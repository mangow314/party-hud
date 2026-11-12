"""Time from the report page's first frame to its first image byte: where the wait goes.

  python3 bench/art.py

Runs the real `ui.run_report` / `ui.run_menu` in a pty (179 x 47) as a child process and reads what it writes with a
timestamp per read. Three scenarios, RUNS runs each, every number is the median in milliseconds:
  (a) the report page opened directly, opening animation on
  (b) the same with the animation off
  (c) `run_menu`: select screen, wait until its images are out, Enter, the report page (only the report page is timed)
Segments (first frame = first `\\x1b[H`, first image = first `a=T`, last image = end of the last image chunk):
  start -> first frame, first frame -> last animation frame (draws within ANIM_TOTAL + 100 ms of it), first image -> last image, and the headline number
  first frame -> first image. The images are sent right after the first frame, so the first image can come before the
  later animation frames. `load_art()` and `import party_hud.ui` are timed on their own.

What it measures: time inside the program. `load_art`, `kitty_image`, the wait constants and the animation are the real
ones. Replaced in the child only: the snapshot, the report source, `capture`, `art_supported` (images forced on) and tmux
(no reply, no delay). It cannot measure what tmux spends forwarding the passthrough or what the terminal spends decoding
and drawing the images. In scenario (c) `fit_report_pane` is not called (it needs TMUX_PANE), so its two tmux round
trips are not included; in (c) `load_art` runs before the select screen, so it is not part of the report segment.
The child sees TMUX set, so images are wrapped in the tmux passthrough as they are in use.
"""

import bisect
import fcntl
import importlib
import json
import os
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
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
from use import make_data

from party_hud import art as art_mod
from party_hud import ui

ROWS, COLS = 47, 179
RUNS = 5
LIMIT = 10.0
IMAGE = re.compile(rb"\x1b_Ga=T,U=1,f=100,i=(\d+)")
IMAGE_BYTES = re.compile(rb"\x1b_G(?:a=T|m=)")
SCENARIOS = [
    ("a", "report page, animation on", "report-anim"),
    ("b", "report page, animation off", "report-static"),
    ("c", "run_menu: select, Enter, report page", "menu"),
]


def child_main(scenario, data_path):
    """Run the real report page or menu with fake outside data. Only this process is patched."""
    from party_hud import collect, common, sidebars

    with open(data_path) as f:
        data = json.load(f)
    pane = data["done"]
    anim = "off" if scenario == "report-static" else "on"
    ui.get_snapshot = lambda fixture=None: {"towns": data["towns"]}
    ui.report_for = lambda a: data["reports"][a["pane"]]
    ui.capture = lambda *a, **k: ""
    ui.mark_seen = lambda *a: None
    ui.art_supported = lambda *a: True
    fake_tmux = lambda *a: anim if "@party_anim" in a else ""
    fake_tmux_run = lambda args, timeout=None: (0, "", "")
    ui.tmux = sidebars.tmux = common.tmux = fake_tmux
    common.tmux_run = sidebars.tmux_run = collect.tmux_run = fake_tmux_run
    real_run = subprocess.run

    def run(args, *a, **k):
        if args and args[0] == "tmux":
            raise RuntimeError(f"bench child started tmux: {args}")
        return real_run(args, *a, **k)

    subprocess.run = run
    if scenario == "menu":
        run_select = ui.run_select
        ui.run_select = lambda sel=None, fixture=None, images=None: run_select(sel or pane, fixture, images)
        ui.run_menu()
    else:
        ui.run_report(pane)


class Capture:
    """Everything the child wrote, with the time each read arrived."""

    def __init__(self, master):
        self.master = master
        self.buf = bytearray()
        self.starts: list[int] = []
        self.times: list[float] = []

    def pump(self, timeout):
        """Read once; False when nothing came within timeout."""
        if not select.select([self.master], [], [], timeout)[0]:
            return False
        try:
            data = os.read(self.master, 65536)
        except OSError:
            data = b""
        if not data:
            raise RuntimeError(f"child closed the pty early: {bytes(self.buf[-300:])!r}")
        self.starts.append(len(self.buf))
        self.times.append(time.monotonic())
        self.buf += data
        return True

    def wait_for(self, pattern, start):
        """Read until pattern matches at or after offset start."""
        end = time.monotonic() + LIMIT
        while not pattern.search(self.buf, start):
            if time.monotonic() > end:
                raise RuntimeError(f"no {pattern.pattern!r} within {LIMIT} s: {bytes(self.buf[-300:])!r}")
            self.pump(0.05)

    def quiet(self, seconds):
        while self.pump(seconds):
            pass

    def time_at(self, offset):
        return self.times[bisect.bisect_right(self.starts, offset) - 1]


def image_name(img_id):
    kinds = [
        (art_mod.PORTRAIT_ID, "portrait"),
        (art_mod.CREST_ID, "crest"),
        (art_mod.BANNER_ID, "banner"),
        (art_mod.BIG_PORTRAIT_ID, "big portrait"),
        (art_mod.LABEL_ID, "label"),
        (art_mod.SELECT_BANNER_ID, "select banner"),
    ]
    return max((k for k in kinds if k[0] <= img_id), key=lambda k: k[0])[1]


