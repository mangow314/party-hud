"""Render the image version of the sidebar to a PNG (for README screenshots), from a fixture file.
Parses ANSI colors, underline colors, wide characters and Kitty Unicode placeholders.

  python3 scripts/screenshot.py scripts/screenshot.json docs/img

writes window.png (the sidebar beside a pane) and card.png (one card with a legend).
Needs Pillow and a Nerd Font: set PARTY_FONT to a TTF path containing {} for the style
(default: Maple Mono NF CN at /usr/share/fonts/MapleMonoNL-NF-CN/MapleMonoNL-NF-CN-{}.ttf).
Characters that font lacks (⏎) come from PARTY_FALLBACK_FONT (default: JetBrainsMono Nerd Font Mono)."""

import os
import re
import sys
import unicodedata

from PIL import Image, ImageDraw, ImageFont

S = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(S, ".."))
from party_hud.art import DIAC, load_art
from party_hud.collect import collect
from party_hud.render import render

loaded = load_art()
assert loaded, "art/ is incomplete"
art = loaded

CW, CH = 16, 36
FONT = os.environ.get("PARTY_FONT", "/usr/share/fonts/MapleMonoNL-NF-CN/MapleMonoNL-NF-CN-{}.ttf")
reg, bold = ImageFont.truetype(FONT.format("Regular"), 26), ImageFont.truetype(FONT.format("Bold"), 26)
FALLBACK = os.environ.get("PARTY_FALLBACK_FONT", "/usr/share/fonts/TTF/JetBrainsMonoNerdFontMono-{}.ttf")
fb_reg, fb_bold = ImageFont.truetype(FALLBACK.format("Regular"), 26), ImageFont.truetype(FALLBACK.format("Bold"), 26)
MISSING = {"⏎"}  # not in the default font
BG = (20, 26, 46)
DIAC_INDEX = {d: i for i, d in enumerate(DIAC)}
tiles = {}


def tile(img_id, r, c, back=BG):
    if (img_id, back) not in tiles:
        import io

        data, cols, rows = art[img_id]
        im = Image.open(io.BytesIO(data)).convert("RGBA")
        flat = Image.new("RGBA", im.size, (*back, 255))
        flat.alpha_composite(im)  # transparent pixels show the terminal background
        tiles[img_id, back] = flat.convert("RGB").resize((cols * CW, rows * CH), Image.Resampling.LANCZOS)
    return tiles[img_id, back].crop((c * CW, r * CH, (c + 1) * CW, (r + 1) * CH))


def icon_glyph(ch):
    """Private-use code points, where Nerd Font icons live."""
    o = ord(ch)
    return 0xE000 <= o <= 0xF8FF or 0xF0000 <= o <= 0xFFFFD


