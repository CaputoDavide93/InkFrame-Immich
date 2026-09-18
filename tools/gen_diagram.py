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
    "library": "M3 7h13v11H3z M6 4h13v11 M7 14l3-3 2.5 2.5L15 11l2 2.5",
    "chip":    "M8 8h8v8H8z M5 5h14v14H5z M10 2v3 M14 2v3 M10 19v3 M14 19v3 M2 10h3 M2 14h3 M19 10h3 M19 14h3",
    "frame":   "M3 5h18v12H3z M9 20h6 M12 17v3 M6 13l3.5-4 2.5 3 2-2.5L18 13",
    "house":   "M4 11 12 4l8 7 M6 10v9h12v-9 M10 19v-5h4v5",
    "moon":    "M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z",
    "bolt":    "M13 2 4 14h7l-1 8 9-12h-7z",
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
            f'markerHeight="6" orient="auto-start-reverse">'
            f'<path d="M10 0 0 5 10 10z" fill="{c["line"]}"/></marker>'
            f'</defs>' + "".join(self.parts) + "</svg>"
        )


# ── the diagrams ──────────────────────────────────────────────────────────

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
        k.box(xs[1], top, W, H, "Renderer", ["Scores 20 candidates,", "renders the calmest"], icon="chip", tone="accent"),
        k.box(xs[2], top, W, H, "ePaper Frame", ["800 x 480, one bit", "awake ~35s a week"], icon="frame"),
        k.box(ha_x, ha_y, W, H, "Home Assistant", ["Settings, previews, next photo"], icon="house"),
        k.edge([(xs[0] + W + 8, mid), (xs[1] - 8, mid)], label="20 scored candidates"),
        k.edge([(xs[1] + W + 8, mid), (xs[2] - 8, mid)], label="one 48 KB frame"),
        k.edge([(ha_x + W / 2, ha_y - 8), (xs[1] + W / 2, top + H + 8)], dash=True, both=True),
        k.text(ha_x + W / 2 + 14, (ha_y + top + H) / 2 + 4, "control and status",
               size=11.5, font=MONO, colour=k.c["chip"]),
        k.footer("The panel never talks to Home Assistant. Both talk to the renderer, "
                 "which is the only part awake all the time."),
    )
    return k.render()


def wake_sequence(scheme):
    """The weekly wake, end to end. A sequence, so it gets lifelines."""
    k = Canvas(1180, 470, scheme,
               "The panel calls /wake; the renderer either rotates to a new photograph or "
               "serves the one already rendered, replies with the sleep parameters, serves "
               "the frame, and the panel draws it and sleeps.")
    c = k.c
    lanes = [("Panel", 150, "frame"), ("Renderer", 590, "chip"), ("Immich", 1030, "library")]
    top, bottom = 84, 404
    for name, x, icon in lanes:
        w = 176
        k.add(k.box(x - w / 2, 26, w, 44, name, icon=icon),
              f'<line x1="{x}" y1="{top - 14}" x2="{x}" y2="{bottom}" stroke="{c["border"]}" '
              f'stroke-width="1" stroke-dasharray="4 5"/>')
    P, R, I = 150, 590, 1030

    def msg(y, x1, x2, text, *, dash=False):
        return k.edge([(x1, y), (x2, y)], label=text, dash=dash)

    def self_msg(y, x, text):
        return (k.edge([(x, y), (x + 54, y), (x + 54, y + 26), (x + 6, y + 26)]) +
                k.text(x + 66, y + 4, text, size=11.5, font=MONO, colour=c["chip"]))

    # The alt block: the one decision in the protocol.
    k.add(f'<rect x="{R - 230}" y="100" width="{I - R + 300}" height="122" rx="8" fill="none" '
          f'stroke="{c["border"]}" stroke-width="1" stroke-dasharray="5 4"/>',
          k.text(R - 216, 118, "if the current frame was already collected", size=11.5,
                 colour=c["sub"], weight="600"))
    k.add(
        msg(88, P + 8, R - 8, "GET /wake"),
        msg(146, R + 8, I - 8, "random landscape photographs"),
        self_msg(178, R, "score 20 candidates, render the calmest"),
        k.text(R - 216, 244, "otherwise: keep it, do not rotate", size=11.5, colour=c["sub"]),
        msg(272, R - 8, P + 8, "generation, sleep_seconds, ota_window_seconds", dash=True),
        msg(314, P + 8, R - 8, "GET /frame.bmp"),
        msg(348, R - 8, P + 8, "48 KB one-bit BMP", dash=True),
        self_msg(380, P, "draw, wait the OTA window, deep sleep"),
        k.footer("A dashed arrow is a reply. The panel makes exactly two requests per wake."),
    )
    return k.render()


