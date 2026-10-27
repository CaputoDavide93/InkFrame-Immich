#!/usr/bin/env python3
"""Draw every diagram in this repository as SVG, one file per colour scheme.

  docs/assets/<name>-light.svg
  docs/assets/<name>-dark.svg

Mermaid was the wrong tool for these and took several attempts to prove it:
GitHub decodes HTML entities before parsing (which broke the architecture
diagram outright), ignores `%%{init}%%` (so edge labels cannot be styled), pins
its own version (so newer syntax is a trap), and picks the theme (so a diagram
tuned for dark renders as black cards on white). None of that is Mermaid's
fault; it is a text-to-diagram tool being asked to do art direction.

Drawn here there are no such limits and one new rule: **GitHub sanitises SVG in
markdown**, so no <style>, no <script>, no web font and no <foreignObject>.
Everything is a presentation attribute and the type is a system stack. Each
pair is served from one <picture>, which GitHub switches on
prefers-color-scheme.

Layout is explicit rather than solved. That is the point -- an auto-layout
engine is what we just left -- and these diagrams are small enough that placing
them by hand is cheaper than a layout engine nobody can predict.

House rules, from the documentation design system: a slate scale, a single
accent on the one thing that matters in each picture, drawn icons rather than
emoji (emoji-as-icon is an anti-pattern and a different picture on every
platform), monospace for anything that is literally typed, and text contrast at
or above 4.5:1 in both schemes.
"""
from __future__ import annotations

import pathlib
import sys
from xml.sax.saxutils import escape

ROOT = pathlib.Path(__file__).resolve().parents[1]
SANS = "system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace"

SCHEMES = {
    "light": dict(card="#ffffff", border="#d8dee4", title="#0f172a", sub="#5b6673",
                  accent="#2b59c3", on_accent="#ffffff", soft="#f1f4f9",
                  line="#94a3b8", rule="#e6e9ee", chip="#475569",
                  warn="#9a3412", warn_soft="#fff4ed", group="#f7f9fb"),
    "dark":  dict(card="#161b22", border="#30363d", title="#e6edf3", sub="#9aa4b0",
                  accent="#4c7ef3", on_accent="#ffffff", soft="#1b2230",
                  line="#6b7684", rule="#232a33", chip="#aeb7c2",
                  warn="#ffa657", warn_soft="#2a1d14", group="#11151b"),
}

