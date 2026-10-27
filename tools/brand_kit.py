#!/usr/bin/env python3
"""Brand kit, trimmed to this project: the 1280x640 social preview.

  python3 tools/brand_kit.py social --out docs/assets/social-preview.png

The preview carries InkFrame's own icon, brand/icon@2x.png from gen_brand.py,
already rounded and transparent at the corners, on a background in the hue of
that icon's orange dot. Needs headless Google Chrome (set CHROME= if it is
elsewhere) and Pillow.
Rendering is deterministic and PNG metadata is stripped.
"""
import argparse, colorsys, html, os, pathlib, subprocess, sys, tempfile
from PIL import Image

CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
INK = "#F8FAFC"
NAME = "InkFrame-Immich"
HUE = 32        # the orange dot on brand/icon.png, (232, 160, 76)
TAGLINE = "One good Immich photo every few days, on a frame that sleeps between"
CHIPS = ('7.5" e-paper', "Immich", "Home Assistant", "ESPHome")

# ---- colour -----------------------------------------------------------------
def _lum(rgb):
    f = lambda c: c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in rgb)
    return .2126 * r + .7152 * g + .0722 * b
def _hex(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h / 360, l, s)
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255)), (r, g, b)
def _contrast(rgb):  # against near-white ink
    return (_lum((.97, .98, .99)) + .05) / (_lum(rgb) + .05)
def palette(hue):
    """(top, bottom, mid) hex. Same saturation, lightness 54/40; yellows and greens are
    darkened just enough that the white glyph keeps 3.2:1 (top) and 4.5:1 (bottom)."""
    s, lt, lb = .68, .55, .41
    while _contrast(_hex(hue, s, lt)[1]) < 3.2 and lt > .30: lt -= .01
    while _contrast(_hex(hue, s, lb)[1]) < 4.5 and lb > .20: lb -= .01
    lb = min(lb, lt - .12)
    return _hex(hue, s, lt)[0], _hex(hue, s, lb)[0], _hex(hue, s, (lt + lb) / 2)[0]
def dark_bg(hue):
    return _hex(hue, .38, .10)[0], _hex(hue, .45, .06)[0]

# ---- rendering --------------------------------------------------------------
def render(html_doc, w, h, out, transparent=False):
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "p.html"
        p.write_text(html_doc)
        shot = pathlib.Path(td) / "s.png"
        cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-sandbox",
               "--force-device-scale-factor=1", f"--window-size={w},{h}",
               "--virtual-time-budget=3000", f"--screenshot={shot}", f"file://{p}"]
        if transparent: cmd.insert(2, "--default-background-color=00000000")
        subprocess.run(cmd, check=True, capture_output=True)
        im = Image.open(shot).convert("RGBA" if transparent else "RGB")
    # fresh image = no metadata chunks
    clean = Image.new(im.mode, im.size); clean.paste(im)
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    clean.save(out, optimize=True)
    return clean

def make_social(name, tagline, chips, icon_path, hue, out_png):
    """1280x640, icon left, name, tagline, chips, hue stripe."""
    top, bot, mid = palette(hue); d1, d2 = dark_bg(hue)
    chips = list(chips)[:4]
    chip_html = "".join(f'<span class="c{" f" if i == 0 else ""}">{html.escape(c)}</span>' for i, c in enumerate(chips))
    doc = f'''<!doctype html><meta charset=utf-8><style>
*{{box-sizing:border-box;margin:0}}
body{{width:1280px;height:640px;overflow:hidden;font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;color:{INK};
 background:radial-gradient(900px 600px at 18% 45%,{mid}33,transparent 70%),linear-gradient(135deg,{d1},{d2});position:relative}}
.icon{{position:absolute;left:98px;top:170px;width:300px;height:300px}}
.txt{{position:absolute;left:480px;top:0;width:740px;height:632px;display:flex;flex-direction:column;justify-content:center}}
h1{{font-weight:800;letter-spacing:-.025em;line-height:1.02;white-space:nowrap;font-size:96px;margin-bottom:26px}}
h1.wrap{{white-space:normal;font-size:68px;overflow-wrap:anywhere}}
p{{font-size:35px;line-height:1.28;font-weight:600;color:#E3E6EBd9;margin-bottom:38px;letter-spacing:-.005em}}
.chips{{display:flex;gap:12px;flex-wrap:wrap}}
.c{{font-weight:700;font-size:23px;padding:11px 22px;border-radius:99px;border:2px solid #ffffff33;color:#F1F3F6}}
.c.f{{background:linear-gradient(180deg,{top},{bot});border-color:transparent;color:#fff}}
.bar{{position:absolute;left:0;right:0;bottom:0;height:8px;background:linear-gradient(90deg,{top},{bot})}}
</style><img class=icon src="file://{pathlib.Path(icon_path).resolve()}">
<div class=txt><h1 id=n>{html.escape(name)}</h1><p>{html.escape(tagline)}</p><div class=chips>{chip_html}</div></div><div class=bar></div>
<script>const h=document.getElementById('n');let s=96;while(h.scrollWidth>740&&s>60){{s-=2;h.style.fontSize=s+'px'}}
if(h.scrollWidth>740){{h.className='wrap';h.innerHTML=h.textContent.replace(/-/g,'-<wbr>')}}</script>'''
    return render(doc, 1280, 640, out_png)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("social"); b.add_argument("--icon", default="brand/icon@2x.png")
    b.add_argument("--out", default="docs/assets/social-preview.png")
    n = ap.parse_args(argv)
    make_social(NAME, TAGLINE, CHIPS, n.icon, HUE, n.out)

if __name__ == "__main__":
    sys.exit(main())