def topology(scheme):
    """Who is awake. The one fact the rest of the architecture rests on."""
    k = Canvas(1180, 350, scheme,
               "Immich, the renderer and Home Assistant are always on; the panel wakes "
               "about thirty-five seconds a week.")
    W, H = 250, 92
    k.add(
        k.group(24, 40, 812, 240, "ALWAYS ON"),
        k.group(868, 40, 288, 240, "AWAKE ~35s A WEEK"),
        k.box(56, 88, W, H, "Immich", ["Photographs and faces"], icon="library"),
        k.box(56, 196, W, H, "Home Assistant", ["Settings and previews"], icon="house"),
        k.box(546, 142, W, H, "Renderer", ["Chooses and prepares"], icon="chip", tone="accent"),
        k.box(900, 142, 224, H, "Panel", ["Draws, then sleeps"], icon="moon"),
        k.edge([(306, 134), (546, 176)]),
        k.edge([(306, 242), (546, 200)]),
        k.edge([(900 - 8, 188), (546 + W + 8, 188)]),
        k.footer("Everything the panel needs is decided while it is asleep, so its whole "
                 "waking life is one fetch and one draw."),
    )
    return k.render()


def wake_states(scheme):
    """The panel's own state machine, as a loop rather than a list."""
    k = Canvas(1180, 330, scheme,
               "Boot, connect, call /wake, fetch the frame, draw it, hold an OTA window, "
               "then deep sleep until the timer fires and it boots again.")
    c = k.c
    states = ["Boot", "Wi-Fi", "GET /wake", "GET /frame.bmp", "Draw", "OTA window", "Deep sleep"]
    y = 116
    x = 74
    centres = []
    for i, s in enumerate(states):
        tone = "accent" if s == "OTA window" else "plain"
        svg, w = k.pill(0, 0, s, tone=tone)
        cx = x + w / 2
        svg, _ = k.pill(cx, y, s, tone=tone)
        k.add(svg)
        centres.append((cx, w))
        if i:
            px, pw = centres[i - 1]
            k.add(k.edge([(px + pw / 2 + 6, y), (cx - w / 2 - 6, y)]))
        x += w + 46
    first_cx, first_w = centres[0]
    last_cx, last_w = centres[-1]
    # The loop home, drawn under everything so it reads as the cycle it is.
    k.add(k.edge([(last_cx, y + 20), (last_cx, y + 74), (first_cx, y + 74), (first_cx, y + 20)]),
          k.text((first_cx + last_cx) / 2, y + 92, "timer, 72 hours later",
                 size=11.5, font=MONO, colour=c["chip"], anchor="middle"))
    ota_cx, ota_w = centres[5]
    k.add(k.edge([(ota_cx, y - 20), (ota_cx, y - 58)]),
          k.pill(ota_cx, y - 76, "Held awake", tone="soft")[0],
          k.text(ota_cx + 14, y - 36, "Stay awake switch on", size=11.5, font=MONO,
                 colour=c["chip"]),
          k.footer("The OTA window is the only moment the panel can be reflashed. "
                   "Everything after it is decided by the renderer's reply."))
    return k.render()


def firmware_flow(scheme):
    """What the firmware does, including both things that can go wrong."""
    k = Canvas(1180, 624, scheme,
               "Boot, connect to Wi-Fi, call /wake and store the reply or keep the "
               "fallback values, fetch the frame with one retry, draw it, hold the OTA "
               "window, then sleep unless Stay awake is on.")
    c = k.c
    W, H = 232, 64
    col1, col2, col3 = 60, 474, 888
    k.add(
        k.box(col1, 48, W, H, "Boot", icon="bolt"),
        k.box(col1, 148, W, H, "Wi-Fi connects"),
        k.box(col1, 248, W, H, "GET /wake"),
        k.edge([(col1 + W / 2, 112), (col1 + W / 2, 140)]),
        k.edge([(col1 + W / 2, 212), (col1 + W / 2, 240)]),
        # The reply, and its absence. Both continue to the same fetch.
        k.box(col2, 176, W, H, "Store sleep_seconds,", ["ota_window_seconds"]),
        k.box(col2, 300, W, H, "Keep the fallback values", ["and log a warning"], tone="warn"),
        k.edge([(col1 + W + 8, 268), (col2 - 8, 212)], label="reply", label_dy=-8),
        k.edge([(col1 + W + 8, 288), (col2 - 8, 330)], label="unreachable", label_dy=17),
        k.box(col3, 232, W, H, "Fetch /frame.bmp", ["online_image"]),
        k.edge([(col2 + W + 8, 208), (col3 - 8, 254)]),
        k.edge([(col2 + W + 8, 330), (col3 - 8, 286)]),
        # One retry, then give up: the panel has no second decode buffer.
        k.edge([(col3 + W + 8, 264), (col3 + W + 48, 264), (col3 + W + 48, 190),
                (col3 + W / 2, 190), (col3 + W / 2, 224)]),
        k.text(col3 + W / 2 + 10, 176, "error: wait 10 s, retry once", size=11.5,
               font=MONO, colour=c["chip"]),
        k.box(col3, 372, W, H, "Display update", tone="accent"),
        k.edge([(col3 + W / 2, 304), (col3 + W / 2, 364)], label="ok", label_dy=-4),
        k.box(col2, 372, W, H, "Hold the OTA window"),
        k.edge([(col3 - 8, 404), (col2 + W + 8, 404)]),
        k.diamond(col1 + W / 2, 404, 214, 78, ["Stay awake", "switch on?"]),
        k.edge([(col2 - 8, 404), (col1 + W / 2 + 107 + 8, 404)]),
        k.box(col1 - 30, 486, 150, 56, "Stay awake", tone="warn"),
        k.box(col1 + 142, 486, 166, 56, "Deep sleep"),
        k.edge([(col1 + W / 2 - 46, 438), (col1 + 45, 478)], label="yes", label_dy=-2, label_anchor="end"),
        k.edge([(col1 + W / 2 + 46, 438), (col1 + 225, 478)], label="no", label_dy=-2, label_anchor="start"),
        k.footer("Both failure paths continue rather than stop: a panel that cannot reach "
                 "the renderer still draws whatever it already has, and sleeps."),
    )
    return k.render()


