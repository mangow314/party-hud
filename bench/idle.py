"""What an idle sidebar costs: where the CPU of `run_ui` goes while nothing happens.

  python3 bench/idle.py              # offline, no tmux, about 60 s, stdlib only
  python3 bench/idle.py --live [N]   # inside your real tmux, N seconds (default 30), read only

Offline: the real `run_ui` runs in a pty (34 x 60) with fake tmux replies and a fixed 5-agent snapshot served through the
real `get_snapshot` (snapshot.json in a private state folder), once with one working member, once with none, once more
under cProfile. Only the measuring process patches product functions. A wake is one return of `select.select` in the loop:
the loop polls every 0.1 s and does its once-a-second work when the second is up. CPU is `time.process_time` (this process
only, children excluded); `RUSAGE_CHILDREN` is read where a child is spawned.

--live runs the real `collect()` and `get_snapshot()` in this process and converts what it sees into the CPU a resident
sidebar spends per second. It opens no pane, sends no key, writes no agent file and uses no network. `get_snapshot` writes
snapshot.json by the product's own rules, and it competes with the running sidebars for snapshot.lock. Run it from the
same checkout the sidebars run from, or SNAP_VERSION differs and the copies keep overwriting each other's snapshot.
"""

import argparse
import atexit
import builtins
import cProfile
import fcntl
import importlib
import json
import os
import pstats
import pty
import resource
import select
import shutil
import statistics
import struct
import subprocess
import sys
import tempfile
import termios
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

ROWS, COLS = 60, 34
WARM, SPAN = 3.0, 10.0
REAL_MS_PER_S = 2.5
SKIP = ("disable' of '_lsprof", "select")


def med(xs):
    xs = list(xs)
    return statistics.median(xs) if xs else 0.0


def isolate():
    """A private state folder: PARTY_DIR is read from XDG_RUNTIME_DIR when party_hud.common is first imported."""
    tmp = tempfile.mkdtemp(prefix="party-idle-xdg-")
    atexit.register(shutil.rmtree, tmp, ignore_errors=True)
    os.environ["XDG_RUNTIME_DIR"] = tmp
    os.environ.pop("TMUX_PANE", None)


class Timers:
    """Exclusive CPU (ns) of wrapped functions per category; a wrapped function called from another is the callee's."""

    def __init__(self):
        self.acc: dict[str, int] = {}
        self.count: dict[str, int] = {}
        self.stack: list[list] = []

    def enter(self, cat):
        now = time.process_time_ns()
        if self.stack:
            top = self.stack[-1]
            self.acc[top[0]] = self.acc.get(top[0], 0) + now - top[1]
        self.stack.append([cat, now])
        self.count[cat] = self.count.get(cat, 0) + 1

    def exit(self):
        now = time.process_time_ns()
        cat, start = self.stack.pop()
        self.acc[cat] = self.acc.get(cat, 0) + now - start
        if self.stack:
            self.stack[-1][1] = now

    def wrap(self, mod, name, cat):
        fn = getattr(mod, name)

        def inner(*a, **k):
            self.enter(cat)
            try:
                return fn(*a, **k)
            finally:
                self.exit()

        setattr(mod, name, inner)


class Out:
    """sys.stdout with write and flush time counted, and the frames (they start with a cursor-home) counted."""

    def __init__(self, f, tm, rec):
        self.f, self.tm, self.rec, self.cat = f, tm, rec, "write"

    def write(self, s):
        if s.startswith("\033[H"):
            self.rec.frames += 1
        self.cat = "img" if "_G" in s else "write"
        self.tm.enter(self.cat)
        try:
            return self.f.write(s)
        finally:
            self.tm.exit()

    def flush(self):
        self.tm.enter(self.cat)
        try:
            self.f.flush()
        finally:
            self.tm.exit()

    def __getattr__(self, name):
        return getattr(self.f, name)


class Stop(BaseException):
    pass


