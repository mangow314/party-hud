"""Compare animation CPU in a real Ghostty + tmux: redraw placeholders every frame vs. Kitty animation protocol.

Run it inside the tmux pane you want to test; it only measures, it does not pick a winner.

  python3 bench/anim.py --mode redraw --fps 8 --term-pid $(pgrep -o ghostty)
  python3 bench/anim.py --mode kitty  --fps 8 --term-pid $(pgrep -o ghostty)
"""

import argparse
import base64
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from party_hud.art import image_row, kitty_image

BASE_ID = 0x7A0000
COLS, ROWS = 8, 4
IS_LINUX = os.path.isdir("/proc/self")


def tmux_wrap(seq):
    if os.environ.get("TMUX"):
        return "\x1bPtmux;" + seq.replace("\x1b", "\x1b\x1b") + "\x1b\\"
    return seq


def load_frames(paths):
    if not paths:
        paths = sorted(glob.glob(os.path.join(HERE, "..", "art", "*.png")))
    if not paths:
        sys.exit("no PNG frames found")
    frames = []
    for p in paths:
        with open(p, "rb") as f:
            frames.append(f.read())
    return frames


def kitty_frame(img_id, data, gap_ms):
    """a=f: add one animation frame to image img_id; z is the frame gap in ms."""
    b64 = base64.b64encode(data).decode()
    chunks = [b64[i : i + 4096] for i in range(0, len(b64), 4096)]
    out = ""
    for n, chunk in enumerate(chunks):
        head = f"a=f,i={img_id},f=100,z={gap_ms},q=2," if n == 0 else ""
        out += tmux_wrap(f"\x1b_G{head}m={1 if n < len(chunks) - 1 else 0};{chunk}\x1b\\")
    return out


def kitty_play(img_id):
    """a=a: s=3 run, v=1 loop forever."""
    return tmux_wrap(f"\x1b_Ga=a,i={img_id},s=3,v=1,q=2\x1b\\")


def draw_placeholders(img_id):
    return "\x1b[H" + "\r\n".join(image_row(img_id, r, COLS) for r in range(ROWS)) + "\r\n"


def cpu_seconds(pid):
    with open(f"/proc/{pid}/stat") as f:
        rest = f.read().rsplit(")", 1)[1].split()
    return (int(rest[11]) + int(rest[12])) / os.sysconf("SC_CLK_TCK")


def ps_cpu(pid):
    out = subprocess.run(["ps", "-o", "%cpu=", "-p", str(pid)], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


class Meter:
    def __init__(self, pid):
        self.pid = pid
        self.samples = []
        self.start = cpu_seconds(pid) if IS_LINUX else 0.0

    def sample(self):
        if not IS_LINUX:
            self.samples.append(ps_cpu(self.pid))

    def average(self, elapsed):
        if IS_LINUX:
            return (cpu_seconds(self.pid) - self.start) / elapsed * 100
        return sum(self.samples) / len(self.samples) if self.samples else 0.0


def tmux_server_pid():
    tmux = os.environ.get("TMUX")
    if not tmux:
        sys.exit("run inside tmux ($TMUX is not set)")
    return int(tmux.split(",")[1])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=("redraw", "kitty"), required=True)
    ap.add_argument("--fps", type=float, required=True)
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--frames", nargs="*", help="PNG files to cycle (default: art/*.png)")
    ap.add_argument("--term-pid", type=int, help="terminal process pid; omit to measure tmux only")
    args = ap.parse_args()

    server_pid = tmux_server_pid()
    subprocess.run(["tmux", "set-option", "-p", "allow-passthrough", "on"], check=True)
    frames = load_frames(args.frames)
    gap_ms = max(1, round(1000 / args.fps))

    out = sys.stdout
    if args.mode == "redraw":
        for k, data in enumerate(frames):
            out.write(kitty_image(BASE_ID + k, data, COLS, ROWS))
    else:
        out.write(kitty_image(BASE_ID, frames[0], COLS, ROWS))
        for data in frames[1:]:
            out.write(kitty_frame(BASE_ID, data, gap_ms))
        out.write(kitty_play(BASE_ID))
        out.write(draw_placeholders(BASE_ID))
    out.flush()

    meters = {"tmux": Meter(server_pid)}
    if args.term_pid:
        meters["term"] = Meter(args.term_pid)

    t0 = time.monotonic()
    next_sample = t0 + 1
    tick = 0
    while (now := time.monotonic()) - t0 < args.seconds:
        if args.mode == "redraw":
            out.write(draw_placeholders(BASE_ID + tick % len(frames)))
            out.flush()
            tick += 1
            delay = t0 + tick / args.fps - time.monotonic()
        else:
            delay = min(next_sample, t0 + args.seconds) - now
        if now >= next_sample:
            for m in meters.values():
                m.sample()
            next_sample += 1
        if delay > 0:
            time.sleep(delay)
    elapsed = time.monotonic() - t0

    tmux_cpu = meters["tmux"].average(elapsed)
    term_cpu = f"{meters['term'].average(elapsed):.1f}" if "term" in meters else "n/a"
    print(f"\nmode={args.mode} fps={args.fps:g} seconds={args.seconds:g} tmux_cpu={tmux_cpu:.1f}% term_cpu={term_cpu}%")


if __name__ == "__main__":
    main()
