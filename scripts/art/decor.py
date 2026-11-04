"""Turn raw/portrait-<class>.png into the framed portraits in art/ (192x216).

Steps: crop to 8:9, cut the character out of the plain dark background (flood fill from the edges),
paint a new background (radial glow, light rays, bokeh, four-point stars, one color per class),
add a soft halo behind the character and a silver frame.
"""

import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
OUT = os.path.join(HERE, "..", "..", "art")
OUT_W, OUT_H = 192, 216
DARK = (14, 16, 28)
# Silver frame: the selected card already uses a gold border, so a gold frame would blend in
SILVER_HI, SILVER, SILVER_LO = (236, 240, 248), (176, 184, 200), (92, 100, 120)
COLORS = {  # class: (background color, glow color)
    "swordsman": ((150, 40, 48), (255, 170, 120)),
    "merchant": ((150, 110, 30), (255, 226, 140)),
    "thief": ((80, 40, 130), (200, 150, 255)),
    "cleric": ((170, 140, 70), (255, 248, 210)),
    "scholar": ((40, 70, 150), (150, 200, 255)),
    "hunter": ((40, 110, 60), (190, 255, 170)),
    "apothecary": ((20, 110, 110), (150, 250, 230)),
    "dancer": ((160, 50, 110), (255, 170, 220)),
}


def crop89(im):
    w, h = im.size
    cw = h * 8 // 9
    x = (w - cw) // 2
    return im.crop((x, 0, x + cw, h))


def cutout(im):
    """Character mask (L, 255 = character). The background is a dark navy close to the corner color;
    flood fill it from the top, left and right edges (the bottom edge is the character's shoulders)."""
    a = np.asarray(im.convert("RGB")).astype(int)
    h, w, _ = a.shape
    corners = np.concatenate([a[:8, :8].reshape(-1, 3), a[:8, -8:].reshape(-1, 3)])
    bg = np.median(corners, axis=0)
    near = (np.abs(a - bg).max(axis=2) < 34).astype(np.uint8) * 255
    flood = Image.fromarray(
        near, "L"
    ).copy()  # copy: an image made from a numpy array is read-only and floodfill does nothing
    for x in range(0, w, 4):
        if flood.getpixel((x, 0)) == 255:
            ImageDraw.floodfill(flood, (x, 0), 128)
    for y in range(0, h, 4):
        for seed in ((0, y), (w - 1, y)):
            if flood.getpixel(seed) == 255:
                ImageDraw.floodfill(flood, seed, 128)
    mask = Image.fromarray(np.where(np.asarray(flood) == 128, 0, 255).astype(np.uint8), "L")
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))  # drop stray pixels
    return mask.filter(ImageFilter.GaussianBlur(1.2))  # feather the edge


def gacha_bg(size, base, glow, seed):
    """Dark base, a big glow above center, light rays, bokeh dots and four-point stars."""
    w, h = size
    rnd = random.Random(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = w * 0.5, h * 0.38
    d = np.sqrt(((xx - cx) / w) ** 2 + ((yy - cy) / h) ** 2)
    t = np.clip(1 - d / 0.75, 0, 1) ** 1.6
    dark = np.array(DARK, float)
    col = dark + (np.array(base, float) - dark) * np.clip(t * 1.4, 0, 1)[..., None]
    col += (np.array(glow, float) - col) * (t**3 * 0.75)[..., None]
    img = Image.fromarray(np.clip(col, 0, 255).astype(np.uint8), "RGB")
    rays = Image.new("L", size, 0)
    rd = ImageDraw.Draw(rays)
    n = 18
    for k in range(n):
        ang = 2 * math.pi * k / n + rnd.uniform(-0.05, 0.05)
        spread = 0.06 if k % 2 else 0.035
        r = max(w, h) * 1.2
        rd.polygon(
            [
                (cx, cy),
                (cx + r * math.cos(ang - spread), cy + r * math.sin(ang - spread)),
                (cx + r * math.cos(ang + spread), cy + r * math.sin(ang + spread)),
            ],
            fill=70 if k % 2 else 110,
        )
    rays = rays.filter(ImageFilter.GaussianBlur(w * 0.01))
    img = Image.composite(Image.new("RGB", size, glow), img, rays.point(lambda v: int(v * 0.55)))
    bokeh = Image.new("L", size, 0)
    bd = ImageDraw.Draw(bokeh)
    for _ in range(14):
        r = rnd.uniform(w * 0.015, w * 0.05)
        x, y = rnd.uniform(0, w), rnd.uniform(0, h * 0.85)
        bd.ellipse([x - r, y - r, x + r, y + r], fill=rnd.randint(40, 110))
    img = Image.composite(Image.new("RGB", size, glow), img, bokeh.filter(ImageFilter.GaussianBlur(w * 0.006)))
    stars = Image.new("L", size, 0)
    sd = ImageDraw.Draw(stars)
    for _ in range(9):
        x, y, r = rnd.uniform(w * 0.05, w * 0.95), rnd.uniform(h * 0.05, h * 0.7), rnd.uniform(w * 0.018, w * 0.04)
        q = r * 0.22
        sd.polygon(
            [
                (x, y - r),
                (x + q, y - q),
                (x + r, y),
                (x + q, y + q),
                (x, y + r),
                (x - q, y + q),
                (x - r, y),
                (x - q, y - q),
            ],
            fill=255,
        )
    return Image.composite(Image.new("RGB", size, (255, 255, 245)), img, stars.filter(ImageFilter.GaussianBlur(0.8)))


def frame(im):
    """Silver bevel frame (5 lines, brightest in the middle), a dark inner line and small corner diamonds."""
    d = ImageDraw.Draw(im)
    w, h = im.size
    ss = w // OUT_W
    for k, col in enumerate((SILVER_LO, SILVER, SILVER_HI, SILVER, SILVER_LO)):
        d.rectangle([k * ss, k * ss, w - 1 - k * ss, h - 1 - k * ss], outline=col, width=ss)
    d.rectangle([5 * ss, 5 * ss, w - 1 - 5 * ss, h - 1 - 5 * ss], outline=DARK, width=ss)
    r = 7 * ss
    for cx, cy in ((0, 0), (w, 0), (0, h), (w, h)):
        cx, cy = min(max(cx, r), w - r), min(max(cy, r), h - r)
        d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=SILVER_HI, outline=SILVER_LO)
    return im


def portrait(cls):
    base, glow = COLORS[cls]
    im = crop89(Image.open(os.path.join(RAW, f"portrait-{cls}.png")).convert("RGB"))
    big = im.resize((OUT_W * 4, OUT_H * 4), Image.Resampling.LANCZOS)
    mask = cutout(big)
    bg = gacha_bg(big.size, base, glow, seed=sum(map(ord, cls)))
    halo = mask.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(10))  # soft rim light
    bg = Image.composite(Image.new("RGB", big.size, glow), bg, halo.point(lambda v: int(v * 0.35)))
    out = frame(Image.composite(big, bg, mask))
    return out.resize((OUT_W, OUT_H), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for cls in COLORS:
        portrait(cls).quantize(256).save(os.path.join(OUT, f"portrait-{cls}.png"), optimize=True)
        print(f"portrait-{cls}.png")