class Rec:
    """One record per wake: CPU between two `select.select` calls, split by the exclusive CPU of the wrapped functions."""

    def __init__(self, tm):
        self.tm, self.iters, self.cur, self.frames = tm, [], None, 0

    def open(self):
        self.cur = (time.monotonic(), time.process_time_ns(), dict(self.tm.acc), dict(self.tm.count), self.frames)

    def close(self):
        if self.cur is None:
            return
        t, cpu0, acc0, n0, f0 = self.cur
        n = self.tm.count
        self.iters.append(
            {
                "t": t,
                "cpu0": cpu0,
                "cpu": time.process_time_ns() - cpu0,
                "c": {k: v - acc0.get(k, 0) for k, v in self.tm.acc.items() if v - acc0.get(k, 0)},
                "snaps": n.get("snap", 0) - n0.get("snap", 0),
                "collects": n.get("collect", 0) - n0.get("collect", 0),
                "tmux": n.get("tmux", 0) - n0.get("tmux", 0),
                "frames": self.frames - f0,
            }
        )
        self.cur = None


class Shim:
    """Stands in for the `select` module of party_hud.ui: every wait closes one wake record and opens the next."""

    def __init__(self, rec, profiler):
        self.rec, self.profiler, self.t_first, self.on = rec, profiler, None, False

    def select(self, rl, wl, xl, timeout=None):
        self.rec.close()
        now = time.monotonic()
        self.t_first = self.t_first or now
        if self.profiler and not self.on and now - self.t_first >= WARM:
            self.profiler.enable()
            self.on = True
        if now - self.t_first >= WARM + SPAN:
            if self.profiler:
                self.profiler.disable()
            raise Stop
        result = select.select(rl, wl, xl, timeout)
        self.rec.open()
        return result

    def __getattr__(self, name):
        return getattr(select, name)


def child_main(fixture_path, out_path, mode):
    """The real run_ui, fake outside world. mode "run" records wakes; "profile" runs cProfile over the measured window."""
    isolate()
    from party_hud import collect, common, render, sidebars, ui

    del render
    real_collect = collect.collect
    collect.collect = lambda fixture=None, now=None: real_collect(fixture_path)
    tm, rec = Timers(), None
    calls: list = []
    replies = {"@party_art": "on", "client_termname": "xterm-ghostty"}

    def fake_tmux(*args):
        tm.enter("tmux")
        try:
            calls.append([time.monotonic(), list(args)])
            return next((v for k, v in replies.items() if k in args or k in " ".join(args)), "")
        finally:
            tm.exit()

    ui.tmux = sidebars.tmux = common.tmux = collect.tmux = fake_tmux
    common.tmux_run = sidebars.tmux_run = collect.tmux_run = lambda args, timeout=None: (0, "", "")
    real_run = subprocess.run

    def run(args, *a, **k):
        if args and args[0] == "tmux":
            raise RuntimeError(f"idle bench child started tmux: {args}")
        return real_run(args, *a, **k)

    subprocess.run = run
    rec = Rec(tm)
    profiler = cProfile.Profile(time.process_time) if mode == "profile" else None
    if mode == "run":
        for mod, name, cat in (
            (collect, "collect", "collect"),
            (ui, "get_snapshot", "snap"),
            (ui, "render", "render"),
            (ui, "animate", "render"),
            (ui, "cursor_mtime", "cursor"),
            (ui, "load_cursor", "cursor"),
        ):
            tm.wrap(mod, name, cat)
        sys.stdout = Out(sys.stdout, tm, rec)
    shim = Shim(rec, profiler)
    ui.select = shim
    try:
        ui.run_ui()
    except Stop:
        pass
    if profiler:
        profiler.dump_stats(out_path)
    else:
        with open(out_path, "w") as f:
            json.dump({"t_first": shim.t_first, "iters": rec.iters, "calls": calls}, f)
    ui.leave_without_teardown()


