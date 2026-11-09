"""Render the image version of the sidebar and the quest report page to SVG (for README screenshots), from a fixture file.
Parses ANSI colors, underline colors, wide characters and Kitty Unicode placeholders.

  python3 scripts/screenshot.py scripts/screenshot.json docs/img

writes window.svg (the sidebar beside a pane), card.svg (one card with a legend), report.svg and report-working.svg
(the split report page of a finished and of a working member) and help.svg (the report page with the key help on top).
Text is <text> with one x per character, lines and blocks are <rect>, Kitty images and Nerd Font icons are embedded
PNGs (data URIs only), so GitHub shows the files without the fonts.
Needs Pillow and a Nerd Font for the icons: set PARTY_FONT to a TTF path containing {} for the style
(default: Maple Mono NF CN at /usr/share/fonts/MapleMonoNL-NF-CN/MapleMonoNL-NF-CN-{}.ttf).
Characters that font lacks (⏎) come from PARTY_FALLBACK_FONT (default: JetBrainsMono Nerd Font Mono)."""

import base64
import io
import json
import os
import re
import sys
import unicodedata
from typing import Any
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont

S = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(S, ".."))
from party_hud.art import DIAC, load_art
from party_hud.collect import collect
from party_hud.render import help_screen, is_final, render, report_parts, report_view, side_labels
from party_hud.ui import banner_cells, portrait_cells, report_image_plan

loaded = load_art()
assert loaded, "art/ is incomplete"
art = loaded

CW, CH = 16, 36
SS = 2  # icon PNGs are drawn at twice the cell size
FONT = os.environ.get("PARTY_FONT", "/usr/share/fonts/MapleMonoNL-NF-CN/MapleMonoNL-NF-CN-{}.ttf")
FALLBACK = os.environ.get("PARTY_FALLBACK_FONT", "/usr/share/fonts/TTF/JetBrainsMonoNerdFontMono-{}.ttf")


def fonts(path, size):
    return ImageFont.truetype(path.format("Regular"), size), ImageFont.truetype(path.format("Bold"), size)


reg, bold = fonts(FONT, 26)
big_reg, big_bold = fonts(FONT, 26 * SS)
big_fb_reg, big_fb_bold = fonts(FALLBACK, 26 * SS)
ASC = reg.getmetrics()[0]
FAMILY = "'Maple Mono NF CN','JetBrains Mono','DejaVu Sans Mono',Menlo,Consolas,monospace"
MISSING = {"⏎"}  # not in the default font
FG = (232, 220, 192)
BG = (20, 26, 46)
DIAC_INDEX = {d: i for i, d in enumerate(DIAC)}
ESC = re.compile(r"\x1b\[[0-9;:]*m")

MX, MY, DD = CW // 2, CH // 2, 3
LIGHT = {"─": "LR", "│": "UD", "╭": "RD", "╮": "LD", "╰": "RU", "╯": "LU", "┼": "LRUD"}
HEAVY = {"━": "LR", "┃": "UD", "┏": "RD", "┓": "LD", "┗": "RU", "┛": "LU"}


def hl(y, x0, x1):
    return (x0, y - 1, x1, y + 1)


def vl(x, y0, y1):
    return (x - 1, y0, x + 1, y1)


DOUBLE = {
    "═": [hl(MY - DD, 0, CW), hl(MY + DD, 0, CW)],
    "║": [vl(MX - DD, 0, CH), vl(MX + DD, 0, CH)],
    "╔": [hl(MY - DD, MX - DD - 1, CW), vl(MX - DD, MY - DD - 1, CH), hl(MY + DD, MX + DD - 1, CW), vl(MX + DD, MY + DD - 1, CH)],
    "╗": [hl(MY - DD, 0, MX + DD + 1), vl(MX + DD, MY - DD - 1, CH), hl(MY + DD, 0, MX - DD + 1), vl(MX - DD, MY + DD - 1, CH)],
    "╚": [hl(MY + DD, MX - DD - 1, CW), vl(MX - DD, 0, MY + DD + 1), hl(MY - DD, MX + DD - 1, CW), vl(MX + DD, 0, MY - DD + 1)],
    "╝": [hl(MY + DD, 0, MX + DD + 1), vl(MX + DD, 0, MY + DD + 1), hl(MY - DD, 0, MX - DD + 1), vl(MX - DD, 0, MY - DD + 1)],
}  # fmt: skip


