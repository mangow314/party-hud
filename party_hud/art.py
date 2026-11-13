"""Portraits, crests, banners and heading labels: load art/, send images with the Kitty graphics protocol, draw placeholders."""

import base64
import os

from .common import RESET, ROOT, log_error, spread

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
# U+10EEEE placeholders carry row and column as diacritics (all 297 of kitty gen/rowcolumn-diacritics.txt)
DIAC_HEX = (
    "0305 030D 030E 0310 0312 033D 033E 033F 0346 034A 034B 034C 0350 0351 0352 0357 035B 0363 0364 0365 "
    "0366 0367 0368 0369 036A 036B 036C 036D 036E 036F 0483 0484 0485 0486 0487 0592 0593 0594 0595 0597 "
    "0598 0599 059C 059D 059E 059F 05A0 05A1 05A8 05A9 05AB 05AC 05AF 05C4 0610 0611 0612 0613 0614 0615 "
    "0616 0617 0657 0658 0659 065A 065B 065D 065E 06D6 06D7 06D8 06D9 06DA 06DB 06DC 06DF 06E0 06E1 06E2 "
    "06E4 06E7 06E8 06EB 06EC 0730 0732 0733 0735 0736 073A 073D 073F 0740 0741 0743 0745 0747 0749 074A "
    "07EB 07EC 07ED 07EE 07EF 07F0 07F1 07F3 0816 0817 0818 0819 081B 081C 081D 081E 081F 0820 0821 0822 "
    "0823 0825 0826 0827 0829 082A 082B 082C 082D 0951 0953 0954 0F82 0F83 0F86 0F87 135D 135E 135F 17DD "
    "193A 1A17 1A75 1A76 1A77 1A78 1A79 1A7A 1A7B 1A7C 1B6B 1B6D 1B6E 1B6F 1B70 1B71 1B72 1B73 1CD0 1CD1 "
    "1CD2 1CDA 1CDB 1CE0 1DC0 1DC1 1DC3 1DC4 1DC5 1DC6 1DC7 1DC8 1DC9 1DCB 1DCC 1DD1 1DD2 1DD3 1DD4 1DD5 "
    "1DD6 1DD7 1DD8 1DD9 1DDA 1DDB 1DDC 1DDD 1DDE 1DDF 1DE0 1DE1 1DE2 1DE3 1DE4 1DE5 1DE6 1DFE 20D0 20D1 "
    "20D4 20D5 20D6 20D7 20DB 20DC 20E1 20E7 20E9 20F0 2CEF 2CF0 2CF1 2DE0 2DE1 2DE2 2DE3 2DE4 2DE5 2DE6 "
    "2DE7 2DE8 2DE9 2DEA 2DEB 2DEC 2DED 2DEE 2DEF 2DF0 2DF1 2DF2 2DF3 2DF4 2DF5 2DF6 2DF7 2DF8 2DF9 2DFA "
    "2DFB 2DFC 2DFD 2DFE 2DFF A66F A67C A67D A6F0 A6F1 A8E0 A8E1 A8E2 A8E3 A8E4 A8E5 A8E6 A8E7 A8E8 A8E9 "
    "A8EA A8EB A8EC A8ED A8EE A8EF A8F0 A8F1 AAB0 AAB2 AAB3 AAB7 AAB8 AABE AABF AAC1 FE20 FE21 FE22 FE23 "
    "FE24 FE25 FE26 10A0F 10A38 1D185 1D186 1D187 1D188 1D189 1D1AA 1D1AB 1D1AC 1D1AD 1D242 1D243 1D244"
)
DIAC = [int(h, 16) for h in DIAC_HEX.split()]
BANNER_FILES = ["quest-complete", "waiting", "report", "last-output"]
BANNER_ID, BANNER_MAX_COLS = 0x7A0300, 80
BANNER_RATIOS = (4, 5, 6, 7, 8)
BIG_PORTRAIT_ID = 0x7A0400
LABEL_ID = 0x7A0500
SELECT_BANNER_ID = 0x7A0600
LABEL_COLS = {"took": 8, "waited": 10, "asked": 9, "files": 9, "work": 8, "where": 9, "running": 11}  # one row tall
SPLIT_MIN_WIDTH, SPLIT_SIDE_COLS, SPLIT_GAP, SPLIT_PORTRAIT_COLS = 100, 30, 2, 24
SPLIT_BIG_PORTRAIT_COLS = 14
PORTRAIT_PX = (192, 216)
ART_MIN_WIDTH = 30