# Stroked glyphs on a 24x24 grid, drawn rather than typed.
ICONS = {
    "library":  "M3 7h13v11H3z M6 4h13v11 M7 14l3-3 2.5 2.5L15 11l2 2.5",
    "chip":     "M8 8h8v8H8z M5 5h14v14H5z M10 2v3 M14 2v3 M10 19v3 M14 19v3 M2 10h3 M2 14h3 M19 10h3 M19 14h3",
    "frame":    "M3 5h18v12H3z M9 20h6 M12 17v3 M6 13l3.5-4 2.5 3 2-2.5L18 13",
    "house":    "M4 11 12 4l8 7 M6 10v9h12v-9 M10 19v-5h4v5",
    "moon":     "M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z",
    "bolt":     "M13 2 4 14h7l-1 8 9-12h-7z",
    "server":   "M4 4h16v6H4z M4 14h16v6H4z M7 7h.01 M7 17h.01 M11 7h6 M11 17h6",
    "database": "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6 M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
    "cloud":    "M7 18h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6.1 9.5 4.3 4.3 0 0 0 7 18z",
    "laptop":   "M5 5h14v10H5z M2 19h20 M9 19l1-2h4l1 2",
    "phone":    "M8 2h8a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z M11 18h2",
    "mail":     "M3 6h18v12H3z M3 7l9 6 9-6",
    "clock":    "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2",
    "shield":   "M12 3 4 6v6c0 4.5 3.4 8.3 8 9 4.6-.7 8-4.5 8-9V6z M9 12l2 2 4-4",
    "box":      "M12 3 3 7.5v9L12 21l9-4.5v-9z M3 7.5 12 12l9-4.5 M12 12v9",
    "user":     "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M4 21c0-4 3.6-6 8-6s8 2 8 6",
    "users":    "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z M2 20c0-3.5 3-5.5 7-5.5s7 2 7 5.5 M16 4.5a3.5 3.5 0 0 1 0 6.5 M18 14.8c2.4.6 4 2.3 4 5.2",
    "key":      "M14 10a4 4 0 1 0-3.2 3.9L13 16h2v2h2v2h3v-3l-5.1-5.1c.1-.3.1-.6.1-.9z M8 9h.01",
    "camera":   "M3 8h4l2-3h6l2 3h4v11H3z M12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
    "chart":    "M4 20V4 M4 20h16 M8 16v-5 M12 16V8 M16 16v-3",
    "api":      "M8 7 3 12l5 5 M16 7l5 5-5 5 M14 4l-4 16",
    "bell":     "M6 16V11a6 6 0 1 1 12 0v5l2 2H4z M10 21h4",
    "chat":     "M4 5h16v11H9l-5 4z",
    "gear":     "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M19.4 13a7.6 7.6 0 0 0 0-2l2-1.6-2-3.4-2.4 1a7.4 7.4 0 0 0-1.7-1L15 3.5h-4l-.4 2.5a7.4 7.4 0 0 0-1.7 1l-2.4-1-2 3.4 2 1.6a7.6 7.6 0 0 0 0 2l-2 1.6 2 3.4 2.4-1a7.4 7.4 0 0 0 1.7 1l.4 2.5h4l.4-2.5a7.4 7.4 0 0 0 1.7-1l2.4 1 2-3.4z",
    "code":     "M4 4h16v16H4z M9 9l-3 3 3 3 M15 9l3 3-3 3",
    "tv":       "M3 5h18v12H3z M8 21h8",
    "play":     "M6 4l14 8-14 8z",
    "file":     "M6 2h8l5 5v15H6z M14 2v5h5 M9 13h6 M9 17h6",
    "lock":     "M6 11h12v10H6z M8 11V7a4 4 0 0 1 8 0v4",
    "globe":    "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M3 12h18 M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9 M12 3c-2.5 2.7-3.8 5.7-3.8 9s1.3 6.3 3.8 9",
    "wifi":     "M2 9a15 15 0 0 1 20 0 M5.5 12.5a10 10 0 0 1 13 0 M9 16a5 5 0 0 1 6 0 M12 19.5h.01",
    "disk":     "M3 6h18v12H3z M7 14h.01 M11 14h6",
    "terminal": "M3 5h18v14H3z M7 10l3 2.5L7 15 M12.5 15h4.5",
    "calendar": "M4 6h16v15H4z M4 10h16 M8 3v5 M16 3v5 M8 14h2 M14 14h2 M8 17.5h2",
    "refresh":  "M20 12a8 8 0 1 1-2.3-5.7 M20 4v4.5h-4.5",
    "search":   "M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 1 0 0-13z M15.5 15.5 20 20",
    "filter":   "M4 5h16l-6 7.5V19l-4 1.5v-8z",
    "send":     "M21 3 3 10.5l7.5 3 3 7.5z M10.5 13.5 21 3",
    "alert":    "M12 3 22 20H2z M12 10v4 M12 17h.01",
    "archive":  "M3 4h18v4H3z M5 8v12h14V8 M10 12h4",
    "tag":      "M3 3h8l10 10-8 8L3 11z M7.5 7.5h.01",
    "user_plus":  "M10 11a4 4 0 1 0 0-8 4 4 0 1 0 0 8z M3 21c0-4 3-7 7-7s7 3 7 7 M19 8v6 M16 11h6",
    "user_x":     "M10 11a4 4 0 1 0 0-8 4 4 0 1 0 0 8z M3 21c0-4 3-7 7-7s7 3 7 7 M16.5 8.5l5 5 M21.5 8.5l-5 5",
    "user_check": "M10 11a4 4 0 1 0 0-8 4 4 0 1 0 0 8z M3 21c0-4 3-7 7-7s7 3 7 7 M16 11l2 2 4-4",
    "bucket":   "M4 6h16l-2 14H6z M4 6c0-1.5 3.6-2.5 8-2.5s8 1 8 2.5",
    "download": "M12 3v12 M7 10l5 5 5-5 M4 20h16",
    "wrench":   "M14.7 6.3a4 4 0 0 1 5-1.5l-2.6 2.6.5 2 2 .5 2.6-2.6a4 4 0 0 1-5.4 5.1L10 19.2",
    "bug":      "M9 7a3 3 0 0 1 6 0 M7 9h10v5a5 5 0 0 1-10 0z M12 9v10 M3 12h4 M17 12h4",
    "pulse":    "M3 12h4l2.5-6 5 12 2.5-6h4",
    "sliders":  "M4 6h9 M17 6h3 M4 12h3 M11 12h9 M4 18h11 M19 18h1 M15 4v4 M9 10v4 M17 16v4",
    "heart":    "M12 20s-7.5-4.6-7.5-10A4.5 4.5 0 0 1 12 7a4.5 4.5 0 0 1 7.5 3c0 5.4-7.5 10-7.5 10z",
    "sparkle":  "M11 3l1.9 5.6L18.5 10.5l-5.6 1.9L11 18l-1.9-5.6L3.5 10.5l5.6-1.9z",
    "rewind":   "M11 6 4 12l7 6z M20 6l-7 6 7 6z",
}