def run_child(mode, fixture_path):
    """Run the child in a pty and drain its output; returns the result file of the child."""
    out_path = f"{fixture_path}.{mode}.out"
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, COLS * 10, ROWS * 20))
    env = dict(os.environ, TMUX="/nonexistent,1,0")
    env.pop("TMUX_PANE", None)
    proc = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--child", fixture_path, out_path, mode],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        close_fds=True,
    )
    os.close(slave)
    tail, deadline = b"", time.monotonic() + WARM + SPAN + 30
    while time.monotonic() < deadline:
        if select.select([master], [], [], 0.5)[0]:
            try:
                data = os.read(master, 65536)
            except OSError:
                break
            if not data:
                break
            tail = (tail + data)[-600:]
        elif proc.poll() is not None:
            break
    os.close(master)
    if proc.poll() is None:
        proc.kill()
    proc.wait()
    if not os.path.exists(out_path):
        raise RuntimeError(f"idle bench child ({mode}) left no result, rc {proc.returncode}: {tail!r}")
    return out_path


CAUSES = (
    ((False, False, False), "poll: 0.1 s select timeout, nothing else"),
    ((True, True, False), "second up: snapshot read, frame redrawn"),
    ((True, False, False), "second up: snapshot read, frame unchanged"),
    ((True, True, True), "second up: snapshot recollected, frame redrawn"),
    ((True, False, True), "second up: snapshot recollected, frame unchanged"),
)
CATS = (
    ("snap", "get_snapshot (read, lock, writes; not collect)"),
    ("collect", "collect (fixture)"),
    ("render", "compute the frame (render, animate)"),
    ("write", "write the frame to the pty"),
    ("img", "image escape sequences"),
    ("tmux", "tmux(...) calls (fake, call overhead only)"),
    ("cursor", "cursor.json (stat, load)"),
)


def window_of(res):
    return [r for r in res["iters"] if r["t"] - res["t_first"] >= WARM]


def report_run(label, res, out):
    w = window_of(res)
    total = w[-1]["cpu0"] + w[-1]["cpu"] - w[0]["cpu0"]
    span = w[-1]["t"] - w[0]["t"]
    out.append(f"\n{label}: {len(w)} wakes in {span:.1f} s, {total / 1e6:.2f} ms CPU, {total / 1e6 / span:.3f} ms/s")
    out.append("| wake cause | wakes | CPU per wake (us, median) | CPU total (ms) |")
    out.append("|---|---:|---:|---:|")
    for key, name in CAUSES:
        rs = [r for r in w if (r["snaps"] > 0, r["frames"] > 0, r["collects"] > 0) == key]
        if rs:
            out.append(
                f"| {name} | {len(rs)} | {med(r['cpu'] for r in rs) / 1e3:.1f} | {sum(r['cpu'] for r in rs) / 1e6:.2f} |"
            )
    inside = sum(r["cpu"] for r in w)
    out.append(f"outside the wake records (select calls and gaps): {(total - inside) / 1e6:.2f} ms")
    out.append("| where the CPU of the wakes goes | ms | share |")
    out.append("|---|---:|---:|")
    named = 0
    for cat, name in CATS:
        ns = sum(r["c"].get(cat, 0) for r in w)
        named += ns
        out.append(f"| {name} | {ns / 1e6:.2f} | {100 * ns / max(1, inside):.0f} % |")
    out.append(
        f"| other (loop body, time calls, polling) | {(inside - named) / 1e6:.2f} | {100 * (inside - named) / max(1, inside):.0f} % |"
    )
    calls = [c for c in res["calls"] if c[0] - res["t_first"] >= WARM]
    early = len(res["calls"]) - len(calls)
    counts: dict[str, int] = {}
    for _, args in calls:
        counts[" ".join(args[:2])] = counts.get(" ".join(args[:2]), 0) + 1
    out.append(
        f"tmux(...) calls in the window: {len(calls)} ({counts or 'none'}); before it (start-up, warm-up): {early}"
    )
    return total, span, len(w), len(calls)


def profile_table(path, out):
    st = pstats.Stats(path).stats  # type: ignore[attr-defined]
    rows = sorted(st.items(), key=lambda kv: kv[1][3], reverse=True)  # type: ignore[union-attr]
    rows = [r for r in rows if not any(s in r[0][2] for s in SKIP)][:15]
    out.append(
        f"\ncProfile of the working window ({SPAN:.0f} s after {WARM:.0f} s warm-up), by cumulative CPU: read the ranking only;"
    )
    out.append("the profiler's own cost inflates every number, and it sees only calls made after it started.")
    out.append("| cumulative (ms) | own (ms) | calls | function |")
    out.append("|---:|---:|---:|---|")
    for (fn, line, name), (_, nc, tt, ct, _) in rows:
        out.append(f"| {ct * 1e3:.2f} | {tt * 1e3:.2f} | {nc} | {os.path.basename(fn)}:{line} {name} |")


