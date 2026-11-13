"""Where the memory and the start-up time go: RSS of the three long-running processes, the cost of every import, and the
time from spawn to the first frame of the select screen.

  python3 bench/mem.py

About 60 s, no tmux, stdlib only; Linux and macOS (RSS from `/proc/<pid>/status` VmRSS, else `ps -o rss= -p`). Four parts:
  1. RSS of the sidebar (`run_ui`), the select screen (`run_menu`, which runs `run_select`) and the report page
     (`run_report`) in a pty (179 x 47), read from outside, after the first frame and its images, after 5 s idle and after
     a round of keys. RUNS runs each, median; the three kinds of a run go at the same time.
  2. RSS and time of fresh `python3` processes: empty, the standard library modules the product imports (read from the
     module-level import statements of `party.py` and `party_hud/*.py`), then `party_hud.common` ... `party_hud.ui` one more module
     per process, then `load_art()`; and the RSS added by each of those standard library modules alone.
  3. (the table of which sub-command needs which module is in docs/performance.md, read from the code)
  4. Spawn to first frame and first image of `run_menu`, split into segments timed inside the child.

What it measures: the real `party_hud.ui` functions in a child process with only the outside world replaced (a fixed
snapshot and reports from `bench/use.py`, `capture`, `tmux`, the cursor file, `art_supported` forcing images on).
`load_art` and `kitty_image` are real and the images are really written to the pty. `import party` plus `party_hud.ui` is what the
long-running sub-commands pay; the children never run `party.main`. Every child imports `time` first (a built-in module) to take its
clock; the empty-Python row includes it.
"""

import ast
import concurrent.futures
import fcntl
import glob
import importlib
import json
import os
import platform
import pty
import re
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
from use import make_data

ROWS, COLS = 47, 179
RUNS = 3
STARTUP_RUNS = 5
LIMIT = 15.0
IMAGE = re.compile(rb"a=T,U=1,f=100")
KINDS = ["sidebar", "select", "report"]
PHASES = ["after first frame", "after 5 s idle", "after use"]
MODULES = [
    "party_hud.common",
    "party_hud.art",
    "party_hud.collect",
    "party_hud.render",
    "party_hud.sidebars",
    "party_hud.ui",
]
SIDEBAR_PANE = "%99"

# keys of the use round: (key, seconds to wait for the first output, seconds of quiet that count as drawn)
USE = {
    "sidebar": [(k, 0.4, 0.3) for k in "jkjkJKnnjk"],
    "select": [(k, 1.0, 0.5) for k in "kkkk"],
    "report": [("n", 1.5, 0.6)] * 5 + [(k, 0.3, 0.15) for k in "jjjkk"],
}

CHILD = r"""
import sys, time
T0 = time.time()
P0 = time.perf_counter()
import party
import json, os, subprocess
from party_hud import collect, common, sidebars, ui
P1 = time.perf_counter()

kind, data_path, out_path = sys.argv[1:4]
with open(data_path) as f:
    data = json.load(f)
me = os.environ.get("TMUX_PANE", "")
snap = {"towns": data["towns"], "panes": {me: {"visible": True, "window_panes": 2}} if me else {}, "here": None}
ui.get_snapshot = lambda fixture=None: snap
ui.report_for = lambda a: data["reports"][a["pane"]]
ui.capture = lambda *a, **k: ""
ui.mark_seen = lambda *a: None
ui.mark_sidebar = lambda *a: None
ui.install_hooks = lambda *a: None
ui.cursor_mtime = lambda: 0.0
ui.load_cursor = lambda st: None
ui.save_cursor = lambda st: None
ui.art_supported = lambda *a: True
fake_tmux = lambda *a: "on" if "@party_anim" in a else ""
fake_tmux_run = lambda args, timeout=None: (0, "", "")
ui.tmux = sidebars.tmux = common.tmux = fake_tmux
common.tmux_run = sidebars.tmux_run = collect.tmux_run = fake_tmux_run
real_run = subprocess.run

def run(args, *a, **k):
    if args and args[0] == "tmux":
        raise RuntimeError("bench child started tmux: %r" % (args,))
    return real_run(args, *a, **k)

subprocess.run = run
run_select = ui.run_select
ui.run_select = lambda sel=None, fixture=None, images=None: run_select(sel or data["working"], fixture, images)

marks = {}
if kind == "startup":
    def timed(name, fn):
        def wrapper(*a, **k):
            if name in marks:
                return fn(*a, **k)
            t = time.perf_counter()
            try:
                return fn(*a, **k)
            finally:
                marks[name] = time.perf_counter() - t
        return wrapper

    ui.load_images = timed("load_images", ui.load_images)
    ui.get_snapshot = timed("snapshot", ui.get_snapshot)
    ui.render_select = timed("render", ui.render_select)

    class Out:
        def __init__(self, f):
            self.f, self.armed = f, []

        def write(self, text):
            t = time.perf_counter()
            if text.startswith("\033[H") and "frame_at" not in marks and not any(n == "frame" for n, _ in self.armed):
                self.armed.append(("frame", t))
            if "a=T" in text and "image_at" not in marks and not any(n == "image" for n, _ in self.armed):
                self.armed.append(("image", t))
            return self.f.write(text)

        def flush(self):
            self.f.flush()
            t = time.perf_counter()
            for name, start in self.armed:
                if name == "frame":
                    marks["write"] = t - start
                    marks["frame_at"] = t - P0
                else:
                    marks["image_at"] = t - P0
            self.armed = []

        def __getattr__(self, name):
            return getattr(self.f, name)

    sys.stdout = Out(sys.stdout)

PR = time.perf_counter()
if kind == "sidebar":
    ui.run_ui()
elif kind == "report":
    ui.run_report(data["done"])
else:
    ui.run_menu()
if kind == "startup":
    with open(out_path, "w") as f:
        json.dump(dict(marks, T0=T0, imported=P1 - P0, run_at=PR - P0), f)
ui.leave_without_teardown()
"""