def run_once(scenario, data_path):
    """One run; returns {segment: ms} plus the first image's id and the animation frame count."""
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, COLS * 10, ROWS * 20))
    xdg = tempfile.mkdtemp(prefix="party-bench-")
    env = dict(os.environ, TMUX="/nonexistent,1,0", XDG_RUNTIME_DIR=xdg)
    env.pop("TMUX_PANE", None)
    cmd = [sys.executable, os.path.abspath(__file__), "--child", scenario, data_path]
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True)
    os.close(slave)
    cap = Capture(master)
    try:
        base = 0
        if scenario == "menu":
            cap.wait_for(IMAGE, 0)
            cap.quiet(0.5)
            enter = len(cap.buf)
            t0 = time.monotonic()
            os.write(master, b"\r")
            cap.wait_for(re.compile(rb"\x1b\[\?1049h"), enter)
            base = cap.buf.find(b"\x1b[?1049h", enter)
        cap.wait_for(IMAGE, base)
        cap.quiet(0.3)
        os.write(master, b"q")
        end = time.monotonic() + LIMIT
        while proc.poll() is None:
            if time.monotonic() > end:
                raise RuntimeError("child did not exit after q")
            try:
                cap.pump(0.05)
            except RuntimeError:
                break
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        os.close(master)
        shutil.rmtree(xdg, ignore_errors=True)
    first_frame = cap.buf.find(b"\x1b[H", base)
    first_image = IMAGE.search(cap.buf, base)
    assert first_frame >= 0 and first_image
    last_chunk = list(IMAGE_BYTES.finditer(cap.buf, base))[-1].start()
    t_frame = cap.time_at(first_frame)
    window = bisect.bisect_right(cap.times, t_frame + ui.ANIM_TOTAL + 0.1)
    anim_end = cap.starts[window] if window < len(cap.starts) else len(cap.buf)
    frames = cap.buf[first_frame:anim_end].count(b"\x1b[H")
    t_last_frame = cap.time_at(cap.buf.rfind(b"\x1b[H", first_frame, anim_end))
    t_image, t_end = cap.time_at(first_image.start()), cap.time_at(last_chunk)
    ms = 1000.0
    return {
        "start": (t_frame - t0) * ms,
        "anim": (t_last_frame - t_frame) * ms,
        "first": (t_image - t_frame) * ms,
        "send": (t_end - t_image) * ms,
        "id": int(first_image.group(1)),
        "frames": frames,
    }


def time_load_art():
    out = []
    for _ in range(RUNS + 1):
        t = time.perf_counter()
        art_mod.load_art()
        out.append((time.perf_counter() - t) * 1000.0)
    return statistics.median(out[1:])


def time_import():
    out = []
    for _ in range(RUNS):
        t = time.perf_counter()
        subprocess.run([sys.executable, "-c", "import party_hud.ui"], cwd=ROOT, check=True)
        out.append((time.perf_counter() - t) * 1000.0)
    return statistics.median(out)


def main():
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__)
        return
    with tempfile.TemporaryDirectory(prefix="party-bench-data-") as tmp:
        path = os.path.join(tmp, "data.json")
        make_data(path, importlib.import_module("bench").fixture)
        with open(path) as f:
            data = json.load(f)
        data["done"] = [a["pane"] for t in data["towns"] for a in t["agents"]][1]
        with open(path, "w") as f:
            json.dump(data, f)
        print(f"Report page image delay, {COLS} x {ROWS} pty, median of {RUNS} runs, ms\n")
        for key, title, scenario in SCENARIOS:
            runs = [run_once(scenario, path) for _ in range(RUNS)]
            med = {k: statistics.median(r[k] for r in runs) for k in ("start", "anim", "first", "send")}
            first_label = "key -> report first frame" if scenario == "menu" else "process start -> first frame"
            print(f"({key}) {title}")
            print(f"  {first_label:<40}{med['start']:8.1f} ms")
            print(
                f"  {'first frame -> last animation frame':<40}{med['anim']:8.1f} ms  ({runs[-1]['frames']} frames drawn)"
            )
            print(f"  {'first image -> last image':<40}{med['send']:8.1f} ms")
            print(f"  first image is {image_name(runs[-1]['id'])} (id 0x{runs[-1]['id']:x})")
            print(f"first image after first frame: {med['first']:.1f} ms\n")
        print("on their own:")
        print(f"  {'load_art() (56 PNGs, warm cache)':<40}{time_load_art():8.1f} ms")
        print(f"  {'python3 + import party_hud.ui':<40}{time_import():8.1f} ms")
        print(
            f"\nwait constants in party_hud/ui.py: ANIM_TOTAL {ui.ANIM_TOTAL * 1000:.0f} ms, RESIZE_SETTLE {ui.RESIZE_SETTLE * 1000:.0f} ms"
        )


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child_main(sys.argv[2], sys.argv[3])
    else:
        main()
