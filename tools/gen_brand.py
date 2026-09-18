#!/usr/bin/env python3
"""Draw the brand assets and the README demo, so they are reproducible.

  brand/icon.png       256x256   home-assistant/brands and HACS
  brand/icon@2x.png    512x512
  brand/logo.png       1024x256  wordmark
  brand/logo@2x.png    2048x512  hDPI wordmark, for home-assistant/brands
  docs/assets/demo.png           a synthetic scene beside its one-bit render

The demo is deliberately synthetic. The real frames this was built on are
family photographs, and a public repository is not the place for them; a
drawn scene pushed through the real `render()` still shows what the pipeline
does to tone, texture and edges.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "server" / "src"
if not SRC.exists():
    SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
from immich import PANEL_H, PANEL_W, render  # noqa: E402

INK = (26, 26, 26)
PAPER = (244, 241, 234)
ACCENT = (232, 160, 76)     # the house orange


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def scene(w: int, h: int) -> Image.Image:
    """A scene chosen to be hard, not pretty.

    A one-bit panel fails in three distinct ways, so the demo has to contain
    all three or it flatters the pipeline: a wide smooth gradient (banding),
    fine high-frequency texture (the speckle that made Davide ask for this
    work in the first place), and hard edges against soft ones (haloing from
    the unsharp pass). Sky, foliage and the waterline cover them in that
    order.
    """
    import numpy as np

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    v, u = yy / h, xx / w

    # Sky: a long vertical ramp, the thing that bands worst.
    sky = np.stack([92 + 118 * v, 138 + 92 * v, 196 + 52 * v], axis=-1)

    # Sun with a wide soft halo -- a smooth radial on top of a linear ramp.
    sx, sy = w * 0.70, h * 0.24
    rad = np.hypot(xx - sx, yy - sy)
    halo = np.clip(1.0 - rad / (h * 0.42), 0, 1) ** 2.2
    disc = np.clip((h * 0.085 - rad) / 2.0, 0, 1)
    sky += halo[..., None] * np.array([52, 40, 8], np.float32)
    sky = sky * (1 - disc[..., None]) + disc[..., None] * np.array([255, 246, 222], np.float32)

    img = sky

    # Water, with a horizon and a compressed reflection of the sky above it.
    horizon = h * 0.60
    water = img[: int(horizon)][::-1]
    water = np.asarray(Image.fromarray(water.clip(0, 255).astype(np.uint8))
                       .resize((w, h - int(horizon))), np.float32)
    water = water * 0.80 + np.array([22, 34, 46], np.float32)
    # Ripples: horizontal streaks, the edge case between smooth and textured.
    ripple = (np.sin(yy[int(horizon):] * 0.9) * np.cos(xx[int(horizon):] * 0.05) * 7.0)
    water += ripple[..., None]
    img = np.concatenate([img[: int(horizon)], water], axis=0)

    # Hills: flat-ish tones close together, which is where banding shows.
    for i, (base, shade) in enumerate([(0.585, 168), (0.545, 138), (0.505, 112)]):
        ridge = h * base - np.sin(u * math.pi * (1.4 + i * 0.9) + i) * h * 0.045
        mask = yy > ridge
        band = np.array([shade - 18, shade, shade - 30], np.float32)
        img = np.where(mask[..., None] & (yy < horizon)[..., None], band, img)

    # Foreground bank with real noise: the high-frequency case.
    rng = np.random.default_rng(7)
    bank = yy > h * 0.86 - np.sin(u * math.pi * 2.6) * h * 0.02
    grass = np.array([118, 140, 82], np.float32) + rng.normal(0, 16, (h, w, 1)).astype(np.float32)
    img = np.where(bank[..., None], grass, img)

    out = Image.fromarray(img.clip(0, 255).astype(np.uint8))

    # A tree: a hard silhouette with textured foliage inside it.
    d = ImageDraw.Draw(out)
    tx, ty = w * 0.20, h * 0.58
    for _ in range(11):
        ox, oy = rng.normal(0, w * 0.026), rng.normal(0, h * 0.042)
        rr = rng.uniform(h * 0.07, h * 0.115)
        g = 104 + int(rng.uniform(0, 46))
        d.ellipse([tx + ox - rr, ty + oy - rr * 0.82, tx + ox + rr, ty + oy + rr * 0.82],
                  fill=(g - 40, g, g - 56))
    # The trunk goes on last: drawn first, a canopy lobe landing on it read as
    # a brown smear rather than a tree.
    d.rectangle([tx - w * 0.005, ty + h * 0.06, tx + w * 0.005, h * 0.89], fill=(62, 48, 34))
    # Leaf speckle inside the canopy, so it is texture rather than a blob.
    can = np.asarray(out, np.float32)
    leaf = (np.hypot(xx - tx, (yy - ty) * 1.25) < h * 0.15) & (yy < h * 0.74)
    can = np.where(leaf[..., None], can + rng.normal(0, 19, (h, w, 1)), can)
    out = Image.fromarray(can.clip(0, 255).astype(np.uint8))

    return out.filter(ImageFilter.GaussianBlur(0.4))


def icon(size: int) -> Image.Image:
    """A frame on paper with a one-bit landscape inside."""
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = s * 0.18
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=PAPER)
    m = s * 0.14
    d.rounded_rectangle([m, m, s - m, s - m], radius=r * 0.35, fill=INK)
    inner = int(s * 0.03)
    box = [m + inner, m + inner, s - m - inner, s - m - inner]
    w = int(box[2] - box[0]); h = int(box[3] - box[1])
    # Real pipeline on the scene, then a square crop biased left so the tree
    # and the sun both stay in; a plain resize squashed the sun into an oval.
    frame = render(scene(PANEL_W, PANEL_H)).convert("L")
    left = int((PANEL_W - PANEL_H) * 0.35)
    frame = frame.crop((left, 0, left + PANEL_H, PANEL_H)).resize((w, h), Image.LANCZOS)
    img.paste(frame.convert("RGB"), (int(box[0]), int(box[1])))
    # The house orange: a small charge dot in the corner, the one bit of colour.
    dot = s * 0.045
    d.ellipse([s - m - dot * 2.2, s - m + dot * 0.4, s - m - dot * 0.2, s - m + dot * 2.4], fill=ACCENT)
    return img


def logo(scale: int = 1) -> Image.Image:
    w, h = 1024 * scale, 256 * scale
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ic = icon(h).resize((h, h), Image.LANCZOS)
    img.paste(ic, (0, 0), ic)
    d = ImageDraw.Draw(img)
    f1, f2 = _font(int(h * 0.42)), _font(int(h * 0.17))
    d.text((h + 40, h * 0.18), "InkFrame", fill=INK, font=f1)
    d.text((h + 44, h * 0.66), "one good photo a week, from Immich", fill=(90, 90, 90), font=f2)
    return img


def demo() -> Image.Image:
    """The before/after card for the README.

    Laid out rather than pasted: the first version put two bare panels flush
    against the image edge with the captions floating over them, which read as
    a screenshot of something unfinished. Margins, a rule under each caption
    and the numbers under the right-hand panel do the explaining the prose
    would otherwise have to.
    """
    before = scene(PANEL_W, PANEL_H)
    after = render(before).convert("RGB")

    pad, gap, cap_h, foot_h = 40, 34, 52, 40
    w = pad * 2 + PANEL_W * 2 + gap
    h = pad * 2 + cap_h + PANEL_H + foot_h
    out = Image.new("RGB", (w, h), PAPER)
    d = ImageDraw.Draw(out)

    label = _font(25)
    small = _font(20)
    muted = (122, 116, 106)
    rule = (214, 208, 197)

    for i, (img, title, foot) in enumerate((
        (before, "THE PHOTOGRAPH", "as Immich stores it"),
        (after, "THE FRAME", f"{PANEL_W} x {PANEL_H} · 1 bit · 48 KB"),
    )):
        x = pad + i * (PANEL_W + gap)
        y = pad + cap_h
        d.text((x, pad + 4), title, fill=INK, font=label)
        d.line([(x, pad + cap_h - 12), (x + PANEL_W, pad + cap_h - 12)], fill=rule, width=1)
        out.paste(img, (x, y))
        # A hairline keeps the light sky from bleeding into the page.
        d.rectangle([x, y, x + PANEL_W - 1, y + PANEL_H - 1], outline=rule, width=1)
        d.text((x, y + PANEL_H + 12), foot, fill=muted, font=small)

    # The arrow carries the direction the two panels only imply.
    ax, ay = pad + PANEL_W + gap // 2, pad + cap_h + PANEL_H // 2
    d.line([(ax - 9, ay), (ax + 7, ay)], fill=ACCENT, width=3)
    d.polygon([(ax + 12, ay), (ax + 2, ay - 6), (ax + 2, ay + 6)], fill=ACCENT)
    return out


def main() -> None:
    (ROOT / "brand").mkdir(exist_ok=True)
    (ROOT / "docs" / "assets").mkdir(parents=True, exist_ok=True)
    icon(256).save(ROOT / "brand" / "icon.png")
    icon(512).save(ROOT / "brand" / "icon@2x.png")
    logo().save(ROOT / "brand" / "logo.png")
    # home-assistant/brands wants the shortest side between 256 and 512 for the
    # hDPI logo, so 2048x512 rather than a doubling of an already-wide image.
    logo(2).save(ROOT / "brand" / "logo@2x.png")
    demo().save(ROOT / "docs" / "assets" / "demo.png", optimize=True)
    print("brand/icon.png brand/icon@2x.png brand/logo.png brand/logo@2x.png "
          "docs/assets/demo.png")


if __name__ == "__main__":
    main()