class Canvas:
    """Parts plus a size. No layout engine, on purpose."""

    def __init__(self, w: int, h: int, scheme: str, label: str) -> None:
        self.w, self.h, self.c, self.label = w, h, SCHEMES[scheme], label
        self.parts: list[str] = []

    def add(self, *svg: str) -> "Canvas":
        self.parts.extend(svg)
        return self

    # ── primitives ────────────────────────────────────────────────────────
    def icon(self, name, x, y, colour, size=21):
        s = size / 24
        return (f'<g transform="translate({x:.1f},{y:.1f}) scale({s:.4f})" fill="none" '
                f'stroke="{colour}" stroke-width="1.7" stroke-linecap="round" '
                f'stroke-linejoin="round"><path d="{ICONS[name]}"/></g>')

    def text(self, x, y, s, *, size=13, colour=None, font=None, weight=None,
             anchor="start", opacity=None):
        c = colour or self.c["sub"]
        extra = (f' font-weight="{weight}"' if weight else "") + \
                (f' opacity="{opacity}"' if opacity else "")
        return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{font or SANS}" '
                f'font-size="{size}" fill="{c}" text-anchor="{anchor}"{extra}>'
                f'{escape(s)}</text>')

    def box(self, x, y, w, h, title, subs=(), *, icon=None, tone="plain", rx=10):
        c = self.c
        fill, edge, tt = c["card"], c["border"], c["title"]
        st, op = c["sub"], ""
        if tone == "accent":
            fill = edge = c["accent"]; tt = st = c["on_accent"]; op = "0.85"
        elif tone == "soft":
            fill = c["soft"]
        elif tone == "warn":
            fill, edge, tt, st = c["warn_soft"], c["warn"], c["warn"], c["warn"]
        out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
               f'stroke="{edge}" stroke-width="1"/>']
        tx = x + 16
        ty = y + (28 if subs else h / 2 + 5)
        if icon:
            out.append(self.icon(icon, x + 16, y + (13 if subs else h / 2 - 10), tt))
            tx = x + 47
        out.append(self.text(tx, ty, title, size=15 if subs else 14,
                             colour=tt, weight="600"))
        for i, s in enumerate(subs):
            out.append(self.text(x + 16, y + 52 + i * 18, s, size=12.5,
                                 colour=st, opacity=op or None))
        return "".join(out)

    def diamond(self, cx, cy, w, h, lines):
        c = self.c
        pts = f"{cx},{cy - h/2} {cx + w/2},{cy} {cx},{cy + h/2} {cx - w/2},{cy}"
        out = [f'<polygon points="{pts}" fill="{c["soft"]}" stroke="{c["border"]}" '
               f'stroke-width="1"/>']
        n = len(lines)
        for i, s in enumerate(lines):
            out.append(self.text(cx, cy - (n - 1) * 7 + i * 14 + 4, s, size=12,
                                 colour=c["title"], anchor="middle"))
        return "".join(out)

    def pill(self, cx, cy, text, *, tone="plain", pad=16, size=13):
        c = self.c
        w = len(text) * size * 0.58 + pad * 2
        h = 32
        fill, edge, col = c["card"], c["border"], c["title"]
        if tone == "accent":
            fill = edge = c["accent"]; col = c["on_accent"]
        elif tone == "soft":
            fill = c["soft"]
        return (f'<rect x="{cx - w/2:.1f}" y="{cy - h/2}" width="{w:.1f}" height="{h}" '
                f'rx="{h/2}" fill="{fill}" stroke="{edge}" stroke-width="1"/>'
                + self.text(cx, cy + 4.5, text, size=size, colour=col, anchor="middle",
                            weight="500")), w

    def edge(self, pts, *, label=None, dash=False, both=False, label_at=0.5,
             label_dy=-9, label_anchor="middle", mono=True):
        c = self.c
        d = ' stroke-dasharray="5 4"' if dash else ""
        path = " ".join(f"{x},{y}" for x, y in pts)
        out = [f'<polyline points="{path}" fill="none" stroke="{c["line"]}" '
               f'stroke-width="1.5"{d} marker-end="url(#a)"'
               + (' marker-start="url(#b)"' if both else "") + "/>"]
        if label:
            (x1, y1), (x2, y2) = pts[0], pts[-1]
            lx = x1 + (x2 - x1) * label_at
            ly = y1 + (y2 - y1) * label_at
            out.append(self.text(lx, ly + label_dy, label, size=11.5,
                                 colour=c["chip"], font=MONO if mono else SANS,
                                 anchor=label_anchor))
        return "".join(out)

    def group(self, x, y, w, h, title):
        c = self.c
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" '
                f'fill="{c["group"]}" stroke="{c["border"]}" stroke-width="1" '
                f'stroke-dasharray="6 5"/>'
                + self.text(x + 18, y + 24, title, size=12, colour=c["sub"],
                            weight="600"))

    def footer(self, note):
        return (f'<line x1="24" y1="{self.h - 52}" x2="{self.w - 24}" y2="{self.h - 52}" '
                f'stroke="{self.c["rule"]}" stroke-width="1"/>'
                + self.text(24, self.h - 26, note, size=12.5, colour=self.c["sub"]))

    def render(self) -> str:
        c = self.c
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" '
            f'width="{self.w}" height="{self.h}" role="img" aria-label="{escape(self.label)}">'
            f'<defs>'
            f'<marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
            f'markerHeight="6" orient="auto-start-reverse">'
            f'<path d="M0 0 10 5 0 10z" fill="{c["line"]}"/></marker>'
            f'<marker id="b" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="6" '
            f'markerHeight="6" orient="auto">'
            f'<path d="M10 0 0 5 10 10z" fill="{c["line"]}"/></marker>'
            f'</defs>' + "".join(self.parts) + "</svg>"
        )


