"""HTTP server that turns Immich photos into 800x480 1-bit e-paper frames.

The panel is a XIAO ESP32-C3: ~200 KB of usable heap, no PSRAM. It cannot hold
a decoded image alongside its own 48 KB display buffer -- that second
allocation is the one reported to fail on this exact board. So this server does
every expensive thing (fetch, orientation filter, crop, tone, dither, pack) and
hands the panel the finished framebuffer in small strips it can copy straight
into the display with a few kilobytes of working memory.
"""
from __future__ import annotations

import datetime as dt
import json
import hmac
import logging
import os
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from urllib.parse import parse_qs, urlparse

from immich import (FRAME_BYTES, Asset, Immich, detail_score, is_landscape,
                    pack, render, to_bmp)
from immich import _INVERT

LOG = logging.getLogger("immichframe")

# Validated in main(), not here: a module that exits on import cannot be
# imported by a test, and the tests for this file's own logic then have to
# reach for a subprocess or fake the environment to say anything at all.
IMMICH_URL = os.environ.get("IMMICH_URL", "").rstrip("/")
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
# A FAILED count must not cost a whole day. On 2026-09-22 this container came
# up before Immich was listening, the one daily count died on a refused
# connection, and /people served {} for the next 22 hours -- which in Home
# Assistant meant the three "Include <person>" switches were never created and
# the People source had nobody to draw from. Nothing was broken; the renderer
# had simply asked once, at the only moment in the day the answer was
# unavailable.
#
# So a failure retries, and the wait GROWS rather than hammering: a frame that
# refreshes every three days gains nothing from asking Immich every thirty
# seconds for an hour. Doubling from 30s to a 15-minute ceiling covers a slow
# co-start in the first minute and a longer Immich outage without noise.
PEOPLE_RETRY_FIRST_SECONDS = 30
PEOPLE_RETRY_MAX_SECONDS = 15 * 60
HEARTBEAT = os.environ.get("HEARTBEAT_FILE", "/tmp/immichframe-heartbeat")
LAST_OK = os.environ.get("LAST_OK_FILE", "/tmp/immichframe-render-ok")


def _read_renderer_token() -> str:
    """Read the shared panel/Home Assistant token without putting it in URLs."""
    path = os.environ.get("INKFRAME_TOKEN_FILE")
    if path:
        with open(path) as handle:
            token = handle.read().strip()
    else:
        token = os.environ.get("INKFRAME_TOKEN", "").strip()
    if not token:
        raise SystemExit("INKFRAME_TOKEN_FILE or INKFRAME_TOKEN must be set")
    return token


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
    # Off means portraits are cropped to fit rather than skipped. The crop
    # window is placed on the faces Immich detected, so a standing subject
    # keeps their head instead of being cut off at the chest.
    "landscape_only": (bool, 0, 1,     os.environ.get("LANDSCAPE_ONLY", "1") != "0"),
    # Delivered to the panel on every /wake, so neither needs a reflash. Hours
    # rather than seconds because that is how anyone thinks about a photo
    # frame; the panel gets seconds.
    "sleep_hours":        (float, 1, 336, float(os.environ.get("SLEEP_HOURS", "168"))),
    "ota_window_seconds": (int,   5, 300, int(os.environ.get("OTA_WINDOW_SECONDS", "20"))),
    # CHECKING IS NOT DRAWING, AND ONLY DRAWING IS EXPENSIVE.
    #
    # A wake that draws runs about 35 seconds: associate, /wake, fetch,
    # refresh, then hold the OTA window. A wake that only asks "is there a
    # photo for me?" skips the fetch, the refresh AND the OTA hold -- that
    # hold lives inside on_download_finished and there is no download -- so
    # it is about 7 seconds. Five times cheaper.
    #
    # That makes the two cadences worth separating. The panel can wake often
    # enough to be responsive when somebody asks for a photo, while the
    # picture on the wall only changes every few days. Four checks a day plus
    # a draw every third day is ~40s awake per day; drawing every 8 hours is
    # ~105s.
    "refresh_days": (int, 1, 30, int(os.environ.get("REFRESH_DAYS", "3"))),
    # Local hour for the scheduled draw. The panel wakes on its own timer and
    # deep sleep drifts, so this is "the first check at or after this hour",
    # never an exact alarm.
    "refresh_hour": (int, 0, 23, int(os.environ.get("REFRESH_HOUR", "7"))),
}