def cpu_pair(fn):
    """(CPU of this process, CPU of the children reaped meanwhile, wall) of fn(), all in ms."""
    r0, c0, w0 = resource.getrusage(resource.RUSAGE_CHILDREN), time.process_time_ns(), time.perf_counter_ns()
    fn()
    w1, c1, r1 = time.perf_counter_ns(), time.process_time_ns(), resource.getrusage(resource.RUSAGE_CHILDREN)
    return (c1 - c0) / 1e6, ((r1.ru_utime + r1.ru_stime) - (r0.ru_utime + r0.ru_stime)) * 1e3, (w1 - w0) / 1e6


def stale(path):
    with open(path) as f:
        snap = json.load(f)
    snap["t"] = 0
    with open(path, "w") as f:
        json.dump(snap, f)


def snapshot_paths(fixture_path, out):
    from party_hud import collect
    from party_hud.common import PARTY_DIR

    real = collect.collect
    n = [0]

    def counted(fixture=None, now=None):
        n[0] += 1
        return real(fixture_path)

    collect.collect = counted
    collect.tmux = lambda *a: ""
    path = os.path.join(PARTY_DIR, "snapshot.json")
    cs = [cpu_pair(lambda: real(fixture_path))[0] for _ in range(200)]
    collect_ms = med(cs)
    collect.get_snapshot()
    read = [cpu_pair(collect.get_snapshot)[0] for _ in range(300)]
    read_n = n[0]
    full = []
    for _ in range(60):
        stale(path)
        full.append(cpu_pair(collect.get_snapshot)[0])
    snap = real(fixture_path)
    snap["v"] = 1

    def write_snapshot():
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(snap, f)
        os.replace(tmp, path)

    wr = [cpu_pair(write_snapshot)[0] for _ in range(200)]
    out.append("\nget_snapshot paths, fixture of 5 agents, CPU of this process (ms, median):")
    out.append(f"| read snapshot.json, fresh (collect calls in 300 reads: {read_n - 1}) | {med(read):.3f} |")
    out.append(
        f"| stale: lock, collect, bookkeeping, write snapshot.json (collect calls in 60: {n[0] - read_n}) | {med(full):.3f} |"
    )
    out.append(f"| of which collect(fixture) alone | {collect_ms:.3f} |")
    out.append(f"| of which writing snapshot.json alone (dump, write, os.replace) | {med(wr):.3f} |")
    out.append(
        f"| rest of the stale path (unseen, bells, collections files, flock) | {med(full) - collect_ms - med(wr):.3f} |"
    )
    return collect_ms, med(read), med(full)


def spawn_costs(out):
    out.append("\nstarting one child with subprocess.run (capture_output, text), 30 runs, ms:")
    out.append("| command | parent CPU median | child CPU median | child CPU mean | wall median |")
    out.append("|---|---:|---:|---:|---:|")
    for cmd in ([sys.executable, "-c", "pass"], [shutil.which("true") or "/bin/true"]):
        rs = [
            cpu_pair(lambda cmd=cmd: subprocess.run(cmd, capture_output=True, text=True, check=False))
            for _ in range(30)
        ]
        out.append(
            f"| {os.path.basename(cmd[0])} {' '.join(cmd[1:])} | {med(r[0] for r in rs):.2f} | {med(r[1] for r in rs):.2f} | "
            f"{statistics.mean(r[1] for r in rs):.2f} | {med(r[2] for r in rs):.2f} |"
        )
    out.append("child CPU comes from RUSAGE_CHILDREN deltas, which the kernel may round (compare median and mean).")
    return med(r[0] for r in rs)


