"""Benchmark of the select screen and report page in use: a fixed key script in a pty, CPU time per step.

The parent starts `python3 bench/use.py --child DATA` in a pty (179 x 47), sends the keys of STEPS on a fixed schedule
and reads the output like a terminal. The child runs the real `run_menu` with the outside world replaced (see
`child_main`): a fixed snapshot and fixed reports, no tmux, images on. CPU time of a step is the growth of the child's
user+sys time between the start and the end of the step. The whole script runs RUNS times; every number is the median.
"""

import fcntl
import json
import os
import pty
import select
import shutil
import signal
import statistics
import struct
import subprocess
import sys
import tempfile
import termios
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
ROWS, COLS = 47, 179
RUNS = 3
EXIT_WAIT = 5.0

# (name, keys as (seconds after the step starts, bytes), seconds the step lasts, start a new process, wait for exit)
STEPS = [
    ("open select", [], 2.0, True, False),
    ("idle on working", [], 5.0, False, False),
    ("k x4, new members", [(0.0, "k"), (1.0, "k"), (2.0, "k"), (3.0, "k")], 4.0, False, False),
    ("j x3, seen members", [(0.0, "j"), (1.0, "j"), (2.0, "j")], 3.0, False, False),
    ("Enter, open report", [(0.0, "\r")], 2.5, False, False),
    ("scroll j j j k k", [(0.0, "j"), (0.5, "j"), (1.0, "j"), (1.5, "k"), (2.0, "k")], 3.0, False, False),
    ("n, next member", [(0.0, "n")], 2.5, False, False),
    ("h, back to select", [(0.0, "h")], 2.5, False, False),
    ("q, close", [(0.0, "q")], 0.0, False, True),
    ("reopen, then q", [(3.0, "q")], 3.0, True, True),
]


def report_text(k):
    """About 70 source lines of Markdown, different for every k so that the layout cache cannot reuse another member's."""
    return "\n".join(
        [f"## Summary {k}", "", f"Agent {k} finished task number {k * 7 + 3}.", ""]
        + [f"- step {i}: changed `module_{k}_{i}.py` and ran the tests for case {k * i}, all green" for i in range(30)]
        + ["", f"## Details {k}", ""]
        + [
            f"Paragraph {i} of {k}: a longer line of **bold** and `code` text about item {i * k + 1}, long enough that "
            "it has to be wrapped to fit the width of the right column."
            for i in range(20)
        ]
        + ["", "```", *[f"code line {i} of {k}" for i in range(10)], "```"]
    )


def make_data(path, fixture):
    """Write the fixed snapshot and reports the child serves: 5 leads, waiting first, working last, 70-line reports."""
    from party_hud.collect import collect

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(fixture(5), f)
    try:
        towns = collect(f.name)["towns"]
    finally:
        os.unlink(f.name)
    now = time.time()
    agents = [a for t in towns for a in t["agents"]]
    status = ["waiting", "done", "done", "done", "working"]
    task = {
        "ask": "do the thing",
        "files": ["a.py"],
        "cmds": 2,
        "agents": 0,
        "dir": "~/x",
        "branch": "main",
        "cwd": "/x",
    }
    reports = {}
    for k, a in enumerate(agents):
        a["status"], a["round"] = status[k], 1
        final = {"text": report_text(k), "start": now - 900.37, "end": now - 300.37, "task": task, "subagents": []}
        if a["status"] == "working":
            reports[a["pane"]] = {
                "live": True,
                "task": task,
                "start": now - 200.37,
                "end": None,
                "tool": "Bash ls -la",
                "said": "working on it, reading the files first",
                "prev": final,
            }
        else:
            reports[a["pane"]] = final | {"end": now - 30.37 if a["status"] == "waiting" else final["end"]}
    with open(path, "w") as f:
        json.dump({"towns": towns, "reports": reports, "working": agents[-1]["pane"]}, f)


def child_main(data_path):
    """Run the real select screen and report page with fake outside data. Only this process is patched."""
    sys.path.insert(0, os.path.abspath(ROOT))
    from party_hud import collect, common, sidebars, ui

    with open(data_path) as f:
        data = json.load(f)
    ui.get_snapshot = lambda fixture=None: {"towns": data["towns"]}
    ui.report_for = lambda a: data["reports"][a["pane"]]
    ui.capture = lambda *a, **k: ""
    ui.mark_seen = lambda *a: None
    ui.art_supported = lambda *a: True
    fake_tmux = lambda *a: "on" if "@party_anim" in a else ""
    fake_tmux_run = lambda args, timeout=None: (0, "", "")
    ui.tmux = sidebars.tmux = common.tmux = fake_tmux
    common.tmux_run = sidebars.tmux_run = collect.tmux_run = fake_tmux_run
    real_run = subprocess.run

    def run(args, *a, **k):
        if args and args[0] == "tmux":
            raise RuntimeError(f"bench child started tmux: {args}")
        return real_run(args, *a, **k)

    subprocess.run = run
    run_select = ui.run_select
    ui.run_select = lambda sel=None, fixture=None, images=None: run_select(sel or data["working"], fixture, images)
    ui.run_menu()
    ui.leave_without_teardown()


