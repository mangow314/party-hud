"""Turn the black-on-white silhouettes in raw/crest-<name>.png into squad crests.

The shield, colors and drop shadow are drawn here; only the silhouette comes from the model.
Output: art/crest-<name>.png, 128x144 RGBA, transparent outside the shield.
"""

import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
OUT = os.path.join(HERE, "..", "..", "art")
W, H, SS = 128, 144, 4  # draw at 4x, then downscale for smooth edges
GOLD, SILVER = (226, 186, 96), (214, 220, 232)
PALETTE = {  # name: (shield field color, silhouette color)
    "lion": ((120, 24, 34), GOLD),
    "eagle": ((28, 54, 120), SILVER),
    "wolf": ((22, 78, 88), SILVER),
    "dragon": ((28, 86, 48), GOLD),
    "stag": ((96, 58, 26), GOLD),
    "phoenix": ((156, 58, 18), GOLD),
    "sun": ((78, 34, 98), GOLD),
    "moon": ((40, 34, 98), SILVER),
}


def shield(w, h, inset):
    """Shield outline: flat top, straight sides, lower half curving into a point."""
    x0, x1, y0 = inset, w - inset, inset
    mid, tip = h * 0.52, h - inset
    pts = [(x0, y0), (x1, y0), (x1, mid)]
    for k in range(1, 21):
        t = k / 20
        pts.append((x1 + (w / 2 - x1) * t**1.6, mid + (tip - mid) * t))
    for k in range(19, -1, -1):
        t = k / 20
        pts.append((x0 + (w / 2 - x0) * t**1.6, mid + (tip - mid) * t))
    return pts


def silhouette(path):
    """White background + black shape -> mask of the shape (mode L), cropped to its bounding box."""
    g = Image.open(path).convert("L")
    mask = g.point([255 if v < 110 else 0 for v in range(256)]).filter(ImageFilter.MedianFilter(5))
    box = mask.getbbox()
    if not box:
        sys.exit(f"{path}: no silhouette found")
    return mask.crop(box)


def compose(name):
    field, charge = PALETTE[name]
    w, h = W * SS, H * SS
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon(shield(w, h, 2 * SS), fill=(*GOLD, 255))  # gold rim
    d.polygon(shield(w, h, 7 * SS), fill=(20, 18, 24, 255))  # dark line inside the rim
    d.polygon(shield(w, h, 9 * SS), fill=(*field, 255))
    m = silhouette(os.path.join(RAW, f"crest-{name}.png"))
    bw, bh = w * 0.66, h * 0.56  # silhouette sits in the upper middle of the shield
    s = min(bw / m.width, bh / m.height)
    m = m.resize((max(1, int(m.width * s)), max(1, int(m.height * s))), Image.Resampling.LANCZOS)
    x, y = (w - m.width) // 2, int(h * 0.44 - m.height / 2)
    inner = Image.new("L", (w, h), 0)
    ImageDraw.Draw(inner).polygon(shield(w, h, 9 * SS), fill=255)
    full = Image.new("L", (w, h), 0)
    full.paste(m, (x, y))
    full = ImageChops.multiply(full, inner)  # clip anything outside the shield face
    shadow = ImageChops.multiply(ImageChops.offset(full, SS, 2 * SS).filter(ImageFilter.GaussianBlur(3 * SS)), inner)
    img.paste((0, 0, 0, 255), (0, 0), shadow.point([v * 160 // 255 for v in range(256)]))
    img.paste((*charge, 255), (0, 0), full)
    return img.resize((W, H), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name in PALETTE:
        compose(name).save(os.path.join(OUT, f"crest-{name}.png"), optimize=True)
        print(f"crest-{name}.png")
