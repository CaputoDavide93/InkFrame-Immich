"""HTTP server that turns Immich photos into 800x480 1-bit e-paper frames.

The panel is a XIAO ESP32-C3: ~200 KB of usable heap, no PSRAM. It cannot hold
a decoded image alongside its own 48 KB display buffer -- that second
allocation is the one reported to fail on this exact board. So this server does
every expensive thing (fetch, orientation filter, crop, tone, dither, pack) and
hands the panel the finished framebuffer in small strips it can copy straight
into the display with a few kilobytes of working memory.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from urllib.parse import parse_qs, urlparse

from immich import (FRAME_BYTES, Asset, Immich, detail_score, pack,
                    render, to_bmp)
from immich import _INVERT

LOG = logging.getLogger("immichframe")

IMMICH_URL = os.environ.get("IMMICH_URL", "").rstrip("/")
if not IMMICH_URL:
    raise SystemExit("IMMICH_URL must be set, e.g. http://immich.example.lan:2283")
LISTEN_HOST = os.environ.get("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8099"))
# Photos not to show again until this many others have been through.
RECENT_MEMORY = int(os.environ.get("RECENT_MEMORY", "120"))
SMOOTH = float(os.environ.get("RENDER_SMOOTH", "0.45"))
CURVE = float(os.environ.get("RENDER_CURVE", "0.35"))
EDGE = int(os.environ.get("RENDER_EDGE", "55"))
CONTRAST = float(os.environ.get("RENDER_CONTRAST", "1.05"))
# How many candidates to actually download and score before choosing. Showing
# one photo a week means the cost of being picky is paid once a week.
CANDIDATES = int(os.environ.get("CANDIDATES", "20"))
# Reject anything busier than this outright. Measured range on this library is
# 2.7 to 59.5; grass and foliage sit above 30 and dither into visible speckle
# whatever the algorithm.
MAX_BUSYNESS = float(os.environ.get("MAX_BUSYNESS", "22"))
REQUIRE_CAMERA = os.environ.get("REQUIRE_CAMERA", "1") != "0"
STATE_FILE = os.environ.get("STATE_FILE", "/data/state.json")
# A person is offered as a source only above this many landscape photographs.
# Below it the source runs dry against the recently-shown list and repeats.
MIN_PERSON_PHOTOS = int(os.environ.get("MIN_PERSON_PHOTOS", "20"))
PEOPLE_RECOUNT_SECONDS = int(os.environ.get("PEOPLE_RECOUNT_SECONDS", str(24 * 3600)))
HEARTBEAT = os.environ.get("HEARTBEAT_FILE", "/tmp/immichframe-heartbeat")
LAST_OK = os.environ.get("LAST_OK_FILE", "/tmp/immichframe-render-ok")


def _read_api_key() -> str:
    path = os.environ.get("IMMICH_API_KEY_FILE")
    if path:
        with open(path) as handle:
            return handle.read().strip()
    key = os.environ.get("IMMICH_API_KEY", "").strip()
    if not key:
        raise SystemExit("IMMICH_API_KEY_FILE or IMMICH_API_KEY must be set")
    return key


# Every setting Home Assistant may change: name -> (type, min, max, default).
# The env var is only the default for a fresh state file; after that the
# persisted value wins, so a redeploy never silently undoes a change somebody
# made from the dashboard.
SETTING_SPEC: dict[str, tuple[type, float, float, object]] = {
    "smooth":       (float, 0.0, 1.0,  SMOOTH),
    "curve":        (float, 0.0, 1.0,  CURVE),
    "edge":         (int,   0,   200,  EDGE),
    "contrast":     (float, 0.5, 2.0,  CONTRAST),
    "candidates":   (int,   1,   60,   CANDIDATES),
    "max_busyness": (float, 1.0, 100.0, MAX_BUSYNESS),
    "require_camera": (bool, 0, 1,     REQUIRE_CAMERA),
    # Delivered to the panel on every /wake, so neither needs a reflash. Hours
    # rather than seconds because that is how anyone thinks about a photo
    # frame; the panel gets seconds.
    "sleep_hours":        (float, 1, 336, float(os.environ.get("SLEEP_HOURS", "168"))),
    "ota_window_seconds": (int,   5, 300, int(os.environ.get("OTA_WINDOW_SECONDS", "20"))),
}


class Source:
    """Which photos the frame draws from, and how they are rendered. Home
    Assistant writes both.

    Persisted, because the panel sleeps for a week between wakes and a service
    restart in between must not silently revert the household's choice back to
    Random -- that would look exactly like the push never worked.
    """

    VALID = ("random", "person", "people", "recent", "album")

    def __init__(self, path: str) -> None:
        self.path = path
        self.mode = "random"
        self.person = ""
        self.people: list[str] = []
        self.album = ""
        self.days = 90
        self.settings: dict[str, object] = {k: v[3] for k, v in SETTING_SPEC.items()}
        self.load()

    def load(self) -> None:
        try:
            with open(self.path) as handle:
                data = json.load(handle)
            self.mode = data.get("mode", "random")
            self.person = data.get("person", "")
            self.people = [str(x) for x in (data.get("people") or [])]
            self.album = data.get("album", "")
            self.days = int(data.get("days", 90))
            for key, raw in (data.get("settings") or {}).items():
                if key in SETTING_SPEC:
                    try:
                        self.settings[key] = self._coerce(key, raw)
                    except ValueError as exc:
                        LOG.warning("ignoring persisted %s=%r: %s", key, raw, exc)
            LOG.info("source restored: %s, settings %s", self.describe(), self.settings)
        except FileNotFoundError:
            pass
        except Exception as exc:  # noqa: BLE001 - a corrupt file must not stop the frame
            LOG.warning("could not read %s, using defaults: %s", self.path, exc)

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as handle:
                json.dump({"mode": self.mode, "person": self.person,
                           "people": self.people, "album": self.album,
                           "days": self.days, "settings": self.settings}, handle)
        except OSError as exc:
            LOG.warning("could not persist source: %s", exc)

    @staticmethod
    def _coerce(key: str, raw: object):
        kind, lo, hi, _ = SETTING_SPEC[key]
        if kind is bool:
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("1", "true", "on", "yes")
        value = kind(float(raw))
        if not lo <= value <= hi:
            raise ValueError(f"{key} must be between {lo} and {hi}")
        return value

    def update_settings(self, changes: dict[str, object]) -> dict[str, object]:
        """Validate and apply a partial update. Unknown keys are refused rather
        than dropped, so a typo in a caller is an error and not a silent no-op."""
        unknown = set(changes) - set(SETTING_SPEC)
        if unknown:
            raise ValueError(f"unknown settings: {', '.join(sorted(unknown))}")
        coerced = {k: self._coerce(k, v) for k, v in changes.items()}
        self.settings.update(coerced)
        self.save()
        return self.settings

    def set(self, mode: str, person: str = "", days: int | None = None,
            people: list[str] | None = None, album: str | None = None) -> None:
        mode = (mode or "random").lower()
        if mode not in self.VALID:
            raise ValueError(f"mode must be one of {', '.join(self.VALID)}")
        if mode == "person" and not person:
            raise ValueError("mode 'person' needs a person name")
        if mode == "album" and not (album or self.album):
            raise ValueError("mode 'album' needs an album name")
        self.mode = mode
        self.person = person
        # The people list and album are kept even when another mode is active,
        # so switching to People or Album brings back the last choice instead
        # of an empty one.
        if people is not None:
            self.people = [p for p in (x.strip() for x in people) if p]
        if album is not None:
            self.album = album
        if days is not None:
            self.days = int(days)
        self.save()

    def describe(self) -> str:
        if self.mode == "person":
            return f"person:{self.person}"
        if self.mode == "people":
            return "people:" + ",".join(self.people)
        if self.mode == "album":
            return f"album:{self.album}"
        if self.mode == "recent":
            return f"recent:{self.days}d"
        return "random"


class FrameStore:
    """Holds the rendered frame, and the one before it.

    Keeping the previous generation matters: the panel fetches the frame in
    strips, and a rotation landing between strip 3 and strip 4 would otherwise
    paste half of one photo onto half of another. A panel mid-fetch keeps
    reading the generation it started with.
    """

    def __init__(self, client: Immich, source: Source) -> None:
        self.client = client
        self.source = source
        # What the PANEL has actually fetched, which is not the same as what
        # has been rendered. E-paper holds its last image with no power, so a
        # frame nobody collected looks identical to one on the wall.
        self.fetched_generation = 0
        self.fetched_at: float | None = None
        # name -> {"landscape": n, "eligible": bool}. Counting means paging
        # every named person's photos, ~20-30s for this library, so it runs
        # in the background and is refreshed daily; callers that need it
        # complete can wait on `people_ready`.
        self.people: dict[str, dict] = {}
        self.people_counted_at: float | None = None
        self.people_ready = threading.Event()
        self._albums: list[str] = []

        self.lock = threading.Lock()
        self.generations: dict[int, bytes] = {}
        # Encoded once per generation, not once per request. The panel fetches
        # a frame a handful of times a week, but /preview.png and the Home
        # Assistant sensor poll far more often, and re-encoding a PNG of
        # dithered noise is pure waste.
        self.encoded: dict[tuple[int, str], bytes] = {}
        self.meta: dict[int, dict] = {}
        self.current = 0
        self.recent: deque[str] = deque(maxlen=RECENT_MEMORY)
        self.last_error: str | None = None

    def count_people(self) -> None:
        try:
            named = self.client.people()
            summary: dict[str, dict] = {}
            for name, pid in named.items():
                n = len(self.client.by_person(pid))
                summary[name] = {"landscape": n, "eligible": n >= MIN_PERSON_PHOTOS}
            albums = sorted(self.client.albums())
            with self.lock:
                self.people = summary
                self.people_counted_at = time.time()
                self._albums = albums
            eligible = sorted(k for k, v in summary.items() if v["eligible"])
            LOG.info("people counted: %d named, eligible: %s", len(summary), eligible)
        except Exception as exc:  # noqa: BLE001 - a failed count must not stop the frame
            LOG.warning("people count failed: %s", exc)
        finally:
            self.people_ready.set()

    def albums_cached(self) -> list[str]:
        """Album names, refreshed alongside the daily people count."""
        with self.lock:
            return list(self._albums)

    def people_summary(self, wait: bool = False) -> dict[str, dict]:
        if wait:
            self.people_ready.wait(timeout=90)
        with self.lock:
            return dict(self.people)
    def rotate(self) -> int:
        """Render the next photo. Returns the new generation id.

        Downloads several candidates and picks the one that will survive one
        bit best, rather than taking the first landscape photo it sees. If
        every candidate is too busy it still shows the calmest of them: a
        speckly photo beats last week's photo left up forever, and `busyness`
        in /status says which happened.
        """
        cfg = self.source.settings
        candidates = int(cfg["candidates"])
        max_busyness = float(cfg["max_busyness"])

        pool = self._pool()
        if not pool:
            raise RuntimeError(
                f"no landscape photographs for source {self.source.describe()}")

        scored: list[tuple[float, dict, object]] = []
        for asset in pool[:candidates]:
            try:
                img = self.client.preview(asset["id"])
            except Exception as exc:  # noqa: BLE001 - one bad asset must not stop the frame
                LOG.warning("preview failed for %s: %s", asset["id"][:8], exc)
                continue
            scored.append((detail_score(img), asset, img))
        if not scored:
            raise RuntimeError("no candidate preview could be downloaded")

        scored.sort(key=lambda row: row[0])
        busyness, chosen, img = scored[0]
        rejected = sum(1 for row in scored if row[0] > max_busyness)
        if busyness > max_busyness:
            LOG.warning("every candidate was busier than %.1f; showing the "
                        "calmest at %.1f", max_busyness, busyness)

        exif = chosen.get("exifInfo") or {}
        asset = Asset(id=chosen["id"], name=chosen.get("originalFileName", ""),
                      taken=exif.get("dateTimeOriginal") or chosen.get("fileCreatedAt"),
                      busyness=round(busyness, 1))

        started = time.monotonic()
        frame = render(img, smooth=float(cfg["smooth"]), curve=float(cfg["curve"]),
                       edge=int(cfg["edge"]), contrast=float(cfg["contrast"]))
        payload = pack(frame)
        elapsed = time.monotonic() - started

        with self.lock:
            generation = self.current + 1
            self.generations[generation] = payload
            self.meta[generation] = {
                "asset_id": asset.id,
                "name": asset.name,
                "taken": asset.taken,
                "busyness": asset.busyness,
                "source": self.source.describe(),
                "candidates_scored": len(scored),
                "candidates_too_busy": rejected,
                "settings": dict(cfg),
                "rendered_at": time.time(),
                "render_seconds": round(elapsed, 2),
            }
            # Two generations is enough: one being served, one being fetched.
            for stale in [g for g in self.generations if g < generation - 1]:
                self.generations.pop(stale, None)
                self.meta.pop(stale, None)
            for key in [k for k in self.encoded if k[0] < generation - 1]:
                self.encoded.pop(key, None)
            self.current = generation
            self.recent.append(asset.id)
        LOG.info("gen %d: %s busyness %.1f (best of %d) in %.2fs",
                 generation, asset.name, busyness, len(scored), elapsed)
        _touch(LAST_OK)
        return generation

    def _pool(self) -> list[dict]:
        """Candidate assets for the selected source, newest bias removed.

        A narrow source can run dry once `recent` exclusions are applied -- of
        the twelve named people here only three have more than twenty landscape
        photographs. Rather than fail, a narrowed source that yields nothing
        falls back to its unfiltered self and says so, because a blank week is
        worse than a repeat.
        """
        import random as _random
        mode = self.source.mode
        if mode == "person":
            people = self.client.people()
            person_id = people.get(self.source.person)
            if not person_id:
                LOG.warning("person %r is not a named face in Immich; "
                            "falling back to random", self.source.person)
                return self.client.candidates(want=int(self.source.settings["candidates"]),
                                              exclude=set(self.recent),
                                              require_camera=bool(self.source.settings["require_camera"]))
            assets = self.client.by_person(person_id)
        elif mode == "people":
            # OR, not AND: photos of ANY chosen person. Immich's own multi-
            # person search is AND -- assets containing everyone at once --
            # which for "Alice or Bob" is almost never what is meant.
            people = self.client.people()
            seen: set[str] = set()
            assets = []
            for name in self.source.people:
                pid = people.get(name)
                if not pid:
                    LOG.warning("person %r is not a named face; skipping", name)
                    continue
                for asset in self.client.by_person(pid):
                    if asset["id"] not in seen:
                        seen.add(asset["id"])
                        assets.append(asset)
            if not assets:
                LOG.warning("no photos for people %s; falling back to random",
                            self.source.people)
                return self.client.candidates(want=int(self.source.settings["candidates"]),
                                              exclude=set(self.recent),
                                              require_camera=bool(self.source.settings["require_camera"]))
        elif mode == "album":
            albums = self.client.albums()
            album_id = albums.get(self.source.album)
            if not album_id:
                LOG.warning("album %r does not exist; falling back to random",
                            self.source.album)
                return self.client.candidates(want=int(self.source.settings["candidates"]),
                                              exclude=set(self.recent),
                                              require_camera=bool(self.source.settings["require_camera"]))
            assets = self.client.by_album(album_id)
        elif mode == "recent":
            assets = self.client.recent(days=self.source.days)
        else:
            return self.client.candidates(want=int(self.source.settings["candidates"]),
                                          exclude=set(self.recent),
                                          require_camera=bool(self.source.settings["require_camera"]))

        fresh = [a for a in assets if a["id"] not in self.recent]
        if not fresh and assets:
            LOG.info("every photo for %s has been shown recently; repeating",
                     self.source.describe())
            fresh = assets
        _random.shuffle(fresh)
        return fresh

    def encode(self, generation: int, fmt: str) -> bytes:
        """Encoded frame, built once per generation and kept."""
        key = (generation, fmt)
        with self.lock:
            hit = self.encoded.get(key)
        if hit is not None:
            return hit

        _, payload = self.get(generation)
        if fmt == "bmp":
            body = to_bmp(payload)
        else:
            from PIL import Image
            img = Image.frombytes("1", (800, 480), payload.translate(_INVERT))
            buf = BytesIO()
            # No point asking zlib to work hard on dithered noise: at level 9
            # the file is within a few per cent of level 6 and takes markedly
            # longer to produce.
            img.save(buf, "PNG", optimize=False, compress_level=6)
            body = buf.getvalue()
        with self.lock:
            self.encoded[key] = body
        return body

    def note_panel_fetch(self, generation: int) -> None:
        with self.lock:
            self.fetched_generation = generation
            self.fetched_at = time.time()

    def get(self, generation: int | None) -> tuple[int, bytes]:
        with self.lock:
            if generation is None or generation not in self.generations:
                generation = self.current
            if generation not in self.generations:
                raise RuntimeError("no frame rendered yet")
            return generation, self.generations[generation]

    def ensure(self) -> None:
        with self.lock:
            has_frame = self.current in self.generations
        if not has_frame:
            self.rotate()


def _touch(path: str) -> None:
    try:
        with open(path, "w") as handle:
            handle.write(str(time.time()))
    except OSError as exc:
        LOG.warning("could not touch %s: %s", path, exc)


class Handler(BaseHTTPRequestHandler):
    store: FrameStore = None  # type: ignore[assignment]
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quieter than the stdlib default
        LOG.debug("%s - %s", self.address_string(), fmt % args)

    def _send(self, code: int, body: bytes, content_type: str,
              extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        import json
        self._send(code, json.dumps(obj).encode() + b"\n", "application/json")

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        url = urlparse(self.path)
        query = parse_qs(url.query)
        try:
            self._route(url.path, query)
        except Exception as exc:  # noqa: BLE001 - any failure becomes a 500, never a crash
            LOG.exception("request failed: %s", self.path)
            self.store.last_error = f"{type(exc).__name__}: {exc}"
            self._json(500, {"error": str(exc)})

    do_POST = do_GET

    def _route(self, path: str, query: dict) -> None:
        store = self.store

        if path == "/healthz":
            self._json(200, {"ok": True, "generation": store.current,
                             "last_error": store.last_error})
            return

        if path == "/people":
            # So Home Assistant can offer the real list rather than a
            # hand-typed one that silently stops matching -- and only the
            # people who have enough landscape photographs to sustain a frame.
            self._json(200, {"people": store.people_summary(wait=True),
                             "min_photos": MIN_PERSON_PHOTOS})
            return

        if path == "/settings":
            if query:
                changes = {k: v[0] for k, v in query.items()}
                try:
                    store.source.update_settings(changes)
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                    return
                LOG.info("settings changed by push: %s", changes)
            self._json(200, {"settings": store.source.settings,
                             "spec": {k: {"type": v[0].__name__, "min": v[1],
                                          "max": v[2], "default": v[3]}
                                      for k, v in SETTING_SPEC.items()}})
            return

        if path == "/source":
            if query:
                store.source.set(
                    query.get("mode", ["random"])[0],
                    query.get("person", [""])[0],
                    int(query["days"][0]) if "days" in query else None,
                    people=query["people"][0].split(",") if "people" in query else None,
                    album=query["album"][0] if "album" in query else None,
                )
                LOG.info("source set by push: %s", store.source.describe())
            self._json(200, {"mode": store.source.mode,
                             "person": store.source.person,
                             "people": store.source.people,
                             "album": store.source.album,
                             "days": store.source.days,
                             "describes": store.source.describe()})
            return

        if path == "/albums":
            self._json(200, {"albums": sorted(store.client.albums())})
            return

        if path == "/wake":
            # The panel's one call per wake. Rotates ONLY if the current
            # generation has already been collected: a frame Home Assistant
            # rendered yesterday and nobody has seen yet is delivered before a
            # new one is made. Also carries the wake parameters, so the sleep
            # interval and OTA window are settings rather than firmware.
            with store.lock:
                collected = store.fetched_generation == store.current
            if collected or store.current == 0:
                generation = store.rotate()
            else:
                generation = store.current
                LOG.info("wake: gen %d not yet collected, serving it", generation)
            cfg = store.source.settings
            self._json(200, {"generation": generation, "bytes": FRAME_BYTES,
                             "sleep_seconds": int(float(cfg["sleep_hours"]) * 3600),
                             "ota_window_seconds": int(cfg["ota_window_seconds"])})
            return

        if path == "/status":
            meta = store.meta.get(store.current, {})
            on_panel = store.fetched_generation == store.current
            self._json(200, {"generation": store.current, "current": meta,
                             "source": store.source.describe(),
                             # Rendered is not the same as displayed. E-paper
                             # keeps its last image with no power, so a frame
                             # the panel never collected looks exactly like one
                             # hanging on the wall.
                             "on_panel": on_panel,
                             "panel_fetched_generation": store.fetched_generation,
                             "panel_fetched_at": store.fetched_at,
                             "recent_count": len(store.recent),
                             "settings": store.source.settings,
                             "people": store.people_summary(),
                             "source_people": store.source.people,
                             "source_album": store.source.album,
                             "source_days": store.source.days,
                             "albums": store.albums_cached(),
                             "last_error": store.last_error})
            return

        if path == "/next":
            # Rotate, then tell the panel which generation to fetch and how
            # many bytes it is. The panel needs no knowledge of the photo.
            generation = store.rotate()
            self._json(200, {"generation": generation, "bytes": FRAME_BYTES,
                             "width": 800, "height": 480})
            return

        if path == "/frame.bin":
            store.ensure()
            generation = query.get("gen", [None])[0]
            generation, payload = store.get(int(generation) if generation else None)
            store.note_panel_fetch(generation)
            offset = int(query.get("offset", ["0"])[0])
            length = int(query.get("len", [str(FRAME_BYTES)])[0])
            if offset < 0 or offset > FRAME_BYTES:
                self._json(416, {"error": "offset out of range"})
                return
            chunk = payload[offset:offset + length]
            self._send(200, chunk, "application/octet-stream",
                       {"X-Frame-Generation": str(generation),
                        "X-Frame-Total": str(FRAME_BYTES)})
            return

        if path in ("/frame.png", "/frame.bmp", "/preview.png"):
            store.ensure()
            gen, _ = store.get(None)
            if path != "/preview.png":
                # Only the panel fetches frame.*; /preview.png is for humans
                # and must not claim the photo reached the glass.
                store.note_panel_fetch(gen)
            fmt = "bmp" if path == "/frame.bmp" else "png"
            body = store.encode(gen, fmt)
            self._send(200, body,
                       "image/bmp" if fmt == "bmp" else "image/png",
                       {"Cache-Control": "no-store",
                        "X-Frame-Generation": str(gen)})
            return

        self._json(404, {"error": "not found"})


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    client = Immich(IMMICH_URL, _read_api_key())
    store = FrameStore(client, Source(STATE_FILE))
    Handler.store = store

    def heartbeat() -> None:
        while True:
            _touch(HEARTBEAT)
            time.sleep(30)

    threading.Thread(target=heartbeat, daemon=True).start()

    def recount_people() -> None:
        while True:
            store.count_people()
            time.sleep(PEOPLE_RECOUNT_SECONDS)

    threading.Thread(target=recount_people, daemon=True).start()

    try:
        store.rotate()
    except Exception as exc:  # noqa: BLE001 - start even if Immich is briefly down
        LOG.error("initial render failed, serving once Immich answers: %s", exc)
        store.last_error = str(exc)

    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    LOG.info("listening on %s:%d, immich at %s", LISTEN_HOST, LISTEN_PORT, IMMICH_URL)
    server.serve_forever()


if __name__ == "__main__":
    main()