# ── the diagrams ──────────────────────────────────────────────────────────
# Cards and arrows only, like architecture(): one accent per picture, every
# edge label monospace because it is literally what crosses, and the one fact
# a reader must not miss under the rule. Every figure here is checked against
# the renderer's app.py and the firmware YAML; a timing or a count that the
# code does not back does not go in a picture.

def card(k, x, y, w, h, title, lines=(), *, icon=None, tone="plain"):
    """A box whose sub-lines may be monospace: `lines` holds strings, or
    (text, True) for something literally typed, such as an endpoint."""
    rows = [(r, False) if isinstance(r, str) else r for r in lines]
    svg = k.box(x, y, w, h, title, [t for t, _ in rows], icon=icon, tone=tone)
    c = k.c
    colour = {"accent": c["on_accent"], "warn": c["warn"]}.get(tone, c["sub"])
    for i, (t, mono) in enumerate(rows):
        if mono:
            plain = k.text(x + 16, y + 52 + i * 18, t, size=12.5, colour=colour,
                           opacity="0.85" if tone == "accent" else None)
            svg = svg.replace(plain, k.text(x + 16, y + 52 + i * 18, t, size=12,
                                            colour=colour, font=MONO))
    return svg


def architecture(scheme):
    k = Canvas(1180, 430, scheme,
               "Immich sends twenty scored candidates to the renderer, which sends one "
               "48 KB one-bit frame to the ePaper frame. Home Assistant exchanges control "
               "and status with the renderer. The panel never talks to Home Assistant.")
    W, H = 268, 108
    xs, top = [24, 456, 888], 56
    mid = top + H / 2
    ha_x, ha_y = 456, 244
    k.add(
        k.box(xs[0], top, W, H, "Immich", ["Your photo library", "on your own server"], icon="library"),
        k.box(xs[1], top, W, H, "Renderer", ["Scores 20 candidates,", "renders a calm one"], icon="chip", tone="accent"),
        k.box(xs[2], top, W, H, "ePaper Frame", ["800 x 480, one bit", "awake ~7s to check, ~35s to draw"], icon="frame"),
        k.box(ha_x, ha_y, W, H, "Home Assistant", ["Settings, previews, next photo"], icon="house"),
        k.edge([(xs[0] + W + 8, mid), (xs[1] - 8, mid)], label="20 scored candidates"),
        k.edge([(xs[1] + W + 8, mid), (xs[2] - 8, mid)], label="one 48 KB frame"),
        k.edge([(ha_x + W / 2, ha_y - 8), (xs[1] + W / 2, top + H + 8)], dash=True, both=True),
        k.text(ha_x + W / 2 + 14, (ha_y + top + H) / 2 + 4, "control and status",
               size=11.5, font=MONO, colour=k.c["chip"]),
        k.footer("The panel never talks to Home Assistant. Both talk to the renderer, "
                 "which is always awake."),
    )
    return k.render()