def portrait_crop(scheme):
    """How a portrait becomes a landscape frame."""
    k = Canvas(1180, 344, scheme,
               "A portrait is cropped to 800 by 480: the window is placed on the faces "
               "Immich found, or centred and biased above the middle when there are none.")
    W, H = 236, 76
    k.add(
        k.box(40, 112, W, H, "Portrait", ["1440 x 1920"], icon="library"),
        k.diamond(430, 150, 214, 94, ["Faces from", "/api/faces?"]),
        k.box(636, 62, 268, H, "Window placed on them", ["a third down for a full body,", "centred for a close-up"]),
        k.box(636, 186, 268, H, "Window centred", ["biased above the middle"]),
        k.box(972, 112, 168, H, "800 x 480", tone="accent"),
        k.edge([(40 + W + 8, 150), (430 - 107 - 8, 150)]),
        k.edge([(430 + 107 + 8, 132), (636 - 8, 100)], label="yes", label_dy=-6),
        k.edge([(430 + 107 + 8, 168), (636 - 8, 224)], label="no", label_dy=16),
        k.edge([(636 + 268 + 8, 100), (972 - 8, 136)]),
        k.edge([(636 + 268 + 8, 224), (972 - 8, 164)]),
        k.footer("Without face.read on the API key Immich returns no boxes, the crop falls "
                 "back to centred, and nothing breaks."),
    )
    return k.render()


def selection_pipeline(scheme):
    """Two filters and a score, in the order that costs least."""
    k = Canvas(1180, 372, scheme,
               "A hundred random assets are filtered by orientation, then by whether a "
               "camera took them, then twenty are downloaded and scored for busyness and "
               "the calmest is rendered.")
    W, H = 200, 72
    y = 118
    k.add(
        k.box(24, y, W, H, "Immich random", ["100 assets"], icon="library"),
        k.diamond(348, y + 36, 186, 88, ["Landscape by", "orientation?"]),
        k.diamond(628, y + 36, 186, 88, ["Camera make", "in EXIF?"]),
        k.box(786, y, 172, H, "Download 20,", ["score busyness"]),
        k.box(986, y, 170, H, "Render the calmest", tone="accent"),
        k.edge([(24 + W + 8, y + 36), (348 - 93 - 8, y + 36)]),
        k.edge([(348 + 93 + 8, y + 36), (628 - 93 - 8, y + 36)], label="yes"),
        k.edge([(786 + 172 + 8, y + 36), (986 - 8, y + 36)]),
        k.edge([(628 + 93 + 8, y + 36), (786 - 8, y + 36)], label="yes"),
        # Both drops go the same way, which is the point: cheap tests first.
        k.edge([(348, y + 36 + 44 + 8), (348, y + 132)], label="no", label_at=0.0, label_dy=18, label_anchor="end"),
        k.edge([(628, y + 36 + 44 + 8), (628, y + 132)], label="no", label_at=0.0, label_dy=18, label_anchor="end"),
        k.box(276, y + 132, 144, 48, "Dropped", tone="soft"),
        k.box(556, y + 132, 144, 48, "Dropped", tone="soft"),
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
    out = ROOT / "docs" / "assets"
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in DIAGRAMS.items():
        for scheme in SCHEMES:
            path = out / f"{name}-{scheme}.svg"
            path.write_text(fn(scheme), encoding="utf-8")
    print(f"{len(DIAGRAMS)} diagrams x {len(SCHEMES)} schemes -> docs/assets/")


if __name__ == "__main__":
    main()