def make_fixtures(tmp, fixture):
    paths = {}
    for name, busy in (("working", True), ("calm", False)):
        data = fixture(5)
        for k, s in enumerate(data["sessions"].values()):
            s["status"] = "busy" if busy and k == 0 else "idle"
        paths[name] = os.path.join(tmp, f"{name}.json")
        with open(paths[name], "w") as f:
            json.dump(data, f)
    return paths


def offline():
    t0 = time.monotonic()
    isolate()
    fixture = importlib.import_module("bench").fixture
    out: list[str] = []
    with tempfile.TemporaryDirectory(prefix="party-idle-") as tmp:
        paths = make_fixtures(tmp, fixture)
        with open(run_child("run", paths["working"])) as f:
            work = json.load(f)
        with open(run_child("run", paths["calm"])) as f:
            calm = json.load(f)
        total, span, wakes, ncalls = report_run("working member, run_ui in a pty", work, out)
        ctotal, cspan, _, _ = report_run("control, no member working", calm, out)
        profile_table(run_child("profile", paths["working"]), out)
        collect_ms, read_ms, full_ms = snapshot_paths(paths["working"], out)
        spawn = spawn_costs(out)
    per_s = total / 1e6 / span
    out.append("\nper second, from the offline numbers (ms):")
    out.append(f"| run_ui loop, working member (measured) | {per_s:.3f} |")
    out.append(f"| run_ui loop, no member working (measured) | {ctotal / 1e6 / cspan:.3f} |")
    out.append(
        f"| tmux(...) calls in the loop {ncalls / span:.2f}/s x {spawn:.2f} ms parent CPU per spawn | {ncalls / span * spawn:.3f} |"
    )
    out.append(f"| real machine, bench/live.sh (0.25 %) | {REAL_MS_PER_S:.3f} |")
    out.append(f"| not explained by the offline loop | {REAL_MS_PER_S - per_s - ncalls / span * spawn:.3f} |")
    out.append(
        "offline has no real collect: its tmux and ps children, its reads of agent files and its share of the collections are what --live measures."
    )
    out.append("")
    out.append(f"sidebar idle, 10 s: {wakes} wakes, {total / 1e6:.1f} ms")
    out.append(f"collect, fixture: {collect_ms:.3f} ms")
    out.append(
        f"(offline run took {time.monotonic() - t0:.0f} s; stale path {full_ms:.3f} ms, fresh read {read_ms:.3f} ms)"
    )
    print("\n".join(out))
    return 0


# ---------------------------------------------------------------- --live


class CountedFile:
    """A read-only file object that counts what it returns."""

    def __init__(self, f, stat):
        self._f, self._stat = f, stat

    def read(self, *a):
        d = self._f.read(*a)
        self._stat[1] += len(d)
        return d

    def readline(self, *a):
        d = self._f.readline(*a)
        self._stat[1] += len(d)
        return d

    def readlines(self, *a):
        ds = self._f.readlines(*a)
        self._stat[1] += sum(len(d) for d in ds)
        return ds

    def __iter__(self):
        for d in self._f:
            self._stat[1] += len(d)
            yield d

    def __enter__(self):
        self._f.__enter__()
        return self

    def __exit__(self, *a):
        return self._f.__exit__(*a)

    def __getattr__(self, name):
        return getattr(self._f, name)


class Counters:
    """Counts of what collect() does outside this process: spawned commands and files read."""

    def __init__(self, party_dir):
        self.party_dir = party_dir
        self.reset()

    def reset(self):
        self.cmds: dict[str, list] = {}
        self.files: dict[str, list] = {}

    def install(self):
        real_run, real_open = subprocess.run, builtins.open

        def run(args, *a, **k):
            key = " ".join([os.path.basename(args[0]), *args[1:2]]) if isinstance(args, list) and args else str(args)
            t = time.perf_counter()
            try:
                return real_run(args, *a, **k)
            finally:
                rec = self.cmds.setdefault(key, [0, 0.0])
                rec[0] += 1
                rec[1] += time.perf_counter() - t

        def counting_open(file, mode="r", *a, **k):
            f = real_open(file, mode, *a, **k)
            if isinstance(file, str) and not any(c in mode for c in "wa+x"):
                group = (
                    "/proc"
                    if file.startswith("/proc/")
                    else "party state"
                    if file.startswith(self.party_dir)
                    else "agent files"
                )
                rec = self.files.setdefault(group, [0, 0])
                rec[0] += 1
                return CountedFile(f, rec)
            return f

        subprocess.run = run
        builtins.open = counting_open