def wake_sequence(scheme):
    """One wake, end to end: the question, the renderer's one decision, and
    what the panel does with the answer. Cards, not lifelines."""
    k = Canvas(1180, 620, scheme,
               "The panel wakes on a clock slot and calls /wake. The renderer renders a "
               "new photo if a draw is due, serves a photo that is already waiting, or "
               "keeps the current one. It replies with generation, draw, sleep_seconds "
               "and ota_window_seconds. On a draw the panel fetches the 48 KB one-bit "
               "BMP, draws it, acknowledges it, holds the OTA window and sleeps; on a "
               "check it sleeps straight away.")
    c = k.c
    # Row one: the question and the decision.
    px, pw = 24, 220
    rx, rw = 340, 236
    bx, bw, bh = 636, 268, 84
    ix, iw = 1000, 156
    ys = [40, 138, 236]
    mid = ys[1] + bh / 2
    ph = 92
    k.add(
        card(k, px, mid - ph / 2, pw, ph, "Panel wakes", ["on the next clock slot"], icon="frame"),
        card(k, rx, mid - ph / 2, rw, ph, "Renderer decides", ["draw, or only a check"],
             icon="chip", tone="accent"),
        k.edge([(px + pw + 8, mid), (rx - 8, mid)], label="GET /wake"),
        card(k, bx, ys[0], bw, bh, "Draw due, nothing waiting",
             ["random pick from Immich,", "score 20, render a calm one"]),
        card(k, bx, ys[1], bw, bh, "A photo is waiting",
             ["asked for, or held for the draw:", "serve it, render nothing new"]),
        card(k, bx, ys[2], bw, bh, "Nothing due",
             ["keep it, do not rotate", ("draw: false", True)], tone="soft"),
        card(k, ix, ys[0], iw, bh, "Immich", ["your library"], icon="library"),
        k.edge([(bx + bw + 8, ys[0] + bh / 2), (ix - 8, ys[0] + bh / 2)]),
    )
    for y in ys:
        k.add(k.edge([(rx + rw + 8, mid), (bx - 8, y + bh / 2)]))

    # Row two: the reply, and the panel doing exactly what it says.
    ry, rh = 396, 100
    cols = [(24, 196), (310, 236), (636, 268), (1000, 156)]
    (ax, aw), (fx, fw), (dx, dw), (sx, sw) = cols
    k.add(
        card(k, ax, ry, aw, rh, "The reply",
             [("generation, draw,", True), ("sleep_seconds,", True),
              ("ota_window_seconds", True)]),
        card(k, fx, ry, fw, rh, "Fetch the frame",
             [("GET /frame.bmp?gen=N", True), "48 KB, one bit a pixel"]),
        card(k, dx, ry, dw, rh, "Draw, then acknowledge",
             [("POST /frame/ack?gen=N", True), "only after a clean refresh"]),
        card(k, sx, ry, sw, rh, "Deep sleep", ["to the next slot,", ("sleep_seconds", True)], icon="moon"),
        # The reply is the only dashed arrow: it comes back down the page.
        k.edge([(rx + rw / 2, mid + ph / 2 + 8), (rx + rw / 2, 354),
                (ax + aw / 2, 354), (ax + aw / 2, ry - 8)], dash=True),
        k.text(rx + rw / 2 + 12, 318, "reply", size=11.5, font=MONO, colour=c["chip"]),
        k.edge([(ax + aw + 8, ry + rh / 2), (fx - 8, ry + rh / 2)], label="draw: true"),
        k.edge([(fx + fw + 8, ry + rh / 2), (dx - 8, ry + rh / 2)]),
        k.edge([(dx + dw + 8, ry + rh / 2), (sx - 8, ry + rh / 2)], label="OTA window"),
    )
    # The common case goes under the draw path, straight to sleep.
    under = ry + rh + 34
    k.add(
        k.edge([(ax + aw / 2, ry + rh + 8), (ax + aw / 2, under), (sx + sw / 2, under),
                (sx + sw / 2, ry + rh + 8)]),
        k.text((ax + sx + sw) / 2, under - 8, "draw: false, the common case",
               size=11.5, font=MONO, colour=c["chip"], anchor="middle"),
        k.footer("A dashed arrow is a reply. A check makes one request and is awake "
                 "about 7 s; a draw adds the fetch and the acknowledgement, about 35 s."),
    )
    return k.render()


