#!/usr/bin/env python3
"""A stand-in Immich for the screenshots: a small library of drawn scenes.

    python tools/screenshots/fake_immich.py [port]

Answers only the calls the renderer makes (`src/immich.py`), with a library of
synthetic landscapes made by `tools/gen_brand.py`'s `scene()`, each one shifted
in colour, flipped or cropped so the frames differ. Nothing here is a
photograph, a person or a real place; the three "people" are labels on subsets
of the same drawn scenes.

Not a model of Immich: it ignores search filters it does not need and returns
every asset, which is enough for the renderer to pick from.
"""
from __future__ import annotations

import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # tools/ -> gen_brand
SRC = HERE.parents[1] / "server" / "src"
if not SRC.exists():
    SRC = HERE.parents[1] / "src"
sys.path.insert(0, str(SRC))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import gen_brand  # noqa: E402

COUNT = 30
PEOPLE = {"Alex": range(0, 24), "Sam": range(6, 30), "Jo": range(12, 30)}
PERSON_ID = {name: f"person-{i}" for i, name in enumerate(PEOPLE)}
ALBUMS = {"Summer": range(0, 12)}
WIDTH, HEIGHT = 1600, 1000


def make_image(index: int) -> Image.Image:
    """Scene `index`: the base drawing, tinted, maybe flipped, cropped a little."""
    base = gen_brand.scene(WIDTH, HEIGHT)
    rng = np.random.default_rng(index)
    arr = np.asarray(base, np.float32)
    tint = rng.uniform(0.82, 1.18, 3)
    arr = (arr * tint + rng.uniform(-14, 14)).clip(0, 255)
    img = Image.fromarray(arr.astype(np.uint8))
    if index % 2:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    dx, dy = int(rng.integers(0, 120)), int(rng.integers(0, 70))
    return img.crop((dx, dy, WIDTH - 60 + dx % 60, HEIGHT - 40 + dy % 40)).resize((WIDTH, HEIGHT))


def asset(index: int) -> dict:
    return {
        "id": f"asset-{index:03d}",
        "originalFileName": f"IMG_{4000 + index}.jpg",
        "fileCreatedAt": f"2026-07-{1 + index % 28:02d}T12:00:00.000Z",
        "type": "IMAGE",
        "exifInfo": {
            "make": "Demo Camera",
            "model": "Model One",
            "exifImageWidth": WIDTH,
            "exifImageHeight": HEIGHT,
            "orientation": "1",
            "dateTimeOriginal": f"2026-07-{1 + index % 28:02d}T12:00:00.000Z",
        },
    }


ASSETS = [asset(i) for i in range(COUNT)]
_cache: dict[int, bytes] = {}
_lock = threading.Lock()


def jpeg(index: int) -> bytes:
    with _lock:
        if index not in _cache:
            buffer = io.BytesIO()
            make_image(index).save(buffer, "JPEG", quality=88)
            _cache[index] = buffer.getvalue()
        return _cache[index]


def page(items: list[dict]) -> dict:
    return {"assets": {"items": items, "total": len(items), "nextPage": None}}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # silent
        pass

    def _send(self, body: bytes, kind: str = "application/json") -> None:
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj) -> None:
        self._send(json.dumps(obj).encode())

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/api/server/ping":
            return self._json({"res": "pong"})
        if url.path == "/api/people":
            return self._json({"people": [{"id": PERSON_ID[n], "name": n} for n in PEOPLE]})
        if url.path == "/api/albums":
            return self._json([{"id": f"album-{n}", "albumName": n} for n in ALBUMS])
        if url.path == "/api/faces":
            return self._json([])
        if url.path.startswith("/api/assets/") and url.path.endswith("/thumbnail"):
            index = int(url.path.split("/")[3].split("-")[1])
            return self._send(jpeg(index), "image/jpeg")
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        body = self._body()
        if url.path == "/api/search/random":
            return self._json(ASSETS[: int(body.get("size", 100))])
        if url.path in ("/api/search/metadata", "/api/search/smart"):
            items = ASSETS
            people = body.get("personIds") or []
            if people:
                wanted = {i for n, p in PERSON_ID.items() if p in people for i in PEOPLE[n]}
                items = [a for i, a in enumerate(ASSETS) if i in wanted]
            if body.get("albumIds"):
                items = [a for i, a in enumerate(ASSETS) if i in ALBUMS["Summer"]]
            return self._json(page(items))
        self.send_error(404)


def serve(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 2283
    print(f"stand-in Immich on 127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
