#!/usr/bin/env python3
"""Draw the architecture diagram as SVG, one file per colour scheme.

  docs/assets/architecture-light.svg
  docs/assets/architecture-dark.svg

Mermaid was the wrong tool for the front page and took three attempts to prove
it: GitHub decodes entities before parsing (which broke it outright), ignores
`%%{init}%%` (so edge labels could not be styled), pins its own version (so
newer syntax is a trap), and picks the theme (so a diagram tuned for dark
renders as black cards on white). None of that is Mermaid's fault; it is a
text-to-diagram tool being asked to do art direction.

An SVG drawn here has none of those limits and one new rule: **GitHub
sanitises SVG in markdown**, so there is no <style> block, no <script> and no
web font. Everything is a presentation attribute and the type is a system
stack. The two files are served from one <picture> element, which GitHub
switches on prefers-color-scheme.

Design follows the house rules for technical documentation: a slate scale, a
single accent for the one box that matters, drawn icons rather than emoji
(emoji-as-icon is an anti-pattern and renders differently on every platform),
and text contrast at or above 4.5:1 in both schemes.
"""
from __future__ import annotations

import pathlib
from xml.sax.saxutils import escape

ROOT = pathlib.Path(__file__).resolve().parents[1]
SANS = "system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace"

SCHEMES = {
    "light": dict(card="#ffffff", border="#d8dee4", title="#0f172a", sub="#5b6673",
                  accent="#2b59c3", on_accent="#ffffff", accent_soft="#eef2ff",
                  line="#94a3b8", rule="#e6e9ee", chip="#475569"),
    "dark":  dict(card="#161b22", border="#30363d", title="#e6edf3", sub="#9aa4b0",
                  accent="#4c7ef3", on_accent="#ffffff", accent_soft="#1b2536",
                  line="#6b7684", rule="#232a33", chip="#aeb7c2"),
}

W, H = 1180, 430
CARD_W, CARD_H, R = 268, 108, 10

# Simple stroked glyphs on a 24x24 grid. Drawn rather than typed: an emoji is
# a different picture on every platform and a blank box on some.
ICONS = {
    "library": "M3 7h13v11H3z M6 4h13v11 M7 14l3-3 2.5 2.5L15 11l2 2.5",
    "chip":    "M8 8h8v8H8z M5 5h14v14H5z M10 2v3 M14 2v3 M10 19v3 M14 19v3 M2 10h3 M2 14h3 M19 10h3 M19 14h3",
    "frame":   "M3 5h18v12H3z M9 20h6 M12 17v3 M6 13l3.5-4 2.5 3 2-2.5L18 13",
    "house":   "M4 11 12 4l8 7 M6 10v9h12v-9 M10 19v-5h4v5",
}


def _icon(name: str, x: float, y: float, colour: str, size: float = 21) -> str:
    s = size / 24
    return (f'<g transform="translate({x:.1f},{y:.1f}) scale({s:.4f})" fill="none" '
            f'stroke="{colour}" stroke-width="1.7" stroke-linecap="round" '
            f'stroke-linejoin="round"><path d="{ICONS[name]}"/></g>')


def _card(x, y, icon, title, lines, c, *, accent=False) -> str:
    fill = c["accent"] if accent else c["card"]
    edge = c["accent"] if accent else c["border"]
    tt = c["on_accent"] if accent else c["title"]
    st = c["on_accent"] if accent else c["sub"]
    op = ' opacity="0.82"' if accent else ""
    out = [f'<rect x="{x}" y="{y}" width="{CARD_W}" height="{CARD_H}" rx="{R}" '
           f'fill="{fill}" stroke="{edge}" stroke-width="1"/>',
           _icon(icon, x + 20, y + 21, tt),
           f'<text x="{x + 51}" y="{y + 37}" font-family="{SANS}" font-size="16" '
           f'font-weight="600" fill="{tt}">{escape(title)}</text>']
    for i, line in enumerate(lines):
        out.append(f'<text x="{x + 20}" y="{y + 64 + i * 19}" font-family="{SANS}" '
                   f'font-size="13" fill="{st}"{op}>{escape(line)}</text>')
    return "".join(out)


def _arrow(x1, y1, x2, y2, c, label=None, *, dash=False, both=False) -> str:
    d = ' stroke-dasharray="5 4"' if dash else ""
    out = [f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{c["line"]}" '
           f'stroke-width="1.5"{d} marker-end="url(#a)"'
           + (' marker-start="url(#b)"' if both else "") + "/>"]
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        out.append(f'<text x="{mx}" y="{my - 11}" text-anchor="middle" '
                   f'font-family="{MONO}" font-size="11.5" fill="{c["chip"]}">'
                   f'{escape(label)}</text>')
    return "".join(out)


def diagram(scheme: str) -> str:
    c = SCHEMES[scheme]
    mid = 56 + CARD_H / 2                       # centre line of the top row
    xs = [24, 456, 888]                         # three columns
    ha_x, ha_y = 456, 244

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" '
        f'height="{H}" role="img" aria-label="Immich sends scored candidates to the '
        f'renderer, which sends one one-bit frame to the e-paper panel; Home Assistant '
        f'controls the renderer">',
        f'<defs>'
        f'<marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
        f'markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M0 0 10 5 0 10z" fill="{c["line"]}"/></marker>'
        f'<marker id="b" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="6" '
        f'markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M10 0 0 5 10 10z" fill="{c["line"]}"/></marker>'
        f'</defs>',

        _card(xs[0], 56, "library", "Immich", ["Your photo library", "on your own server"], c),
        _card(xs[1], 56, "chip", "Renderer", ["Scores 20 candidates,", "renders the calmest"], c, accent=True),
        _card(xs[2], 56, "frame", "ePaper Frame", ["800 x 480, one bit", "awake ~35s a week"], c),
        _card(ha_x, ha_y, "house", "Home Assistant", ["Settings, previews, next photo"], c),

        _arrow(xs[0] + CARD_W + 8, mid, xs[1] - 8, mid, c, "20 scored candidates"),
        _arrow(xs[1] + CARD_W + 8, mid, xs[2] - 8, mid, c, "one 48 KB frame"),
        # Dashed, because this link is the only one that is not the photograph.
        _arrow(ha_x + CARD_W / 2, ha_y - 8, xs[1] + CARD_W / 2, 56 + CARD_H + 8, c,
               dash=True, both=True),
        f'<text x="{ha_x + CARD_W / 2 + 14}" y="{(ha_y + 56 + CARD_H) / 2 + 4}" '
        f'font-family="{MONO}" font-size="11.5" fill="{c["chip"]}">control and status</text>',

        f'<line x1="24" y1="{H - 52}" x2="{W - 24}" y2="{H - 52}" stroke="{c["rule"]}" stroke-width="1"/>',
        f'<text x="24" y="{H - 26}" font-family="{SANS}" font-size="12.5" fill="{c["sub"]}">'
        f'The panel never talks to Home Assistant. Both talk to the renderer, which is the '
        f'only part awake all the time.</text>',
        "</svg>",
    ]
    return "".join(parts)


def main() -> None:
    out = ROOT / "docs" / "assets"
    out.mkdir(parents=True, exist_ok=True)
    for scheme in SCHEMES:
        path = out / f"architecture-{scheme}.svg"
        path.write_text(diagram(scheme), encoding="utf-8")
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