def topology(scheme):
    """Who is awake. The one fact the rest of the architecture rests on."""
    k = Canvas(1180, 364, scheme,
               "Immich, the renderer and Home Assistant are always on; the panel sleeps "
               "between wakes and is awake about 7 seconds to check and 35 to draw.")
    W, H = 250, 92
    k.add(
        k.group(24, 40, 812, 260, "ALWAYS ON"),
        k.group(868, 40, 288, 260, "ASLEEP BETWEEN WAKES"),
        k.box(56, 80, W, H, "Immich", ["Photographs and faces"], icon="library"),
        k.box(56, 188, W, H, "Home Assistant", ["Settings and previews"], icon="house"),
        k.box(546, 134, W, H, "Renderer", ["Chooses and prepares"], icon="chip", tone="accent"),
        k.box(900, 134, 224, H, "Panel", ["Asks, draws if told, sleeps"], icon="moon"),
        k.edge([(306 + 8, 126), (546 - 8, 168)]),
        k.edge([(306 + 8, 234), (546 - 8, 192)]),
        k.edge([(900 - 8, 180), (546 + W + 8, 180)]),
        k.footer("Everything the panel needs is decided while it is asleep, so a wake is "
                 "one question and, when told to, one frame."),
    )
    return k.render()


def wake_states(scheme):
    """The panel's own state machine, as a loop rather than a list."""
    k = Canvas(1180, 316, scheme,
               "Boot, connect and call /wake. On a draw: fetch the frame, draw it, "
               "acknowledge it and hold the OTA window. On a check: go straight to deep "
               "sleep. Either way the timer fires at the next clock slot and it boots again.")
    c = k.c
    states = ["Boot", "Wi-Fi", "GET /wake", "GET /frame.bmp", "Draw",
              "POST /frame/ack", "OTA window", "Deep sleep"]
    y, gap = 112, 34
    widths = [k.pill(0, 0, s)[1] for s in states]
    x = (k.w - sum(widths) - gap * (len(states) - 1)) / 2
    centres = []
    for i, (s, w) in enumerate(zip(states, widths)):
        cx = x + w / 2
        k.add(k.pill(cx, y, s, tone="accent" if s == "OTA window" else "plain")[0])
        if i:
            pcx, pw = centres[-1]
            k.add(k.edge([(pcx + pw / 2 + 5, y), (cx - w / 2 - 5, y)]))
        centres.append((cx, w))
        x += w + gap
    (boot, _), (wake, _), (ota, _), (sleep, _) = (centres[0], centres[2],
                                                  centres[6], centres[7])
    # A check skips everything between the question and the sleep.
    top = y - 62
    k.add(k.edge([(wake, y - 20), (wake, top), (sleep, top), (sleep, y - 20)]),
          k.text((wake + sleep) / 2, top - 8, "draw: false, about 7 s awake",
                 size=11.5, font=MONO, colour=c["chip"], anchor="middle"))
    # Held awake hangs under the OTA window; the loop home runs beneath it.
    k.add(k.edge([(ota, y + 20), (ota, y + 54)]),
          k.pill(ota, y + 72, "Held awake", tone="soft")[0],
          k.text(ota - 12, y + 42, "Stay awake on", size=11.5, font=MONO,
                 colour=c["chip"], anchor="end"))
    home = y + 112
    k.add(k.edge([(sleep, y + 20), (sleep, home), (boot, home), (boot, y + 20)]),
          k.text((boot + ota) / 2, home - 8, "timer: sleep_seconds, to the next clock slot",
                 size=11.5, font=MONO, colour=c["chip"], anchor="middle"))
    k.add(k.footer("Only a drawing wake holds the OTA window. Set it to 60 s or more and "
                   "the renderer makes every wake a draw, so the panel can be flashed."))
    return k.render()


