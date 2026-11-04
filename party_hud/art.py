"""Portraits and crests: load art/, send images with the Kitty graphics protocol, draw placeholders."""

import base64
import os

from .common import RESET, ROOT, spread

ART_DIR = os.path.join(ROOT, "art")
PORTRAIT_FILES = [
    "swordsman",
    "merchant",
    "thief",
    "cleric",
    "scholar",
    "hunter",
    "apothecary",
    "dancer",
]  # same order as CLASS_NAMES
CREST_FILES = ["lion", "eagle", "wolf", "dragon", "stag", "phoenix", "sun", "moon"]
PORTRAIT_CELLS, CREST_CELLS = (6, 3), (4, 2)
PORTRAIT_ID, CREST_ID = 0x7A0100, 0x7A0200  # image id, also the placeholder's 24-bit foreground color
# U+10EEEE placeholders carry row and column as diacritics (first 16 of kitty gen/rowcolumn-diacritics.txt)
DIAC = [
    0x0305,
    0x030D,
    0x030E,
    0x0310,
    0x0312,
    0x033D,
    0x033E,
    0x033F,
    0x0346,
    0x034A,
    0x034B,
    0x034C,
    0x0350,
    0x0351,
    0x0352,
    0x0357,
]
ART_MIN_WIDTH = 30


def load_art():
    """art/ -> {image id: (PNG bytes, cols, rows)}, or None if any of the 16 images is missing."""
    art = {}
    for base, prefix, names, cells in (
        (PORTRAIT_ID, "portrait", PORTRAIT_FILES, PORTRAIT_CELLS),
        (CREST_ID, "crest", CREST_FILES, CREST_CELLS),
    ):
        for k, name in enumerate(names):
            try:
                with open(os.path.join(ART_DIR, f"{prefix}-{name}.png"), "rb") as f:
                    art[base + k] = (f.read(), *cells)
            except OSError:
                return None
    return art


ART_TERMS = ("ghostty", "kitty")


def art_supported(option, termname):
    """Use images? @party_art on/off wins; else the outer terminal (client_termname, carried over SSH) must be Ghostty or Kitty. Others lack Unicode placeholders and would show garbage."""
    if option in ("on", "off"):
        return option == "on"
    return any(t in termname for t in ART_TERMS)


def portrait_id(a):
    return PORTRAIT_ID + a["cls"]


def crest_ids(names):
    return {name: CREST_ID + k for name, k in spread(names, len(CREST_FILES)).items()}


def kitty_image(img_id, data, cols, rows):
    """Send one PNG: a=T transmit, U=1 virtual placement of cols x rows cells, q=2 no reply, 4096-byte base64 chunks.
    Wrapped in tmux passthrough. tmux forwards it only for visible panes, so resend when one becomes visible."""
    b64 = base64.b64encode(data).decode()
    chunks = [b64[i : i + 4096] for i in range(0, len(b64), 4096)]
    out = ""
    for n, chunk in enumerate(chunks):
        head = f"a=T,U=1,f=100,i={img_id},c={cols},r={rows},q=2," if n == 0 else ""
        seq = f"\x1b_G{head}m={1 if n < len(chunks) - 1 else 0};{chunk}\x1b\\"
        if os.environ.get("TMUX"):
            seq = "\x1bPtmux;" + seq.replace("\x1b", "\x1b\x1b") + "\x1b\\"
        out += seq
    return out


def image_row(img_id, row, cols):
    """Placeholder cells for one row of an image: foreground = image id, U+10EEEE + row + column."""
    r, g, b = img_id >> 16 & 255, img_id >> 8 & 255, img_id & 255
    cells = "".join(chr(0x10EEEE) + chr(DIAC[row]) + chr(DIAC[c]) for c in range(cols))
    return f"\033[38;2;{r};{g};{b}m{cells}{RESET}"
