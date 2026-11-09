"""Draw the report page's small-heading labels: art/label-<name>.png, one terminal row tall, no raw images needed.

Each label is a 5x7 hand-drawn pixel word with a dark outline and a soft glow in its own color, a pixel gem on the left
and a tab plate that fades out to the right. The pixel grid is 4 px per dot (2x the 10x22 px cell the sizes assume),
so a label N cells wide is N*20 x 44 px; the terminal scales it into its cells.
"""

import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "..", "art")
S = 2
CELL_W, CELL_H = 10 * S, 22 * S
DOT = 2 * S
CODE, AMBER, GOLD, GREEN, VIOLET = (140, 207, 224), (224, 122, 58), (226, 178, 74), (143, 191, 106), (183, 138, 208)
LABELS = {
    "took": ("TOOK", CODE),
    "waited": ("WAITED", AMBER),
    "asked": ("ASKED", GOLD),
    "files": ("FILES", GREEN),
    "work": ("WORK", GREEN),
    "where": ("WHERE", VIOLET),
    "running": ("RUNNING", CODE),
}
FONT = {
    "A": ".###.|#...#|#...#|#####|#...#|#...#|#...#",
    "D": "####.|#...#|#...#|#...#|#...#|#...#|####.",
    "E": "#####|#....|#....|####.|#....|#....|#####",
    "F": "#####|#....|#....|####.|#....|#....|#....",
    "G": ".####|#....|#....|#..##|#...#|#...#|.####",
    "H": "#...#|#...#|#...#|#####|#...#|#...#|#...#",
    "I": "###|.#.|.#.|.#.|.#.|.#.|###",
    "K": "#...#|#..#.|#.#..|##...|#.#..|#..#.|#...#",
    "L": "#....|#....|#....|#....|#....|#....|#####",
    "N": "#...#|##..#|#.#.#|#.#.#|#..##|#...#|#...#",
    "O": ".###.|#...#|#...#|#...#|#...#|#...#|.###.",
    "R": "####.|#...#|#...#|####.|#.#..|#..#.|#...#",
    "S": ".####|#....|#....|.###.|....#|....#|####.",
    "T": "#####|..#..|..#..|..#..|..#..|..#..|..#..",
    "U": "#...#|#...#|#...#|#...#|#...#|#...#|.###.",
    "W": "#...#|#...#|#...#|#.#.#|#.#.#|##.##|#...#",
}
GEM = ["...#...", "..###..", ".##o##.", "##ooo##", ".#ooo#.", "..#o#..", "...#..."]
INK = (12, 14, 24, 255)
TEXT_X = 22 * S


def shade(rgb, k):
    return tuple(int(v * k) for v in rgb)


def cells_wide(word):
    glyphs = [FONT[c].split("|") for c in word]
    text = sum(len(g[0]) + 1 for g in glyphs) - 1
    return -(-(TEXT_X // S + text * 2 + 6) // 10)


def label(word, color):
    glyphs = [FONT[c].split("|") for c in word]
    width, height = cells_wide(word) * CELL_W, CELL_H
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    plate = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pd = ImageDraw.Draw(plate)
    for x in range(width):
        a = 1 - x / width
        pd.line([(x, 2 * S), (x, 19 * S - 1)], fill=(*color, int(46 * a)))
        pd.line([(x, 20 * S), (x, 20 * S + S - 1)], fill=(*color, int(220 * a)))
    img.alpha_composite(plate)
    mask = Image.new("L", (width, height), 0)
    md = ImageDraw.Draw(mask)
    x = TEXT_X
    for g in glyphs:
        for r, row in enumerate(g):
            for c, ch in enumerate(row):
                if ch == "#":
                    md.rectangle(
                        [x + c * DOT, 4 * S + r * DOT, x + (c + 1) * DOT - 1, 4 * S + (r + 1) * DOT - 1], fill=255
                    )
        x += (len(g[0]) + 1) * DOT
    glow = mask.filter(ImageFilter.GaussianBlur(2 * S)).point([int(min(255, v * 2) * 0.75) for v in range(256)])
    img.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", (width, height), color).split(), glow)))
    img.paste(INK, (0, 0), mask.filter(ImageFilter.MaxFilter(2 * S + 1)))
    hi = tuple(min(255, int(v * 1.18 + 20)) for v in color)
    img.paste(hi, (0, 0), mask)
    gd = ImageDraw.Draw(img)
    for r, row in enumerate(GEM):
        for c, ch in enumerate(row):
            if ch == ".":
                continue
            px, py = 4 * S + c * DOT, 4 * S + r * DOT
            fill = shade(color, 0.55) if ch == "#" else (hi if r <= 2 else color)
            if ch == "#" and r < 3 and c <= 3:
                fill = (255, 248, 225)
            gd.rectangle([px, py, px + DOT - 1, py + DOT - 1], fill=fill)
    return img


def main():
    for slug, (word, color) in LABELS.items():
        label(word, color).save(os.path.join(OUT, f"label-{slug}.png"))


if __name__ == "__main__":
    main()