def line_rects(ch):
    """Rects (x0, y0, x1, y1) inside one cell that draw a box-drawing character; light 2 px, heavy 4 px, double 2 px twice."""
    if ch in DOUBLE:
        return DOUBLE[ch]
    arms = LIGHT.get(ch) or HEAVY[ch]
    h = 2 if ch in HEAVY else 1
    out = []
    if "L" in arms and "R" in arms:
        out.append((0, MY - h, CW, MY + h))
    elif "L" in arms:
        out.append((0, MY - h, MX + h, MY + h))
    elif "R" in arms:
        out.append((MX - h, MY - h, CW, MY + h))
    if "U" in arms and "D" in arms:
        out.append((MX - h, 0, MX + h, CH))
    elif "U" in arms:
        out.append((MX - h, 0, MX + h, MY + h))
    elif "D" in arms:
        out.append((MX - h, MY - h, MX + h, CH))
    return out


def hx(c):
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"


def icon_glyph(ch):
    """Private-use code points, where Nerd Font icons live."""
    o = ord(ch)
    return 0xE000 <= o <= 0xF8FF or 0xF0000 <= o <= 0xFFFFD


def png_uri(im):
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


class Canvas:
    """An SVG page of w x h pixels; paint() adds ANSI text at a cell, the other methods add shapes in pixels."""

    def __init__(self, w, h, sizes=None):
        self.w, self.h = w, h
        self.sizes: dict[int, tuple[int, int]] = dict(sizes or {})  # image id -> (cols, rows) it is shown at
        self.defs: dict[str, str] = {}
        self.body: list[str] = []

    def rect(self, x0, y0, x1, y1, color, opacity=None):
        extra = f' fill-opacity="{opacity}"' if opacity is not None else ""
        self.body.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="{hx(color)}"{extra}/>')

    def image(self, img_id):
        name = f"i{img_id:x}"
        if name not in self.defs:
            cols, rows = self.sizes[img_id] if img_id in self.sizes else art[img_id][1:]
            self.defs[name] = (
                f'<image id="{name}" width="{cols * CW}" height="{rows * CH}" preserveAspectRatio="none"'
                f' href="{png_uri(Image.open(io.BytesIO(art[img_id][0])))}"/>'
            )
        return name

    def glyph(self, ch, fgc, b, w):
        """PNG of one character, a cell (or two) in size, for characters the viewer's fonts will not have."""
        name = f"g{ord(ch):x}{fgc[0]:02x}{fgc[1]:02x}{fgc[2]:02x}{'b' if b else 'r'}"
        if name not in self.defs:
            if ch in MISSING:
                font = big_fb_bold if b else big_fb_reg
            else:
                font = big_bold if b else big_reg
            cw, chh = w * CW * SS, CH * SS
            cell = Image.new("RGBA", (cw, chh), (0, 0, 0, 0))
            left, _, right, _ = (int(v) for v in font.getbbox(ch))
            if icon_glyph(ch) and right > cw:
                # like Ghostty: a Nerd Font icon followed by text is squeezed into one cell
                g = Image.new("RGBA", (right, chh), (0, 0, 0, 0))
                ImageDraw.Draw(g).text((0, 4 * SS), ch, font=font, fill=fgc)
                g = g.crop((left, 0, right, chh))
                g = g.resize((cw, round(chh * cw / (right - left))), Image.Resampling.LANCZOS)
                cell.paste(g, (0, (chh - g.height) // 2), g)
            else:
                ImageDraw.Draw(cell).text((0, 4 * SS), ch, font=font, fill=fgc)
            self.defs[name] = f'<image id="{name}" width="{w * CW}" height="{CH}" href="{png_uri(cell)}"/>'
        return name

    def paint(self, text, x0, y0):
        """Draw multi-line ANSI text starting at cell (x0, y0)."""
        rects: list[list[Any]] = []
        tail: dict[tuple[int, int, tuple[int, ...]], list[Any]] = {}
        runs: list[list[int]] = []  # [image id, row, first column, count, x, y]
        icons: list[tuple[str, int, int]] = []
        texts: list[str] = []

        def add(ax0, ay0, ax1, ay1, color):
            r = tail.get((ay0, ay1, color))
            if r and r[2] == ax0:
                r[2] = ax1
                return
            r = [ax0, ay0, ax1, ay1, color]
            rects.append(r)
            tail[ay0, ay1, color] = r

        for y, line in enumerate(text.split("\n")):
            fgc, bgc, b, x, i = FG, None, False, x0, 0
            ul, ulc = False, None  # underline (SGR 4) and underline color (SGR 58)
            last_x = x0 * CW
            cells: list[tuple[int, str, int, tuple[int, ...], bool]] = []  # x, character, width in px, color, bold
            while i < len(line):
                mt = ESC.match(line, i)
                if mt:
                    p = [int(n) for n in re.split("[;:]", mt.group(0)[2:-1]) if n] or [0]
                    j = 0
                    while j < len(p):
                        if p[j] == 0:
                            fgc, bgc, b, ul, ulc = FG, None, False, False, None
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
                    i = mt.end()
                    continue
                ch = line[i]
                i += 1
                px, py = x * CW, (y0 + y) * CH
                if ch == "\U0010eeee":
                    r, c = DIAC_INDEX[ord(line[i])], DIAC_INDEX[ord(line[i + 1])]
                    i += 2
                    if bgc:
                        add(px, py, px + CW, py + CH, bgc)
                    img = fgc[0] << 16 | fgc[1] << 8 | fgc[2]
                    run = runs[-1] if runs else None
                    if (
                        run
                        and run[:2] == [img, r]
                        and run[5] == py
                        and run[4] + run[3] * CW == px
                        and run[2] + run[3] == c
                    ):
                        run[3] += 1
                    else:
                        runs.append([img, r, c, 1, px, py])
                    x += 1
                    continue
                if unicodedata.combining(ch):
                    cells.append((last_x, ch, 0, fgc, b))
                    continue
                w = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
                if ul:
                    add(px, py + CH - 3, px + w * CW, py + CH, ulc or fgc)
                if bgc:
                    add(px, py, px + w * CW, py + CH, bgc)
                if ch == "▅":  # drawn by hand so line height does not matter
                    add(px, py + CH * 3 // 8, px + CW, py + CH, fgc)
                elif "─" <= ch <= "╿":
                    for rx0, ry0, rx1, ry1 in line_rects(ch):
                        add(px + rx0, py + ry0, px + rx1, py + ry1, fgc)
                elif ch != " " and (icon_glyph(ch) or ch in MISSING):
                    icons.append((self.glyph(ch, fgc, b, w), px, py))
                else:
                    cells.append((px, ch, w * CW, fgc, b))
                    last_x = px
                x += w
            texts += self.text_runs(cells, (y0 + y) * CH + 4 + ASC)
        out = [
            f'<rect x="{r[0]}" y="{r[1]}" width="{r[2] - r[0]}" height="{r[3] - r[1]}" fill="{hx(r[4])}"/>'
            for r in rects
        ]
        for img, r, c, n, px, py in runs:
            out.append(
                f'<svg x="{px}" y="{py}" width="{n * CW}" height="{CH}" viewBox="{c * CW} {r * CH} {n * CW} {CH}">'
                f'<use href="#{self.image(img)}"/></svg>'
            )
        out += [f'<use href="#{name}" x="{px}" y="{py}"/>' for name, px, py in icons]
        self.body += out + texts

    @staticmethod
    def text_runs(cells, baseline):
        """<text> elements for one line: neighbouring cells of one color and weight share an element (spaces inside it too, so viewers that ignore the x list still keep the grid), each character has its own x."""
        runs: list[list[Any]] = []
        for cx, ch, w, fgc, b in cells:
            run = runs[-1] if runs else None
            if run and run[0] == (fgc, b) and (w == 0 or cx == run[2]):
                run[1].append((cx, ch))
                run[2] = max(run[2], cx + w)
            else:
                runs.append([(fgc, b), [(cx, ch)], cx + w])
        out = []
        for (fgc, b), chars, _ in runs:
            while chars and chars[-1][1] == " ":
                chars.pop()
            while chars and chars[0][1] == " ":
                chars.pop(0)
            if not chars:
                continue
            xs = " ".join(str(cx) for cx, _ in chars)
            weight = ' font-weight="700"' if b else ""
            out.append(
                f'<text x="{xs}" y="{baseline}" fill="{hx(fgc)}"{weight}>{escape("".join(c for _, c in chars))}</text>'
            )
        return out

    def nest(self, other, x, y, w, h, view):
        """Put another canvas in as a clipped, scaled window onto its pixels view = (x, y, w, h)."""
        self.defs.update(other.defs)
        vx, vy, vw, vh = view
        self.body.append(
            f'<svg x="{x}" y="{y}" width="{w}" height="{h}" viewBox="{vx} {vy} {vw} {vh}">{"".join(other.body)}</svg>'
        )

    def svg(self):
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}"'
            f' xml:space="preserve" font-family="{FAMILY}" font-size="26">\n'
            f"<defs>{''.join(self.defs.values())}</defs>\n"
            f'<rect width="{self.w}" height="{self.h}" fill="{hx(BG)}"/>\n' + "\n".join(self.body) + "\n</svg>\n"
        )


def shot(fixture, sel=None, height=34, main=None, status=None, focus="party", squad=None):
    """The sidebar, optionally with a pane of text on its right and a tmux status line below."""
    towns = collect(fixture)["towns"]
    frame = render(towns, 33, sel, None, "sidebar", height, None, focus, squad, 3, True)
    cols = 34 + (1 + 62 if main else 0)
    cv = Canvas(cols * CW, (height + (1 if status else 0)) * CH)
    cv.paint(frame, 0, 0)
    if main:
        cv.rect(34 * CW + CW // 2 - 1, 0, 34 * CW + CW // 2 + 1, height * CH, (58, 66, 102))
        cv.paint(main, 35, 0)
    if status:
        cv.rect(0, height * CH, cols * CW, (height + 1) * CH, (36, 44, 74))
        cv.paint(status, 0, height)
    return cv


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
    crop_w, crop_h = int(33 * CW * k), int((r1 - r0) * CH * k)
    mx, my, gap, rows = 24, 24, 28, (len(MARKS) + 1) // 2
    font = ImageFont.truetype(FONT.format("Regular"), 22)
    col_w = 36 + max(int(font.getlength(label)) for label, _ in MARKS) + 40
    width = max(crop_w + 16, 2 * col_w) + 2 * mx
    cv = Canvas(width, my + crop_h + gap + rows * 40 + my)
    ox = (width - crop_w) // 2
    cv.nest(full, ox, my, crop_w, crop_h, (0, r0 * CH, 33 * CW, (r1 - r0) * CH))
    gold, ink = (240, 180, 90), (232, 220, 192)
    base = font.getmetrics()[0]

    def badge(x, y, n):
        cv.body.append(
            f'<circle cx="{x:g}" cy="{y:g}" r="13" fill="{hx(gold)}" stroke="{hx(BG)}" stroke-width="2"/>'
            f'<text x="{x:g}" y="{y + 6:g}" font-size="18" font-weight="700" text-anchor="middle" fill="{hx(BG)}">{n}</text>'
        )

    for i, (label, (c, r)) in enumerate(MARKS, 1):
        badge(ox + c * CW * k, my + (r + 0.5) * CH * k, i)
        lx = mx + ((i - 1) // rows) * col_w
        ly = my + crop_h + gap + ((i - 1) % rows) * 40
        badge(lx + 13, ly + 13, i)
        cv.body.append(
            f'<text x="{lx + 36}" y="{ly + 1 + base}" font-size="22" fill="{hx(ink)}">{escape(label)}</text>'
        )
    return cv


RATIO = CW / CH
REPORT_COLS, REPORT_ROWS = 110, 36


def report_page(fixture, data, entry, helping=False):
    """The split report page the way run_report draws it (fixed left frame, scrolled to the top), from a fixture entry."""
    towns = collect(fixture)["towns"]
    squad, a = next((t["name"], m) for t in towns for m in t["agents"] if m["pane"] == entry["pane"])
    a = {**a, **entry.get("agent", {})}
    report, now = entry["report"], data["now"]
    banner, big = banner_cells(REPORT_COLS, RATIO), portrait_cells(RATIO)
    left, right = report_parts(
        a,
        squad,
        report,
        [],
        REPORT_COLS,
        entry.get("pos", 1),
        entry.get("total", 1),
        True,
        banner,
        big,
        REPORT_ROWS,
        now,
        True,
    )
    rows, _ = report_view(left, right, REPORT_ROWS, 0)
    plan = report_image_plan(a, is_final(report), art, REPORT_COLS, banner, big, side_labels(report, now))
    cv = Canvas(REPORT_COLS * CW, REPORT_ROWS * CH, {img: (c, r) for img, c, r in plan})
    cv.paint("\n".join(rows), 0, 0)
    if helping:
        keys = help_screen("report", REPORT_COLS, REPORT_ROWS)[:-1]
        plain = [ESC.sub("", row) for row in keys]
        top = next(i for i, row in enumerate(plain) if row.strip())
        bottom = max(i for i, row in enumerate(plain) if row.strip())
        c0 = min(len(row) - len(row.lstrip()) for row in plain if row.strip())
        c1 = max(len(row.rstrip()) for row in plain)
        cv.rect(0, 0, cv.w, cv.h, BG, 0.6)
        cv.rect(c0 * CW, top * CH, c1 * CW, (bottom + 1) * CH, BG)
        cv.paint("\n".join(keys), 0, 0)
    return cv


if __name__ == "__main__":
    fixture, outdir = sys.argv[1], sys.argv[2]
    with open(fixture) as f:
        data = json.load(f)
    pages = {
        "window.svg": shot(fixture, "%1", height=27, main=MAIN, status=STATUS),
        "card.svg": card(fixture, "%2"),
        "report.svg": report_page(fixture, data, data["reports"]["done"]),
        "report-working.svg": report_page(fixture, data, data["reports"]["working"]),
        "help.svg": report_page(fixture, data, data["reports"]["done"], True),
    }
    for name, cv in pages.items():
        path = os.path.join(outdir, name)
        with open(path, "w") as f:
            f.write(cv.svg())
        print(path, os.path.getsize(path))