def table_cmds(cn, runs, out):
    out.append("| spawned command | calls per collect | wall ms per call |")
    out.append("|---|---:|---:|")
    for key, (n, wall) in sorted(cn.cmds.items(), key=lambda kv: -kv[1][1]):
        out.append(f"| {key} | {n / runs:.1f} | {1e3 * wall / n:.2f} |")
    out.append("| file group | files per collect | bytes returned per collect |")
    out.append("|---|---:|---:|")
    for key, (n, size) in sorted(cn.files.items()):
        out.append(f"| {key} | {n / runs:.1f} | {size / runs:.0f} |")


def live(secs):
    if not os.environ.get("TMUX"):
        print(
            "idle --live: not inside tmux ($TMUX is empty); run it in a tmux pane with the sidebars open",
            file=sys.stderr,
        )
        return 2
    from party_hud import collect, common

    try:
        rc, pane, err = common.tmux_run(["display-message", "-p", "#{pane_id}"], timeout=3)
    except OSError as e:
        print(f"idle --live: cannot run tmux: {e}", file=sys.stderr)
        return 2
    if rc != 0 or not pane.strip():
        print(f"idle --live: tmux did not answer (rc {rc}): {err.strip()}", file=sys.stderr)
        return 2
    from party_hud import render

    cn = Counters(common.PARTY_DIR)
    cn.install()
    out = [f"live, {secs:g} s, party.py from {ROOT}, state folder {common.PARTY_DIR}", ""]
    out.append("1. collect() x 10, in this process")
    rows = []
    for _ in range(10):
        rows.append(cpu_pair(collect.collect))
    cn.reset()
    runs = 10
    for _ in range(runs):
        collect.collect()
    out.append("| run | wall (ms) | this process CPU (ms) | children CPU (ms) |")
    out.append("|---:|---:|---:|---:|")
    for k, (own, child, wall) in enumerate(rows, 1):
        out.append(f"| {k} | {wall:.1f} | {own:.2f} | {child:.2f} |")
    own_med, child_med, wall_med = med(r[0] for r in rows), med(r[1] for r in rows), med(r[2] for r in rows)
    out.append(f"median: wall {wall_med:.1f} ms, own CPU {own_med:.2f} ms, children CPU {child_med:.2f} ms")
    table_cmds(cn, runs, out)
    n_cmds = sum(v[0] for v in cn.cmds.values()) / runs

    out.append(
        f"\n2. get_snapshot() once a second for {secs:g} s (this process competes with the sidebars for snapshot.lock;"
    )
    out.append("   whoever finds the snapshot older than 2 s collects, the others read it)")
    seq_path = os.path.join(common.PARTY_DIR, "collections")

    def seq():
        try:
            with open(seq_path) as f:
                return int(f.read() or 0)
        except (OSError, ValueError):
            return 0

    mine = [0]
    real_collect = collect.collect

    def counted(*a, **k):
        mine[0] += 1
        return real_collect(*a, **k)

    collect.collect = counted
    cn.reset()
    reads, fulls, seq0 = [], [], seq()
    t_start, r0, c0 = time.monotonic(), resource.getrusage(resource.RUSAGE_CHILDREN), time.process_time_ns()
    k = 0
    while time.monotonic() - t_start < secs:
        k += 1
        before = mine[0]
        own, child, _ = cpu_pair(collect.get_snapshot)
        (fulls if mine[0] > before else reads).append((own, child))
        time.sleep(max(0.0, t_start + k - time.monotonic()))
    elapsed = time.monotonic() - t_start
    own_total = (time.process_time_ns() - c0) / 1e6
    r1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    child_total = ((r1.ru_utime + r1.ru_stime) - (r0.ru_utime + r0.ru_stime)) * 1e3
    out.append(
        f"calls {k}: read only {len(reads)}, collected here {len(fulls)}; snapshots collected by anyone in {elapsed:.0f} s: {seq() - seq0}"
    )
    out.append(
        f"this process CPU {own_total:.1f} ms = {own_total / elapsed:.3f} ms/s = {own_total / elapsed / 10:.3f} % of one core"
    )
    out.append(
        f"children CPU     {child_total:.1f} ms = {child_total / elapsed:.3f} ms/s = {child_total / elapsed / 10:.3f} % of one core"
    )
    read_ms = med(r[0] for r in reads)
    out.append(
        f"read-only call, own CPU median {read_ms:.3f} ms"
        if reads
        else "no read-only call happened (this process collected every time)"
    )
    collections_per_s = (seq() - seq0) / elapsed
    table_cmds(cn, 1, out)
    out.append("(commands and files above: totals over the whole section)")
    collect.collect = real_collect

    out.append("\n3. one sidebar frame (render, 33 columns x 60 rows, images on), 30 runs")
    snap = collect.get_snapshot()
    towns = snap["towns"]
    agents = [a for t in towns for a in t["agents"]]
    sel = agents[0]["pane"] if agents else None
    session = (snap.get("here") or {}).get("session")
    args = (towns, 33, sel, None, "sidebar", 60, [], "party", None, int(time.time()), True, session, frozenset())
    frame = ""
    frames = []
    for _ in range(30):
        frames.append(cpu_pair(lambda: render.render(*args))[0])
    frame = render.render(*args)
    with open(os.devnull, "w") as dev:
        writes = [cpu_pair(lambda: (dev.write("\033[H" + frame), dev.flush()))[0] for _ in range(30)]
    t_poll = []
    for _ in range(30):
        t_poll.append(cpu_pair(lambda: [(time.time(), common.cursor_mtime()) for _ in range(100)])[0] / 100)
    frame_ms, write_ms, poll_ms = med(frames), med(writes), med(t_poll)
    out.append(
        f"render {frame_ms:.3f} ms (median, {len(agents)} agents); writing the frame to /dev/null {write_ms:.3f} ms (a pty costs more); one idle poll (time.time + cursor stat) {poll_ms * 1e3:.1f} us"
    )

    out.append("\n4. per second of one resident sidebar (ms), against the 2.5 ms of bench/live.sh")
    out.append("| item | this process | children |")
    out.append("|---|---:|---:|")
    rows4 = [
        ("get_snapshot read of snapshot.json", read_ms if reads else 0.0, 0.0),
        (
            f"collect, {collections_per_s:.2f}/s x per-collect cost",
            own_med * collections_per_s,
            child_med * collections_per_s,
        ),
        ("render, once a second", frame_ms, 0.0),
        ("write the frame (changed every second when a member works)", write_ms, 0.0),
        ("idle polls, 10 a second (time + stat only; the select wake itself is not in it)", poll_ms * 10, 0.0),
    ]
    for name, own, child in rows4:
        out.append(f"| {name} | {own:.3f} | {child:.3f} |")
    own_sum, child_sum = sum(r[1] for r in rows4), sum(r[2] for r in rows4)
    out.append(f"| total | {own_sum:.3f} | {child_sum:.3f} |")
    out.append(
        f"bench/live.sh counts only the process itself: {REAL_MS_PER_S:.3f} measured, {own_sum:.3f} here, gap {REAL_MS_PER_S - own_sum:.3f} ms/s"
    )
    out.append(
        f"each collect spawns {n_cmds:.1f} commands; collections here are shared by all sidebars, the per-sidebar share depends on who wins the lock"
    )
    print("\n".join(out))
    return 0


def main():
    if len(sys.argv) == 5 and sys.argv[1] == "--child":
        child_main(*sys.argv[2:])
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--live", nargs="?", const=30.0, type=float, metavar="SECONDS", help="measure in your real tmux (default 30 s)"
    )
    args = ap.parse_args()
    if args.live is not None:
        return live(args.live)
    return offline()


if __name__ == "__main__":
    raise SystemExit(main())
