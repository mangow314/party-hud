"""Turn the raw banner scenes into the four report-page banners.

The model draws only the scene (hill, camp, tavern map, scout ridge); the title is drawn here on the 320x80 pixel grid, then everything is
enlarged x3 with nearest neighbour. Output: art/banner-<slug>.png, 960x240 (4:1).
The flatter art/banner-<slug>-<k>x1.png (k = 5..8, 960 wide, 320/k grid rows tall) cut rows off the scene at a per-scene offset and centre the title.
Needs Noto Serif Bold (Arch: noto-fonts); used only here, never shipped.
"""

import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
OUT = os.path.join(HERE, "..", "..", "art")
FONT = "/usr/share/fonts/noto/NotoSerif-Bold.ttf"
W, H, COLORS, SCALE = 320, 80, 48, 3
X, BASELINE, SIZE = 12, 49, 22
INK = (28, 20, 34)
RAMP = [(255, 236, 170), (240, 200, 105), (214, 156, 64), (170, 110, 44)]
BANNERS = {
    "quest-complete": ("Quest Complete", "banner-hill"),
    "waiting": ("Waiting for You", "banner-camp"),
    "report": ("Report", "banner-map"),
    "last-output": ("Last Output", "banner-scout"),
}
CENTER = {"quest-complete": 40, "waiting": 58, "report": 44, "last-output": 26}


def background(name):
    img = Image.open(os.path.join(RAW, name + ".png")).convert("RGB")
    small = img.resize((W, H), Image.Resampling.BOX)
    return small.quantize(COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).convert("RGB")


def title(bg, text, baseline=BASELINE):
    """Gold 4-tone title, with a hard 1-pixel dark outline and a 1-pixel drop shadow."""
    font = ImageFont.truetype(FONT, SIZE)
    w, h = bg.size
    hard = lambda v: 255 if v > 110 else 0
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((X, baseline), text, font=font, fill=255, anchor="ls")
    mask = mask.point(hard)
    outline = Image.new("L", (w, h), 0)
    ImageDraw.Draw(outline).text((X, baseline), text, font=font, fill=255, anchor="ls", stroke_width=1, stroke_fill=255)
    outline = outline.point(hard)
    top = baseline - SIZE * 0.75
    gold = Image.new("RGB", (w, h))
    gd = ImageDraw.Draw(gold)
    for row in range(h):
        t = min(max((row - top) / max(baseline - top, 1), 0), 0.999)
        gd.line((0, row, w, row), fill=RAMP[int(t * len(RAMP))])
    out = bg.copy()
    ImageDraw.Draw(out).text(
        (X + 1, baseline + 1), text, font=font, fill=INK, anchor="ls", stroke_width=1, stroke_fill=INK
    )
    out.paste(INK, (0, 0, w, h), outline)
    out.paste(gold, (0, 0), mask)
    return out


def flat(slug, text, scene, k):
    """k:1 banner: the rows around CENTER[slug] of the scene, the title centred (outline and shadow included) in the new height."""
    rows = round(H * 4 / k)
    y0 = min(max(CENTER[slug] - rows // 2, 0), H - rows)
    font = ImageFont.truetype(FONT, SIZE)
    top, bottom = font.getbbox(text, anchor="ls")[1::2]
    baseline = round((rows - (top + bottom + 1)) / 2)
    return title(background(scene).crop((0, y0, W, y0 + rows)), text, baseline)


if __name__ == "__main__":
    for slug, (text, scene) in BANNERS.items():
        im = title(background(scene), text).resize((W * SCALE, H * SCALE), Image.Resampling.NEAREST)
        path = os.path.join(OUT, f"banner-{slug}.png")
        im.save(path, optimize=True)
        print(path, im.size, os.path.getsize(path), "bytes")
        for k in range(5, 9):
            im = flat(slug, text, scene, k).resize((W * SCALE, round(H * 4 / k) * SCALE), Image.Resampling.NEAREST)
            path = os.path.join(OUT, f"banner-{slug}-{k}x1.png")
            im.save(path, optimize=True)
            print(path, im.size, os.path.getsize(path), "bytes")
