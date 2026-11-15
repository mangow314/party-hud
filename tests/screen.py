"""Text checks on rendered sidebar and report output."""

import re
import unicodedata

FRAME = ("╭", "│", "╰", "╔", "║", "╚")


def strip(x):
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", x)


def width(line):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in line)


def widths_ok(text, cols=33):
    """Every box line (starting with a frame character) is exactly cols wide, and there is at least one."""
    lines = [ln for ln in text.splitlines() if ln[:1] in FRAME]
    return bool(lines) and all(width(ln) == cols for ln in lines)


def has_line(pattern, text):
    return any(re.search(pattern, ln) for ln in text.splitlines())