class Source:
    """Which photos the frame draws from, and how they are rendered. Home
    Assistant writes both.

    Persisted, because the panel sleeps for a week between wakes and a service
    restart in between must not silently revert the household's choice back to
    Random -- that would look exactly like the push never worked.
    """

    VALID = ("random", "person", "people", "recent", "album", "search")

    def __init__(self, path: str) -> None:
        self.path = path
        self.mode = "random"
        self.person = ""
        self.people: list[str] = []
        self.album = ""
        self.query = ""
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
            self.query = data.get("query", "")
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
                           "query": self.query, "days": self.days,
                           "settings": self.settings}, handle)
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
            people: list[str] | None = None, album: str | None = None,
            query: str | None = None) -> None:
        mode = (mode or "random").lower()
        if mode not in self.VALID:
            raise ValueError(f"mode must be one of {', '.join(self.VALID)}")
        if mode == "person" and not person:
            raise ValueError("mode 'person' needs a person name")
        if mode == "album" and not (album or self.album):
            raise ValueError("mode 'album' needs an album name")
        # Validate what the source will BE, not what it was: passing an empty
        # query used to pass this check on the strength of the old term and
        # then blank it, leaving mode 'search' with nothing to search for.
        if mode == "search" and not (self.query if query is None else query.strip()):
            raise ValueError("mode 'search' needs something to search for")
        self.mode = mode
        self.person = person
        # The people list and album are kept even when another mode is active,
        # so switching to People or Album brings back the last choice instead
        # of an empty one.
        if people is not None:
            self.people = [p for p in (x.strip() for x in people) if p]
        if album is not None:
            self.album = album
        if query is not None:
            self.query = query.strip()
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
        if self.mode == "search":
            return f"search:{self.query}"
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
        # The heartbeat. On a multi-day draw cycle the FETCH timestamp cannot
        # tell you the panel is alive -- three days without one is normal --
        # so the check itself has to be the evidence. 0 means "has not called
        # since this process started", which is honest rather than stale.
        self.last_wake_at = 0.0
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
        # Last, because it restores the state everything above declares.
        self._restore()

    # ── surviving a restart ───────────────────────────────────────────────
    # The state file has always held the source and the settings. It did not
    # hold the picture, so a container restart left generation 0 and every
    # image route answering 500 until something rendered successfully. With a
    # narrow source that has run dry -- an album with nothing in it yet -- that
    # is indefinitely, and the panel's next wake gets nothing at all.

    def _frame_path(self, slot: str = "frame") -> str:
        """Two slots, because the newest frame and the one on the wall are
        different pictures whenever a render has happened since the panel last
        woke -- which on a three-day cycle is most of the time.

        Saving only the newest lost the collected one on every restart, and
        `On the panel` went blank until the panel's next wake, days away. It
        said unknown rather than showing the wrong photo, which was the right
        failure, but it is still a blank card describing a wall that has a
        picture on it.
        """
        return os.path.join(os.path.dirname(self.source.path) or "/data", f"{slot}.bin")

    def _read_slot(self, slot: str) -> tuple[bytes, dict] | None:
        try:
            with open(self._frame_path(slot), "rb") as handle:
                payload = handle.read()
        except FileNotFoundError:
            return None
        except OSError as exc:
            LOG.warning("could not read the %s frame: %s", slot, exc)
            return None
        if len(payload) != FRAME_BYTES:
            LOG.warning("saved %s frame is %d bytes, not %d; ignoring",
                        slot, len(payload), FRAME_BYTES)
            return None
        meta: dict = {}
        try:
            with open(self._frame_path(slot) + ".json") as handle:
                meta = json.load(handle)
        except FileNotFoundError:
            pass
        except Exception as exc:  # noqa: BLE001 - a bad sidecar loses the caption, not the picture
            LOG.warning("could not read the %s frame's details: %s", slot, exc)
        return payload, meta

    def _restore(self) -> None:
        """Rebuild both pictures. Generation numbering restarts, so the panel's
        frame takes 1 and the newest takes 2 when they differ -- `on_panel`
        then reports false, which is the truth: a newer photo is waiting."""
        try:
            panel = self._read_slot("panel")
            latest = self._read_slot("frame")
            if panel:
                payload, meta = panel
                self.current = 1
                self.generations[1] = payload
                self.meta[1] = {k: v for k, v in meta.items() if not k.startswith("_")}
                self.fetched_generation = 1
                self.fetched_at = meta.get("_fetched_at")
            if latest:
                payload, meta = latest
                same = bool(panel) and meta.get("asset_id") == panel[1].get("asset_id")
                generation = 1 if (same or not panel) else 2
                self.current = generation
                self.generations[generation] = payload
                self.meta[generation] = {k: v for k, v in meta.items() if not k.startswith("_")}
                if not panel and meta.get("_was_on_panel"):
                    self.fetched_generation = 1
                    self.fetched_at = meta.get("_fetched_at")
            if panel or latest:
                LOG.info("restored: on the panel %r, up next %r",
                         (panel[1].get("name") if panel else None),
                         (latest[1].get("name") if latest else None))
        except Exception as exc:  # noqa: BLE001 - a bad file must not stop the frame
            LOG.warning("could not restore the saved frames: %s", exc)

    def _persist(self, payload: bytes, meta: dict, slot: str = "frame") -> None:
        try:
            path = self._frame_path(slot)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # Write then replace, so a restart mid-write cannot leave a
            # half-written frame that restores as a band of noise.
            with open(path + ".tmp", "wb") as handle:
                handle.write(payload)
            os.replace(path + ".tmp", path)
            with open(path + ".json.tmp", "w") as handle:
                json.dump(meta, handle)
            os.replace(path + ".json.tmp", path + ".json")
        except OSError as exc:
            LOG.warning("could not persist the %s frame: %s", slot, exc)

    def count_people(self) -> bool:
        """Recount eligible people. True if the count actually landed.

        The return value is what lets the caller retry: before it existed the
        only outcome was a log line, so the scheduling loop could not tell a
        good count from a refused connection and slept a day either way.
        """
        try:
            named = self.client.people()
            summary: dict[str, dict] = {}
            for name, pid in named.items():
                n = len(self.client.by_person(
                    pid, require_camera=bool(self.source.settings["require_camera"])
                ))
                summary[name] = {"landscape": n, "eligible": n >= MIN_PERSON_PHOTOS}
            albums = sorted(self.client.albums())
            with self.lock:
                self.people = summary
                self.people_counted_at = time.time()
                self._albums = albums
            eligible = sorted(k for k, v in summary.items() if v["eligible"])
            LOG.info("people counted: %d named, eligible: %s", len(summary), eligible)
            return True
        except Exception as exc:  # noqa: BLE001 - a failed count must not stop the frame
            LOG.warning("people count failed: %s", exc)
            return False
        finally:
            # Set on FAILURE too. people_summary(wait=True) must not block for
            # its full 90 seconds on every request while Immich is down; an
            # empty answer now beats a slow empty answer later.
            self.people_ready.set()

    def albums_cached(self) -> list[str]:
        """Album names, refreshed alongside the daily people count."""
        with self.lock:
            return list(self._albums)

    def refresh_albums(self) -> list[str]:
        """Read the album list from Immich now and replace the daily cache.

        The cache is filled once a day beside the people count, which is fine
        for a frame that changes weekly and wrong for the five minutes after
        somebody makes an album. Until this existed, a new album was usable
        immediately by name -- rendering reads the live list -- but absent from
        the Home Assistant picker until the next day, which reads as the
        integration not seeing it at all.
        """
        albums = sorted(self.client.albums())
        with self.lock:
            self._albums = albums
        return albums

    def people_summary(self, wait: bool = False) -> dict[str, dict]:
        if wait:
            self.people_ready.wait(timeout=90)
        with self.lock:
            return dict(self.people)
    def scheduled_refresh_due(self) -> bool:
        """Is this the first check at or after the refresh hour, on the day
        the picture is due to change?

        Date arithmetic, not elapsed seconds, and deliberately so. "Every
        three days at 7am" against a clock that drifts (deep sleep is not
        precise, and the panel wakes on its own timer) has to mean "the first
        check on or after that morning", or the draw slides a little later
        every cycle until it happens at night.
        """
        cfg = self.source.settings
        days = int(cfg.get("refresh_days", 3))
        hour = int(cfg.get("refresh_hour", 7))
        now = dt.datetime.now().astimezone()
        if now.hour < hour:
            return False
        if not self.fetched_at:
            # Never collected anything. /wake's `first_ever` covers generation
            # 0; past that, draw rather than wait days to start the cycle.
            return True
        last = dt.datetime.fromtimestamp(self.fetched_at).astimezone()
        return (now.date() - last.date()).days >= days

    def next_refresh_at(self) -> float | None:
        """When the next DRAW is due, as a timestamp; None before the first one.

        The same arithmetic as `next_refresh_description`, as a number Home
        Assistant can use. Until 2026-09-24 the only machine-readable times
        were the last collection and the last wake, and the dashboard derived
        "Next Wake" from the collection -- which since the check/draw split is
        one to three days old, so it read "Due Now" permanently.
        """
        if not self.fetched_at:
            return None
        cfg = self.source.settings
        days = int(cfg.get("refresh_days", 3))
        hour = int(cfg.get("refresh_hour", 7))
        last = dt.datetime.fromtimestamp(self.fetched_at).astimezone()
        due = (last + dt.timedelta(days=days)).replace(
            hour=hour, minute=0, second=0, microsecond=0)
        return due.timestamp()

    def next_refresh_description(self) -> str:
        """For the log line on a check, so a quiet wake still says something."""
        cfg = self.source.settings
        days = int(cfg.get("refresh_days", 3))
        hour = int(cfg.get("refresh_hour", 7))
        if not self.fetched_at:
            return "unknown (nothing collected yet)"
        last = dt.datetime.fromtimestamp(self.fetched_at).astimezone()
        due = (last + dt.timedelta(days=days)).replace(
            hour=hour, minute=0, second=0, microsecond=0)
        return f"{due:%a %d %b %H:%M}"

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
            # Say which of the two it is. "No photographs" about an album that
            # visibly holds sixteen sends somebody to check their album, when
            # the truth was a filter -- or a bug in how they were fetched.
            shape = ("nothing matched" if bool(self.source.settings["landscape_only"])
                     else "the source is empty")
            raise RuntimeError(
                f"{shape} for source {self.source.describe()}"
                + (" (landscape_only is on, so portraits were skipped)"
                   if bool(self.source.settings["landscape_only"]) else ""))

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

        # Face boxes for the winner only. Scoring twenty candidates is already
        # twenty downloads; asking Immich about faces for the nineteen that
        # lose would be twenty more calls for nothing.
        # For the winner only: scoring twenty candidates is already twenty
        # downloads, and asking about faces for the nineteen that lose would
        # double the call count for nothing. A 4:3 landscape is cropped to 5:3
        # too, so faces help there as well, not only on portraits.
        faces = self.client.faces(asset.id)

        started = time.monotonic()
        frame = render(img, smooth=float(cfg["smooth"]), curve=float(cfg["curve"]),
                       edge=int(cfg["edge"]), contrast=float(cfg["contrast"]),
                       faces=faces)
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
                "portrait": is_landscape(exif) is False,
                "faces_used": len(faces),
                "candidates_scored": len(scored),
                "candidates_too_busy": rejected,
                "settings": dict(cfg),
                "rendered_at": time.time(),
                "render_seconds": round(elapsed, 2),
            }
            # Keep the new frame, the one before it, and whatever the panel is
            # actually displaying. That last one is the point: press Next photo
            # three times before a wake and the panel is three generations
            # behind, so evicting by age alone would throw away the only copy
            # of the picture hanging on the wall.
            keep = {generation, generation - 1, self.fetched_generation}
            for stale in [g for g in self.generations if g not in keep]:
                self.generations.pop(stale, None)
                self.meta.pop(stale, None)
            for key in [k for k in self.encoded if k[0] not in keep]:
                self.encoded.pop(key, None)
            self.current = generation
            self.recent.append(asset.id)
            saved = dict(self.meta[generation])
            saved["_was_on_panel"] = False      # brand new, nobody has it yet
            saved["_fetched_at"] = None
        self._persist(payload, saved)
        LOG.info("gen %d: %s busyness %.1f (best of %d) in %.2fs",
                 generation, asset.name, busyness, len(scored), elapsed)
        self.last_error = None
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
        landscape_only = bool(self.source.settings["landscape_only"])
        require_camera = bool(self.source.settings["require_camera"])
        if mode == "person":
            people = self.client.people()
            person_id = people.get(self.source.person)
            if not person_id:
                LOG.warning("person %r is not a named face in Immich; "
                            "falling back to random", self.source.person)
                return self.client.candidates(want=int(self.source.settings["candidates"]),
                                              exclude=set(self.recent),
                                              require_camera=bool(self.source.settings["require_camera"]),
                                              landscape_only=landscape_only)
            assets = self.client.by_person(person_id, landscape_only=landscape_only,
                                           require_camera=require_camera)
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
                for asset in self.client.by_person(pid, landscape_only=landscape_only,
                                                   require_camera=require_camera):
                    if asset["id"] not in seen:
                        seen.add(asset["id"])
                        assets.append(asset)
            if not assets:
                LOG.warning("no photos for people %s; falling back to random",
                            self.source.people)
                return self.client.candidates(want=int(self.source.settings["candidates"]),
                                              exclude=set(self.recent),
                                              require_camera=bool(self.source.settings["require_camera"]),
                                              landscape_only=landscape_only)
        elif mode == "album":
            albums = self.client.albums()
            album_id = albums.get(self.source.album)
            if not album_id:
                LOG.warning("album %r does not exist; falling back to random",
                            self.source.album)
                return self.client.candidates(want=int(self.source.settings["candidates"]),
                                              exclude=set(self.recent),
                                              require_camera=bool(self.source.settings["require_camera"]),
                                              landscape_only=landscape_only)
            assets = self.client.by_album(album_id, landscape_only=landscape_only,
                                          require_camera=require_camera)
        elif mode == "search":
            assets = self.client.by_search(self.source.query,
                                           landscape_only=landscape_only,
                                           require_camera=require_camera)
            if not assets:
                LOG.warning("nothing matched the search %r", self.source.query)
        elif mode == "recent":
            assets = self.client.recent(days=self.source.days, landscape_only=landscape_only,
                                        require_camera=require_camera)
        else:
            return self.client.candidates(want=int(self.source.settings["candidates"]),
                                          exclude=set(self.recent),
                                          require_camera=bool(self.source.settings["require_camera"]),
                                          landscape_only=landscape_only)

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
            payload = self.generations.get(generation)
            saved = dict(self.meta.get(generation, {}))
            saved["_was_on_panel"] = True
            saved["_fetched_at"] = self.fetched_at
        # Its own slot, so a later render cannot overwrite the picture that is
        # actually on the wall.
        if payload is not None:
            self._persist(payload, saved, slot="panel")

    def get(self, generation: int | None) -> tuple[int, bytes]:
        """The frame for a generation, or the current one when asked for None.

        A generation that was asked for BY NUMBER and is no longer held raises.
        It used to fall back to the newest frame, which meant `?gen=999` -- or
        any evicted generation -- answered 200 with a different photo under the
        caller's label. On a card captioned "On the panel" that is a lie about
        what is hanging on the wall, which is the one thing this system exists
        to get right.
        """
        with self.lock:
            if generation is not None and generation not in self.generations:
                raise KeyError(generation)
            if generation is None:
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

    def _authorised(self) -> bool:
        """Accept a bearer header, never a query token that logs in proxies."""
        supplied = self.headers.get("Authorization", "")
        if supplied.lower().startswith("bearer "):
            supplied = supplied[7:].strip()
        else:
            supplied = self.headers.get("X-InkFrame-Token", "")
        return bool(supplied) and hmac.compare_digest(supplied, self.token)

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        url = urlparse(self.path)
        query = parse_qs(url.query, keep_blank_values=True)
        # Docker needs an unauthenticated liveness probe, but every endpoint
        # that reveals images/state or changes the frame requires the bearer.
        if url.path != "/healthz" and not self._authorised():
            self._json(401, {"error": "authorization required"})
            return
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
            self._json(200, {"ok": True, "generation": store.current})
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
                if "require_camera" in changes:
                    # Eligibility drives HA's Source options. Recount now so
                    # turning the switch off does not leave people hidden for a day.
                    threading.Thread(target=store.count_people, daemon=True).start()
                LOG.info("settings changed by push: %s", changes)
            self._json(200, {"settings": store.source.settings,
                             "spec": {k: {"type": v[0].__name__, "min": v[1],
                                          "max": v[2], "default": v[3]}
                                      for k, v in SETTING_SPEC.items()}})
            return

        if path == "/source":
            if query:
                try:
                    store.source.set(
                        query.get("mode", ["random"])[0],
                        query.get("person", [""])[0],
                        int(query["days"][0]) if "days" in query else None,
                        people=query["people"][0].split(",") if "people" in query else None,
                        album=query["album"][0] if "album" in query else None,
                        query=query["query"][0] if "query" in query else None,
                    )
                except ValueError as exc:
                    # A caller's mistake, not a failure of the frame: 400, and
                    # `last_error` stays for things that actually went wrong
                    # with a render, which is what Home Assistant surfaces.
                    self._json(400, {"error": str(exc)})
                    return
                LOG.info("source set by push: %s", store.source.describe())
            self._json(200, {"mode": store.source.mode,
                             "person": store.source.person,
                             "people": store.source.people,
                             "album": store.source.album,
                             "query": store.source.query,
                             "days": store.source.days,
                             "describes": store.source.describe()})
            return

        if path == "/albums":
            # Live, and it updates the cache /status serves, so asking for the
            # list is also how you refresh it.
            self._json(200, {"albums": store.refresh_albums()})
            return

        if path == "/wake":
            # The panel's one call per wake, and the ONLY place that decides
            # whether the glass changes. The panel does what it is told.
            #
            # Most wakes are a question, not a refresh. A checking wake costs
            # about 7 seconds against 35 for a drawing one, so the panel can
            # wake four times a day and still spend less battery than drawing
            # every eight hours. `draw` is what buys that.
            #
            # It is served even on a check, because this is also the heartbeat:
            # `last_wake_at` is the only evidence the panel is alive, and on a
            # multi-day draw cycle the fetch timestamp cannot be that evidence.
            store.last_wake_at = time.time()
            cfg = store.source.settings
            with store.lock:
                pending = (store.current != 0
                           and store.fetched_generation != store.current)
            first_ever = store.current == 0
            scheduled = store.scheduled_refresh_due()

            # A photo somebody ASKED for outranks the schedule and is never
            # rotated past: it is delivered before a new one is made, which is
            # the whole reason /wake and /next are different endpoints.
            draw = pending or scheduled or first_ever
            if draw and not pending:
                generation = store.rotate()
                LOG.info("wake: drawing gen %d (%s)", generation,
                         "scheduled refresh" if scheduled else "first frame")
            elif pending:
                generation = store.current
                LOG.info("wake: gen %d was asked for and not yet collected, "
                         "serving it", generation)
            else:
                # NOTHING TO DO, AND THAT IS THE COMMON CASE. Do not rotate:
                # rendering a photo nobody will collect burns a generation and
                # makes `on_panel` read false until the next draw, which is
                # exactly the "a newer photo is waiting" signal that would then
                # be lying.
                generation = store.current
                LOG.info("wake: nothing new, next scheduled draw in %s",
                         store.next_refresh_description())
            self._json(200, {"generation": generation, "bytes": FRAME_BYTES,
                             "draw": draw,
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
                             # The heartbeat, not the draw. See last_wake_at.
                             "last_wake_at": store.last_wake_at,
                             "scheduled_refresh_due": store.next_refresh_description(),
                             "next_refresh_at": store.next_refresh_at(),
                             "on_panel_photo": store.meta.get(store.fetched_generation, {}),
                             "recent_count": len(store.recent),
                             "settings": store.source.settings,
                             "people": store.people_summary(),
                             "source_people": store.source.people,
                             "source_album": store.source.album,
                             "source_query": store.source.query,
                             "source_days": store.source.days,
                             "albums": store.albums_cached(),
                             "last_error": store.last_error})
            return

        if path == "/next":
            # Rotate, then tell the panel which generation to fetch and how
            # many bytes it is. The panel needs no knowledge of the photo.
            generation = store.rotate()
            store.last_error = None
            self._json(200, {"generation": generation, "bytes": FRAME_BYTES,
                             "width": 800, "height": 480})
            return

        if path == "/frame.bin":
            store.ensure()
            asked = query.get("gen", [None])[0]
            try:
                generation, payload = store.get(int(asked) if asked else None)
            except (KeyError, ValueError):
                self._json(404, {"error": f"generation {asked} is no longer held"})
                return
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
            asked = query.get("gen", [None])[0]
            try:
                gen, _ = store.get(int(asked) if asked else None)
            except (KeyError, ValueError):
                # A generation that has been evicted, or one that never
                # existed. Saying so beats serving a different photo under the
                # caller's label.
                self._json(404, {"error": f"generation {asked} is no longer held"})
                return
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
    if not IMMICH_URL:
        raise SystemExit("IMMICH_URL must be set, e.g. http://immich.example.lan:2283")
    client = Immich(IMMICH_URL, _read_api_key())
    store = FrameStore(client, Source(STATE_FILE))
    Handler.store = store
    Handler.token = _read_renderer_token()

    def heartbeat() -> None:
        while True:
            _touch(HEARTBEAT)
            time.sleep(30)

    threading.Thread(target=heartbeat, daemon=True).start()

    def recount_people() -> None:
        wait = PEOPLE_RETRY_FIRST_SECONDS
        while True:
            if store.count_people():
                wait = PEOPLE_RETRY_FIRST_SECONDS
                time.sleep(PEOPLE_RECOUNT_SECONDS)
            else:
                # Back off, but never past the point where the next ordinary
                # daily count would have come round anyway.
                time.sleep(min(wait, PEOPLE_RECOUNT_SECONDS))
                wait = min(wait * 2, PEOPLE_RETRY_MAX_SECONDS)

    threading.Thread(target=recount_people, daemon=True).start()

    # Only render at start-up if there is nothing to show. A restart is not a
    # reason to consume a photo: it would advance the generation, leave the
    # panel a step behind for no reason, and on a weekly cycle mean the frame
    # rotates every time the container is rebuilt rather than every week.
    if store.current:
        LOG.info("start-up: keeping the restored frame, not rendering a new one")
    else:
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