def load_art():
    """art/ -> {image id: (PNG path, cols, rows)}; banners have only (PNG path,), or None if any of the 56 images is missing or unreadable. The files are opened, not read: send_image reads one when it sends it."""
    art = {}
    for base, prefix, names, cells in (
        (PORTRAIT_ID, "portrait", PORTRAIT_FILES, PORTRAIT_CELLS),
        (CREST_ID, "crest", CREST_FILES, CREST_CELLS),
        (BIG_PORTRAIT_ID, "portrait-big", PORTRAIT_FILES, ()),
        (BANNER_ID, "banner", BANNER_FILES, ()),
        (LABEL_ID, "label", list(LABEL_COLS), ()),
        *((BANNER_ID + 4 * (k - 4), "banner", [f"{n}-{k}x1" for n in BANNER_FILES], ()) for k in BANNER_RATIOS[1:]),
        (SELECT_BANNER_ID, "banner", ["select"] + [f"select-{k}x1" for k in BANNER_RATIOS[1:]], ()),
    ):
        for k, name in enumerate(names):
            path = os.path.join(ART_DIR, f"{prefix}-{name}.png")
            try:
                with open(path, "rb"):
                    pass
            except OSError:
                return None
            art[base + k] = (path, *cells)
    return art


ART_TERMS = ("ghostty", "kitty")


def art_supported(option, termname):
    """Use images? @party_art on/off wins; else the outer terminal (client_termname, carried over SSH) must be Ghostty or Kitty. Others lack Unicode placeholders and would show garbage."""
    if option in ("on", "off"):
        return option == "on"
    return any(t in termname for t in ART_TERMS)


def portrait_id(a):
    return PORTRAIT_ID + a["cls"]


def big_portrait_id(a):
    return BIG_PORTRAIT_ID + a["cls"]


def banner_id(status, has_report, has_summons, k=4):
    if status == "waiting":
        name = "waiting"
    elif not has_report:
        name = "last-output"
    elif has_summons:
        name = "report"
    else:
        name = "quest-complete" if status == "done" else "report"
    return BANNER_ID + 4 * (k - 4) + BANNER_FILES.index(name)


def select_banner_id(k=4):
    return SELECT_BANNER_ID + k - 4


def label_id(name):
    return LABEL_ID + list(LABEL_COLS).index(name)


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


def send_image(art, img_id, cols, rows):
    """kitty_image of the file art holds for img_id, read now and not kept. A file that cannot be read is logged and sends nothing."""
    try:
        with open(art[img_id][0], "rb") as f:
            data = f.read()
    except OSError:
        log_error()
        return ""
    return kitty_image(img_id, data, cols, rows)


def kitty_delete(img_id):
    """Delete an image and its placements (d=I) so a resend with other c/r is not shown at the old size; Ghostty may keep the old virtual placement for an id it already has."""
    seq = f"\x1b_Ga=d,d=I,i={img_id},q=2\x1b\\"
    if os.environ.get("TMUX"):
        seq = "\x1bPtmux;" + seq.replace("\x1b", "\x1b\x1b") + "\x1b\\"
    return seq


def image_row(img_id, row, cols):
    """Placeholder cells for one row of an image: foreground = image id, U+10EEEE + row + column."""
    r, g, b = img_id >> 16 & 255, img_id >> 8 & 255, img_id & 255
    cells = "".join(chr(0x10EEEE) + chr(DIAC[row]) + chr(DIAC[c]) for c in range(cols))
    return f"\033[38;2;{r};{g};{b}m{cells}{RESET}"