def cpu_seconds(pid):
    """user+sys seconds of a live single-threaded process: /proc schedstat (ns) or stat (10 ms ticks) on Linux, `ps -o time=` (10 ms) elsewhere."""
    if os.path.exists(f"/proc/{pid}/schedstat"):
        with open(f"/proc/{pid}/schedstat") as f:
            return int(f.read().split()[0]) / 1e9
    if os.path.exists(f"/proc/{pid}/stat"):
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
    out = subprocess.run(["ps", "-o", "time=", "-p", str(pid)], capture_output=True, text=True, check=True).stdout
    days, _, rest = out.strip().rpartition("-")
    seconds = 0.0
    for part in rest.split(":"):
        seconds = seconds * 60 + float(part)
    return seconds + 86400 * int(days or 0)


class Child:
    def __init__(self, cmd):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, COLS * 10, ROWS * 20))
        self.xdg = tempfile.mkdtemp(prefix="party-bench-")
        env = dict(os.environ, TMUX="/nonexistent,1,0", XDG_RUNTIME_DIR=self.xdg)
        env.pop("TMUX_PANE", None)
        self.proc = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True)
        os.close(slave)
        self.master, self.open, self.written, self.tail = master, True, 0, b""
        self.rusage, self.closed = None, False

    def read(self, timeout):
        """Read and count what the child wrote; wait at most timeout."""
        if not self.open:
            time.sleep(min(timeout, 0.01))
            return
        if select.select([self.master], [], [], timeout)[0]:
            try:
                data = os.read(self.master, 65536)
            except OSError:
                data = b""
            if data:
                self.written += len(data)
                self.tail = (self.tail + data)[-1500:]
            else:
                self.open = False

    def poll(self):
        """True once the child has exited (its rusage is then in self.rusage)."""
        if self.rusage is None:
            pid, status, usage = os.wait4(self.proc.pid, os.WNOHANG)
            if pid:
                self.rusage, self.proc.returncode = usage, os.waitstatus_to_exitcode(status)
        return self.rusage is not None

    def kill(self):
        if self.rusage is None:
            self.proc.kill()
            self.rusage = os.wait4(self.proc.pid, 0)[2]
        if not self.closed:
            self.closed = True
            os.close(self.master)
            shutil.rmtree(self.xdg, ignore_errors=True)


def play(cmd):
    """Run STEPS once with the child command cmd; return {cpu_pct, seconds, peak_rss_mb, steps}."""
    steps, peak, total_cpu = [], 0.0, 0.0
    child, cpu_prev = None, 0.0
    t_start = time.monotonic()
    try:
        for name, keys, secs, spawn, wait_exit in STEPS:
            if spawn:
                child, cpu_prev = Child(cmd), 0.0
            assert child
            written_prev, t0 = child.written, time.monotonic()
            pending = list(keys)
            while True:
                now = time.monotonic() - t0
                while pending and now >= pending[0][0]:
                    os.write(child.master, pending.pop(0)[1].encode())
                if child.poll():
                    if not wait_exit or pending:
                        raise RuntimeError(f"child exited early in step {name!r}: {child.tail!r}")
                    break
                if not pending and now >= secs and not wait_exit:
                    break
                if wait_exit and not pending and now >= secs + EXIT_WAIT:
                    raise RuntimeError(f"child did not exit after step {name!r}: {child.tail!r}")
                due = pending[0][0] if pending else secs
                child.read(max(0.0, min(0.05, due - now)))
            if wait_exit:
                while child.open and select.select([child.master], [], [], 0)[0]:
                    child.read(0)
                usage = child.rusage
                assert usage
                cpu = usage.ru_utime + usage.ru_stime
                peak = max(peak, usage.ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024))
                child.kill()
            else:
                cpu = cpu_seconds(child.proc.pid)
            steps.append(
                {
                    "name": name,
                    "cpu_ms": round((cpu - cpu_prev) * 1000, 1),
                    "out_kb": round((child.written - written_prev) / 1024, 1),
                }
            )
            total_cpu += cpu - cpu_prev
            cpu_prev = cpu
    finally:
        if child:
            child.kill()
    seconds = time.monotonic() - t_start
    return {
        "cpu_pct": round(100 * total_cpu / seconds, 3),
        "seconds": round(seconds, 1),
        "peak_rss_mb": round(peak, 1),
        "steps": steps,
    }


def measure(fixture, cmd=None, runs=RUNS):
    """Median of runs plays. cmd defaults to this file as the child; every run gets a fresh data file."""
    out = []
    with tempfile.TemporaryDirectory(prefix="party-bench-data-") as tmp:
        path = os.path.join(tmp, "data.json")
        for _ in range(runs):
            make_data(path, fixture)
            out.append(play(cmd or [sys.executable, os.path.abspath(__file__), "--child", path]))
    mid = statistics.median
    return {
        "cpu_pct": round(mid(r["cpu_pct"] for r in out), 3),
        "seconds": round(mid(r["seconds"] for r in out), 1),
        "peak_rss_mb": round(max(r["peak_rss_mb"] for r in out), 1),
        "runs": runs,
        "run_cpu_pct": [r["cpu_pct"] for r in out],
        "steps": [
            {
                "name": s["name"],
                "cpu_ms": round(mid(r["steps"][i]["cpu_ms"] for r in out), 1),
                "out_kb": round(mid(r["steps"][i]["out_kb"] for r in out), 1),
            }
            for i, s in enumerate(out[0]["steps"])
        ],
    }


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: os._exit(1))
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        child_main(sys.argv[2])
    else:
        raise SystemExit("run it through bench/bench.py")