STATE = """
import sys, time
t = time.perf_counter()
%s
d = time.perf_counter() - t
sys.stdout.write("%%r\\n" %% d)
sys.stdout.flush()
sys.stdin.readline()
"""


def rss_mb(pid):
    """RSS of a live process in MB, read from outside."""
    path = f"/proc/{pid}/status"
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
        raise RuntimeError(f"no VmRSS in {path}")
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, check=True).stdout
    return int(out.strip()) / 1024


class Pty:
    """A child of CHILD in a pty: its output is read and dropped, its keys are written, its RSS is read from here."""

    def __init__(self, kind, data_path, out_path):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, COLS * 10, ROWS * 20))
        self.xdg = tempfile.mkdtemp(prefix="party-bench-")
        env = dict(os.environ, TMUX="/nonexistent,1,0", XDG_RUNTIME_DIR=self.xdg)
        env.pop("TMUX_PANE", None)
        if kind == "sidebar":
            env["TMUX_PANE"] = SIDEBAR_PANE
        cmd = [sys.executable, "-c", CHILD, kind, data_path, out_path]
        self.spawned = time.time()
        self.proc = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave, env=env, cwd=ROOT, close_fds=True)
        os.close(slave)
        self.master, self.eof, self.tail, self.window = master, False, b"", b""

    def pump(self, timeout):
        """Read once; False when nothing came within timeout or the child closed the pty."""
        if not select.select([self.master], [], [], timeout)[0]:
            return False
        try:
            data = os.read(self.master, 65536)
        except OSError:
            data = b""
        if not data:
            self.eof = True
            return False
        self.tail = (self.tail + data)[-400:]
        self.window = self.window[-30:] + data
        return True

    def alive(self):
        if self.eof:
            raise RuntimeError(f"child closed the pty early: {self.tail!r}")

    def wait_for_image(self):
        end = time.monotonic() + LIMIT
        while not IMAGE.search(self.window):
            if time.monotonic() > end:
                raise RuntimeError(f"no image within {LIMIT} s: {self.tail!r}")
            self.pump(0.05)
            self.alive()

    def quiet(self, gap, limit=4.0):
        """Read until nothing comes for gap seconds (at most limit)."""
        end = time.monotonic() + limit
        while time.monotonic() < end and self.pump(gap):
            pass
        self.alive()

    def drain(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.pump(min(0.1, end - time.monotonic()))
        self.alive()

    def send(self, key, first, settle):
        """One key, then wait for its drawing: the first output within first seconds, then settle seconds of quiet."""
        os.write(self.master, key.encode())
        end = time.monotonic() + first
        while time.monotonic() < end and not self.pump(0.02):
            pass
        self.quiet(settle)

    def rss(self):
        self.alive()
        return rss_mb(self.proc.pid)

    def close(self):
        """Send q and wait for the exit."""
        os.write(self.master, b"q")
        end = time.monotonic() + 5.0
        while self.proc.poll() is None:
            if time.monotonic() > end:
                raise RuntimeError(f"child did not exit after q: {self.tail!r}")
            self.pump(0.05)
        while self.pump(0):
            pass

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        os.close(self.master)
        shutil.rmtree(self.xdg, ignore_errors=True)


def run_rss(kind, data_path):
    """[RSS after first frame, after 5 s idle, after use] of one process of kind."""
    p = Pty(kind, data_path, "")
    try:
        p.wait_for_image()
        p.quiet(0.5)
        out = [p.rss()]
        p.drain(5.0)
        out.append(p.rss())
        for key, first, settle in USE[kind]:
            p.send(key, first, settle)
        out.append(p.rss())
        p.close()
        return out
    finally:
        p.kill()


def run_startup(data_path, out_dir):
    """Segments in ms of one fresh run_menu, from spawn to the first frame and first image."""
    out_path = os.path.join(out_dir, "startup.json")
    p = Pty("startup", data_path, out_path)
    try:
        p.wait_for_image()
        p.quiet(0.3)
        p.close()
    finally:
        p.kill()
    with open(out_path) as f:
        m = json.load(f)
    ms = 1000.0
    begin = (m["T0"] - p.spawned) * ms
    imported = m["imported"] * ms
    run_at = m["run_at"]
    others = (m["frame_at"] - run_at - m["load_images"] - m["snapshot"] - m["render"] - m["write"]) * ms
    return {
        "Python start (spawn to first line)": begin,
        "import party + party_hud.ui": imported,
        "load_images": m["load_images"] * ms,
        "first get_snapshot": m["snapshot"] * ms,
        "first render_select": m["render"] * ms,
        "first frame write + flush": m["write"] * ms,
        "rest of run_menu until the frame": others,
        "= first frame at": begin + imported + (m["frame_at"] - run_at) * ms,
        "= first image written at": begin + imported + (m["image_at"] - run_at) * ms,
    }


def state_run(body):
    """(RSS MB read from outside, seconds the body took inside) of a fresh python3 that runs body and waits."""
    p = subprocess.Popen(
        [sys.executable, "-c", STATE % body],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        cwd=ROOT,
    )
    assert p.stdin and p.stdout
    try:
        seconds = float(p.stdout.readline())
        rss = rss_mb(p.pid)
        p.stdin.write("\n")
        p.stdin.close()
    finally:
        p.stdout.close()
        p.wait()
    return rss, seconds


def state(body, runs=RUNS):
    out = [state_run(body) for _ in range(runs)]
    return statistics.median(r for r, _ in out), statistics.median(s for _, s in out) * 1000.0


def product_stdlib():
    """Standard library modules imported at module level by party.py and party_hud/*.py (imports inside functions are not start-up cost)."""
    names = set()
    for path in [os.path.join(ROOT, "party.py"), *sorted(glob.glob(os.path.join(ROOT, "party_hud", "*.py")))]:
        with open(path) as f:
            tree = ast.parse(f.read())
        for node in tree.body:
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return sorted(n for n in names if n in sys.stdlib_module_names)


def rss_part(data_path):
    runs = {k: [] for k in KINDS}
    for _ in range(RUNS):
        with concurrent.futures.ThreadPoolExecutor(len(KINDS)) as pool:
            for kind, res in zip(KINDS, pool.map(lambda k: run_rss(k, data_path), KINDS)):
                runs[kind].append(res)
    print(f"1. RSS of the three processes, {COLS} x {ROWS} pty, median of {RUNS} runs, MB (read from outside)\n")
    for kind in KINDS:
        for i, phase in enumerate(PHASES):
            values = [r[i] for r in runs[kind]]
            print(f"{kind} RSS {phase}: {statistics.median(values):.1f} MB")
            print(f"  runs: {' '.join(f'{v:.1f}' for v in values)}")
        print()


def import_part():
    print("2. import cost: a fresh python3 per state, median of 3, RSS read from outside, time inside\n")
    libs = product_stdlib()
    print(f"standard library modules the product imports ({len(libs)}): {', '.join(libs)}\n")
    stdlib = "import " + ", ".join(libs)
    states = [("empty Python", ""), ("standard library only", stdlib)]
    states += [(f"+ import {m}", stdlib + "\nimport " + ", ".join(MODULES[: i + 1])) for i, m in enumerate(MODULES)]
    states.append(("+ load_art()", f"{stdlib}\nimport {', '.join(MODULES)}\nart = party_hud.art.load_art()"))
    print(f"{'state':<36}{'RSS MB':>8}{'+ MB':>7}{'ms':>9}{'+ ms':>8}")
    prev = None
    empty_rss = 0.0
    for name, body in states:
        rss, ms = state(body)
        empty_rss = rss if prev is None else empty_rss
        d_rss, d_ms = ("", "") if prev is None else (f"{rss - prev[0]:.1f}", f"{ms - prev[1]:.1f}")
        print(f"{name:<36}{rss:8.1f}{d_rss:>7}{ms:9.1f}{d_ms:>8}")
        prev = (rss, ms)
    print("\nRSS added by one standard library module alone, over empty Python (above 0.1 MB):")
    each = sorted(((state(f"import {m}")[0] - empty_rss, m) for m in libs), reverse=True)
    for added, m in each:
        if added > 0.1:
            print(f"  {m:<18}{added:6.1f} MB")
    print()


def startup_part(data_path, out_dir):
    runs = [run_startup(data_path, out_dir) for _ in range(STARTUP_RUNS)]
    print(f"4. a fresh run_menu, spawn to first frame and first image, median of {STARTUP_RUNS} runs, ms\n")
    for key in runs[0]:
        print(f"  {key:<38}{statistics.median(r[key] for r in runs):8.1f} ms")
    print()


def main():
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__)
        return
    print(f"{platform.platform()}, Python {platform.python_version()}\n")
    with tempfile.TemporaryDirectory(prefix="party-bench-data-") as tmp:
        path = os.path.join(tmp, "data.json")
        make_data(path, importlib.import_module("bench").fixture)
        with open(path) as f:
            data = json.load(f)
        data["done"] = [a["pane"] for t in data["towns"] for a in t["agents"]][1]
        with open(path, "w") as f:
            json.dump(data, f)
        rss_part(path)
        import_part()
        startup_part(path, tmp)


if __name__ == "__main__":
    main()