def firmware_flow(scheme):
    """What the firmware does, including both things that can go wrong."""
    k = Canvas(1180, 610, scheme,
               "Boot, connect to Wi-Fi and call /wake, storing the reply or keeping the "
               "fallbacks. If told to draw: fetch the frame with one retry, update the "
               "display, acknowledge it and hold the OTA window. Then sleep unless Stay "
               "awake is on.")
    c = k.c
    # Column one: the start, straight down.
    x1, w1, h1 = 24, 190, 60
    k.add(
        k.box(x1, 40, w1, h1, "Boot", icon="bolt"),
        k.box(x1, 130, w1, h1, "Wi-Fi connects", icon="wifi"),
        k.box(x1, 220, w1, h1, "GET /wake"),
        k.edge([(x1 + w1 / 2, 100 + 6), (x1 + w1 / 2, 130 - 6)]),
        k.edge([(x1 + w1 / 2, 190 + 6), (x1 + w1 / 2, 220 - 6)]),
    )
    # Column two: the reply, or its absence. Both reach the same question.
    x2, w2, h2 = 300, 262, 80
    k.add(
        card(k, x2, 150, w2, h2, "Store the reply",
             [("sleep_seconds, generation,", True), ("ota_window_seconds, draw", True)]),
        card(k, x2, 268, w2, h2, "Keep the fallbacks", ["sleep 1 h, nothing to draw"],
             tone="warn"),
        k.edge([(x1 + w1 + 8, 240), (x2 - 8, 196)], label="reply", label_dy=-10),
        k.edge([(x1 + w1 + 8, 262), (x2 - 8, 306)], label="no reply", label_dy=20),
    )
    # The decision, and the draw path down its middle.
    tx, ty = 704, 250
    k.add(
        k.diamond(tx, ty, 176, 88, ["Told to", "draw?"]),
        k.edge([(x2 + w2 + 8, 192), (tx - 50, ty - 30)]),
        k.edge([(x2 + w2 + 8, 306), (tx - 50, ty + 30)]),
        card(k, tx - 116, 352, 232, 80, "Fetch /frame.bmp",
             ["on error wait 10 s, retry once;", "a second error sleeps 1 h"]),
        k.edge([(tx, ty + 44 + 6), (tx, 352 - 8)], label="yes", label_at=0.5,
               label_dy=4, label_anchor="start"),
        k.box(tx - 116, 484, 232, 60, "Display update", tone="accent"),
        k.edge([(tx, 432 + 8), (tx, 484 - 8)]),
        k.text(tx + 10, 466, "ok", size=11.5, font=MONO, colour=c["chip"]),
    )
    # Column four: acknowledge, hold, then the one switch that stops a sleep.
    sx, sw = 940, 216
    scx = sx + sw / 2
    k.add(
        card(k, sx, 484, sw, 60, "POST /frame/ack"),
        k.edge([(tx + 116 + 8, 514), (sx - 8, 514)], label="no fault"),
        k.box(sx, 362, sw, 60, "Hold the OTA window"),
        k.edge([(scx, 484 - 8), (scx, 422 + 8)]),
        k.diamond(scx, ty, 176, 88, ["Stay awake", "switch on?"]),
        k.edge([(scx, 362 - 8), (scx, ty + 44 + 6)]),
        k.edge([(tx + 88 + 8, ty), (scx - 88 - 8, ty)], label="no"),
        k.box(sx - 150, 40, 170, 60, "Deep sleep", icon="moon"),
        k.box(sx + 60, 40, 156, 60, "Stay awake", tone="warn"),
        k.edge([(scx - 30, ty - 44 - 4), (sx - 65, 100 + 8)], label="no",
               label_dy=-4, label_anchor="end"),
        k.edge([(scx + 30, ty - 44 - 4), (sx + 138, 100 + 8)], label="yes",
               label_dy=-4, label_anchor="start"),
        k.footer("Every path ends in a sleep: a panel that cannot reach the renderer "
                 "keeps the photo it has and asks again in an hour."),
    )
    return k.render()


