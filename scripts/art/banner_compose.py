"""Turn raw/banner-hill.png into the four report-page banners.

The model draws only the hilltop scene; the title is drawn here on the 320x80 pixel grid, then everything is
enlarged x3 with nearest neighbour. Output: art/banner-<slug>.png, 960x240.
Needs Noto Serif Display Bold (Arch: noto-fonts); used only here, never shipped.
"""

import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
OUT = os.path.join(HERE, "..", "..", "art")
FONT = "/usr/share/fonts/noto/NotoSerifDisplay-Bold.ttf"
W, H, COLORS, SCALE = 320, 80, 48, 3
X, BASELINE, SIZE = 12, 49, 22
INK = (28, 20, 34)
RAMP = [(255, 236, 170), (240, 200, 105), (214, 156, 64), (170, 110, 44)]
TITLES = {
    "quest-complete": "Quest Complete",
    "waiting": "Waiting for You",
    "report": "Report",
    "last-output": "Last Output",
}


def background():
    img = Image.open(os.path.join(RAW, "banner-hill.png")).convert("RGB")
    small = img.resize((W, H), Image.Resampling.BOX)
    return small.quantize(COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).convert("RGB")


def title(bg, text):
    """Gold 4-tone title with a hard 1-pixel dark outline and a 1-pixel drop shadow."""
    font = ImageFont.truetype(FONT, SIZE)
    hard = lambda v: 255 if v > 110 else 0
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).text((X, BASELINE), text, font=font, fill=255, anchor="ls")
    mask = mask.point(hard)
    outline = Image.new("L", (W, H), 0)
    ImageDraw.Draw(outline).text((X, BASELINE), text, font=font, fill=255, anchor="ls", stroke_width=1, stroke_fill=255)
    outline = outline.point(hard)
    top = BASELINE - SIZE * 0.75
    gold = Image.new("RGB", (W, H))
    gd = ImageDraw.Draw(gold)
    for row in range(H):
        t = min(max((row - top) / max(BASELINE - top, 1), 0), 0.999)
        gd.line((0, row, W, row), fill=RAMP[int(t * len(RAMP))])
    out = bg.copy()
    ImageDraw.Draw(out).text(
        (X + 1, BASELINE + 1), text, font=font, fill=INK, anchor="ls", stroke_width=1, stroke_fill=INK
    )
    out.paste(INK, (0, 0, W, H), outline)
    out.paste(gold, (0, 0), mask)
    return out


if __name__ == "__main__":
    bg = background()
    for slug, text in TITLES.items():
        im = title(bg, text).resize((W * SCALE, H * SCALE), Image.Resampling.NEAREST)
        path = os.path.join(OUT, f"banner-{slug}.png")
        im.save(path, optimize=True)
        print(path, im.size, os.path.getsize(path), "bytes")