def paint(draw, canvas, text, x0, y0):
    """Draw multi-line ANSI text starting at cell (x0, y0)."""
    for y, line in enumerate(text.split("\n")):
        fgc, bgc, b, x, i = (232, 220, 192), None, False, x0, 0
        ul, ulc = False, None  # underline (SGR 4) and underline color (SGR 58)
        while i < len(line):
            mt = re.match(r"\x1b\[([0-9;:]*)m", line[i:])
            if mt:
                p = [int(n) for n in re.split("[;:]", mt.group(1)) if n] or [0]
                j = 0
                while j < len(p):
                    if p[j] == 0:
                        fgc, bgc, b, ul, ulc = (232, 220, 192), None, False, False, None
                    elif p[j] == 1:
                        b = True
                    elif p[j] == 4:
                        ul = True
                    elif p[j] == 24:
                        ul = False
                    elif p[j] == 59:
                        ulc = None
                    elif p[j] in (38, 48, 58) and p[j + 1] == 2:
                        if p[j] == 38:
                            fgc = tuple(p[j + 2 : j + 5])
                        elif p[j] == 48:
                            bgc = tuple(p[j + 2 : j + 5])
                        else:
                            ulc = tuple(p[j + 2 : j + 5])
                        j += 4
                    j += 1
                i += mt.end()
                continue
            if ul and line[i] != "\U0010eeee":  # underline at the bottom edge of the cell
                uw = 2 if unicodedata.east_asian_width(line[i]) in "WF" else 1
                draw.rectangle(
                    [x * CW, (y0 + y) * CH + CH - 3, (x + uw) * CW - 1, (y0 + y) * CH + CH - 1], fill=ulc or fgc
                )
            ch = line[i]
            i += 1
            px, py = x * CW, (y0 + y) * CH
            if ch == "\U0010eeee":
                r, c = DIAC_INDEX[ord(line[i])], DIAC_INDEX[ord(line[i + 1])]
                i += 2
                canvas.paste(tile(fgc[0] << 16 | fgc[1] << 8 | fgc[2], r, c, bgc or BG), (px, py))
                x += 1
                continue
            w = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
            if bgc:
                draw.rectangle([px, py, px + w * CW - 1, py + CH - 1], fill=bgc)
            if ch in "▅":  # draw block characters by hand so line height does not matter
                draw.rectangle([px, py + CH * 3 // 8, px + CW - 1, py + CH - 1], fill=fgc)
            elif ch in "─│╭╮╰╯":
                mx, my = px + CW // 2, py + CH // 2
                if ch in "─╭╰":
                    draw.line([mx if ch != "─" else px, my, px + CW, my], fill=fgc, width=2)
                if ch in "─╮╯":
                    draw.line([px, my, mx if ch != "─" else px + CW, my], fill=fgc, width=2)
                if ch in "│╭╮":
                    draw.line([mx, my if ch != "│" else py, mx, py + CH], fill=fgc, width=2)
                if ch in "│╰╯":
                    draw.line([mx, py, mx, my if ch != "│" else py + CH], fill=fgc, width=2)
            elif ch != " " and icon_glyph(ch) and (bold if b else reg).getbbox(ch)[2] > CW:
                # like Ghostty: a Nerd Font icon followed by text is squeezed into one cell
                font = bold if b else reg
                l, _, r, _ = (int(v) for v in font.getbbox(ch))
                g = Image.new("RGBA", (r, CH), (0, 0, 0, 0))
                ImageDraw.Draw(g).text((0, 4), ch, font=font, fill=fgc)
                g = g.crop((l, 0, r, CH)).resize((CW, CH * CW // (r - l)), Image.Resampling.LANCZOS)
                canvas.paste(g, (px, py + (CH - g.height) // 2), g)
            elif ch != " ":
                font = (fb_bold if b else fb_reg) if ch in MISSING else (bold if b else reg)
                draw.text((px, py + 4), ch, font=font, fill=fgc)
            x += w


def shot(fixture, sel=None, height=34, main=None, status=None, focus="party", squad=None):
    """The sidebar, optionally with a pane of text on its right and a tmux status line below."""
    towns = collect(fixture)["towns"]
    frame = render(towns, 33, sel, None, "sidebar", height, None, focus, squad, 3, True)
    cols = 34 + (1 + 62 if main else 0)
    canvas = Image.new("RGB", (cols * CW, (height + (1 if status else 0)) * CH), BG)
    draw = ImageDraw.Draw(canvas)
    paint(draw, canvas, frame, 0, 0)
    if main:
        draw.line([34 * CW + CW // 2, 0, 34 * CW + CW // 2, height * CH], fill=(58, 66, 102), width=2)
        paint(draw, canvas, main, 35, 0)
    if status:
        draw.rectangle([0, height * CH, cols * CW, (height + 1) * CH], fill=(36, 44, 74))
        paint(draw, canvas, status, 0, height)
    return canvas


# A generic agent session for the pane next to the sidebar (no real tool's look)
DIM, TXT, OK, ACC = (
    "\x1b[38;2;120;128;160m",
    "\x1b[38;2;220;214;196m",
    "\x1b[38;2;130;200;120m",
    "\x1b[38;2;240;180;90m",
)
MAIN = "\n".join(
    [
        f"{DIM}~/work/webapp (auth-refactor)",
        "",
        f"{ACC}> {TXT}move the session middleware to the new token store",
        "",
        f"{DIM}  read   {TXT}src/auth/session.ts",
        f"{DIM}  read   {TXT}src/auth/token-store.ts",
        f"{DIM}  edit   {TXT}src/auth/session.ts        {OK}+42 {ACC}-17",
        f"{DIM}  edit   {TXT}src/auth/middleware.ts     {OK}+8 {ACC}-3",
        f"{DIM}  run    {TXT}npm test",
        f"         {OK}128 passed{DIM}, 0 failed",
        "",
        f"{DIM}  2 helpers are checking the other routes ...",
    ]
)
STATUS = f"\x1b[1m{ACC} webapp \x1b[0m{TXT} 1:auth-refactor* {DIM}2:api-tests  3:codex"

# Numbered marks on one member card: (label, badge center as (col, row) inside the card)
CARD_ROWS = (15, 20)  # the "auth-refactor" card in the fixture frame
MARKS = [
    ("agent: claude, codex, agy or grok", (10.2, 0)),
    ("portrait: one of 8 classes per member", (0.6, 2)),
    ("class icon and name (session or window)", (24.9, 1)),
    ("status: busy, idle, wait or done", (32.5, 1)),
    ("HP: context window left", (24.3, 2)),
    ("model", (32.5, 2)),
    ("SP: prompt cache minutes left", (24.3, 3)),
    ("subagents running", (32.5, 3)),
]


def card(fixture, sel):
    """One member card, enlarged, with numbered marks and a legend below."""
    full = shot(fixture, sel)
    r0, r1 = CARD_ROWS
    k = 1.5
    crop = full.crop((0, r0 * CH, 33 * CW, r1 * CH))
    crop = crop.resize((int(crop.width * k), int(crop.height * k)), Image.Resampling.LANCZOS)
    mx, my, gap, rows = 24, 24, 28, (len(MARKS) + 1) // 2
    font, num = ImageFont.truetype(FONT.format("Regular"), 22), ImageFont.truetype(FONT.format("Bold"), 18)
    col_w = 36 + max(int(font.getlength(label)) for label, _ in MARKS) + 40
    width = max(crop.width + 16, 2 * col_w) + 2 * mx
    canvas = Image.new("RGB", (width, my + crop.height + gap + rows * 40 + my), BG)
    canvas.paste(crop, ((width - crop.width) // 2, my))
    draw = ImageDraw.Draw(canvas)
    gold, ink = (240, 180, 90), (232, 220, 192)

    def badge(x, y, n):
        draw.ellipse([x - 13, y - 13, x + 13, y + 13], fill=gold, outline=BG, width=2)
        draw.text((x, y + 1), str(n), font=num, fill=BG, anchor="mm")

    for i, (label, (c, r)) in enumerate(MARKS, 1):
        badge((width - crop.width) // 2 + c * CW * k, my + (r + 0.5) * CH * k, i)
        lx = mx + ((i - 1) // rows) * col_w
        ly = my + crop.height + gap + ((i - 1) % rows) * 40
        badge(lx + 13, ly + 13, i)
        draw.text((lx + 36, ly + 1), label, font=font, fill=ink)
    return canvas


if __name__ == "__main__":
    fixture, outdir = sys.argv[1], sys.argv[2]
    images = {
        "window.png": shot(fixture, "%1", height=27, main=MAIN, status=STATUS),
        "card.png": card(fixture, "%2"),
    }
    for name, im in images.items():
        im.save(os.path.join(outdir, name))
        print(os.path.join(outdir, name))