def portrait_crop(scheme):
    """How a portrait becomes a landscape frame."""
    k = Canvas(1180, 330, scheme,
               "A portrait is cropped to 800 by 480: the window is placed on the faces "
               "Immich found, or centred and biased above the middle when there are none.")
    W, H = 236, 76
    k.add(
        k.box(40, 104, W, H, "Portrait", ["1440 x 1920"], icon="library"),
        k.diamond(430, 142, 214, 94, ["Faces from", "/api/faces?"]),
        k.box(636, 44, 268, 86, "Window placed on them", ["a third down for a full body,", "centred for a close-up"]),
        k.box(636, 166, 268, H, "Window centred", ["biased above the middle"]),
        k.box(972, 104, 168, H, "800 x 480", tone="accent"),
        k.edge([(40 + W + 8, 142), (430 - 107 - 8, 142)]),
        k.edge([(430 + 107 + 8, 124), (636 - 8, 87)], label="yes", label_dy=-6),
        k.edge([(430 + 107 + 8, 160), (636 - 8, 204)], label="no", label_dy=16),
        k.edge([(636 + 268 + 8, 87), (972 - 8, 128)]),
        k.edge([(636 + 268 + 8, 204), (972 - 8, 156)]),
        k.footer("Without face.read on the API key Immich returns no boxes, the crop falls "
                 "back to centred, and nothing breaks."),
    )
    return k.render()


def selection_pipeline(scheme):
    """Two filters and a score, in the order that costs least."""
    k = Canvas(1180, 330, scheme,
               "Random assets come from Immich a hundred at a time, are filtered by "
               "orientation and then by whether a camera took them, then twenty are "
               "downloaded and scored for busyness, and a calm one is rendered.")
    W, H = 200, 80
    y = 52
    cy = y + H / 2
    k.add(
        k.box(24, y, W, H, "Immich random", ["100 a round, up to 4"], icon="library"),
        k.diamond(348, cy, 186, 88, ["Landscape, or", "portraits on?"]),
        k.diamond(628, cy, 186, 88, ["Camera make", "in EXIF?"]),
        k.box(786, y, 172, H, "Score 20", ["download, rate busyness"]),
        k.box(986, y, 170, H, "Render one", ["random under the cap,", "else the calmest"], tone="accent"),
        k.edge([(24 + W + 8, cy), (348 - 93 - 8, cy)]),
        k.edge([(348 + 93 + 8, cy), (628 - 93 - 8, cy)], label="yes"),
        k.edge([(628 + 93 + 8, cy), (786 - 8, cy)], label="yes"),
        k.edge([(786 + 172 + 8, cy), (986 - 8, cy)]),
        # Both drops go the same way, which is the point: cheap tests first.
        k.edge([(348, cy + 44 + 6), (348, y + 140 - 8)], label="no", label_at=0.5, label_dy=4, label_anchor="end"),
        k.edge([(628, cy + 44 + 6), (628, y + 140 - 8)], label="no", label_at=0.5, label_dy=4, label_anchor="end"),
        k.box(276, y + 140, 144, 48, "Dropped", tone="soft"),
        k.box(556, y + 140, 144, 48, "Dropped", tone="soft"),
        k.footer("Orientation and EXIF come from the search result, so both filters are "
                 "free. Only the twenty that survive are ever downloaded."),
    )
    return k.render()


DIAGRAMS = {
    "architecture": architecture,
    "wake-sequence": wake_sequence,
    "topology": topology,
    "wake-states": wake_states,
    "firmware-flow": firmware_flow,
    "portrait-crop": portrait_crop,
    "selection-pipeline": selection_pipeline,
}


def main() -> None:
    check = "--check" in sys.argv[1:]
    out = ROOT / "docs" / "assets"
    out.mkdir(parents=True, exist_ok=True)
    stale = []
    for name, fn in DIAGRAMS.items():
        for scheme in SCHEMES:
            path = out / f"{name}-{scheme}.svg"
            svg = fn(scheme)
            if check:
                if not path.exists() or path.read_text(encoding="utf-8") != svg:
                    stale.append(str(path.relative_to(ROOT)))
            else:
                path.write_text(svg, encoding="utf-8")
    if check:
        if stale:
            print("stale diagrams (run python3 tools/gen_diagram.py):\n  " + "\n  ".join(stale))
            sys.exit(1)
        print(f"{len(DIAGRAMS) * len(SCHEMES)} diagram files up to date")
        return
    print(f"{len(DIAGRAMS)} diagrams x {len(SCHEMES)} schemes -> docs/assets/")


if __name__ == "__main__":
    main()
