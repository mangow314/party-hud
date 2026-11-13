"""Shared by every module: colors, status names, classes, text width, tmux calls, state files."""

import functools
import json
import os
import re
import subprocess
import time
import unicodedata
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


C = {
    "fg": (232, 220, 192),
    "dim": (138, 143, 168),
    "gold": (226, 178, 74),
    "amber": (224, 122, 58),
    "code": (140, 207, 224),
    "blue": (127, 167, 232),
    "green": (143, 191, 106),
    "warn": (240, 160, 80),
    "red": (208, 96, 90),
    "line": (58, 66, 102),
    "violet": (183, 138, 208),
    "track": (37, 43, 69),
    "sel": (42, 51, 82),
    "view": (78, 60, 24),
    "hp": (126, 214, 168),
    "sp": (150, 170, 255),
    "model": (190, 180, 255),
}
RESET = "\033[0m"


def fg(name, bold=False):
    r, g, b = C[name]
    return f"\033[{'1;' if bold else ''}38;2;{r};{g};{b}m"


WORKMUX_ICONS = {"🤖": "working", "💬": "waiting", "✅": "done"}
STATUS_TAG = {
    "working": (None, "busy", "blue"),
    "waiting": ("!", "wait", "warn"),
    "done": ("✓", "done", "green"),
    "idle": ("·", "idle", "dim"),
    "sleep": ("z", "zzz", "violet"),
}
STATUS_ORDER = ["waiting", "working", "done", "idle", "sleep"]


# Nerd Font (Material Design) icons; names from nerd-fonts glyphnames.json
CLASSES = [
    "\U000f0787",  # md-sword_cross
    "\U000f0d2e",  # md-sack
    "\U000f09fb",  # md-knife
    "\U000f0953",  # md-cross
    "\U000f0474",  # md-school
    "\U000f1841",  # md-bow_arrow
    "\U000f0093",  # md-flask
    "\U000f075a",  # md-music
]
BUILDINGS = ["\U000f011a", "\U000f0144", "\U000f02de", "\U000f0508"]  # castle church home_variant tent

PARTY_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or os.path.expanduser("~/.cache"), "party-hud")
CLAUDE_SESSIONS = os.path.expanduser("~/.claude/sessions")
CLAUDE_PROJECTS = os.path.expanduser("~/.claude/projects")
SUMMON_ICON = "\U000f03e9"  # md-paw


@functools.lru_cache(maxsize=4096)
def _char_width(ch):
    return 0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in "WF" else 1


def cw(s):
    """Display width: wide CJK = 2, combining marks (placeholder row/column) = 0, everything else = 1."""
    if s.isascii():
        return len(s)
    return sum(map(_char_width, s))


CONTROL = re.compile("[\x00-\x1f\x7f-\x9f]")  # exactly Unicode category Cc, checked over every code point in the tests


def printable(s):
    return CONTROL.sub("", s)


def clip(s, width):
    out, used = "", 0
    for ch in s:
        w = cw(ch)
        if used + w > width:
            return out[: max(0, len(out) - 1)] + "…" if out else ""
        out += ch
        used += w
    return out


CLASS_NAMES = [
    "Warrior",
    "Merchant",
    "Thief",
    "Cleric",
    "Scholar",
    "Hunter",
    "Apothecary",
    "Dancer",
]  # same order as CLASSES


def spread(keys, n):
    """Assign keys to 0..n-1, starting from their hash and taking the next free slot.
    Unique up to n keys; adding or removing a key moves at most the key after it."""
    taken, out = set(), {}
    for key in sorted(set(keys)):
        k = zlib.crc32(key.encode()) % n
        while k in taken and len(taken) < n:
            k = (k + 1) % n
        taken.add(k)
        out[key] = k
    return out


def class_icon(a):
    return CLASSES[a["cls"]]


def bg(name):
    r, g, b = C[name]
    return f"\033[48;2;{r};{g};{b}m"


def tmux(*args):
    return subprocess.run(["tmux", *args], capture_output=True, text=True, check=False).stdout


def tmux_run(args, timeout=None):
    """(returncode, stdout, stderr) of a tmux call; subprocess.run ends the child at the timeout and the rc is None."""
    try:
        r = subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return None, "", ""
    return r.returncode, r.stdout, r.stderr


def capture(pane, color=False):
    return tmux("capture-pane", "-p", *(["-e"] if color else []), "-t", pane).splitlines()


CURSOR = os.path.join(PARTY_DIR, "cursor.json")
CURSOR_KEYS = ("sel", "focus", "squad")


def load_cursor(st):
    try:
        with open(CURSOR) as f:
            saved = json.load(f)
        st.update({k: saved[k] for k in CURSOR_KEYS})
    except (OSError, ValueError, KeyError, TypeError):
        pass


def save_cursor(st):
    try:
        os.makedirs(PARTY_DIR, exist_ok=True)
        tmp = f"{CURSOR}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump({k: st[k] for k in CURSOR_KEYS}, f)
        os.replace(tmp, CURSOR)  # atomic: other sidebars never read a half-written file
    except OSError:
        pass


def cursor_mtime():
    try:
        return os.stat(CURSOR).st_mtime_ns
    except OSError:
        return 0


ERROR_LOG = os.path.join(PARTY_DIR, "error.log")


def log_error():
    import traceback

    try:
        os.makedirs(PARTY_DIR, exist_ok=True)
        with open(ERROR_LOG, "a") as f:
            f.write(f"--- {time.strftime('%F %T')} pane={os.environ.get('TMUX_PANE', '')}\n{traceback.format_exc()}")
    except OSError:
        pass
