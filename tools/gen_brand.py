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
    """Sky gradient, sun, hills, a lone tree: gradients and edges, the two
    things a one-bit panel has to be made to cope with."""
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / h
        r = int(40 + 180 * t); g = int(60 + 150 * t); b = int(110 + 120 * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    d = ImageDraw.Draw(img)
    d.ellipse([w * 0.62, h * 0.18, w * 0.62 + h * 0.28, h * 0.46], fill=(255, 236, 200))
    for i, (yy, shade) in enumerate([(0.62, 70), (0.70, 95), (0.80, 125)]):
        pts = [(x, h * yy + math.sin(x / w * math.pi * (2 + i)) * h * 0.05) for x in range(0, w + 40, 40)]
        d.polygon([(0, h)] + pts + [(w, h)], fill=(shade, shade + 20, shade - 10))
    tx, ty = w * 0.22, h * 0.66
    d.rectangle([tx - w * 0.006, ty, tx + w * 0.006, ty + h * 0.22], fill=(50, 40, 30))
    d.ellipse([tx - w * 0.07, ty - h * 0.20, tx + w * 0.07, ty + h * 0.04], fill=(40, 60, 40))
    return img.filter(ImageFilter.GaussianBlur(0.6))


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
    before = scene(PANEL_W, PANEL_H)
    after = render(before).convert("RGB")
    gap = 24
    out = Image.new("RGB", (PANEL_W * 2 + gap, PANEL_H + 56), PAPER)
    out.paste(before, (0, 56)); out.paste(after, (PANEL_W + gap, 56))
    d = ImageDraw.Draw(out); f = _font(26)
    d.text((0, 14), "what Immich has", fill=INK, font=f)
    d.text((PANEL_W + gap, 14), "what the panel gets: 800x480, one bit, dithered", fill=INK, font=f)
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
