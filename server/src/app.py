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
import hashlib
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
# AN OTA WINDOW THIS LONG MEANS SOMEBODY IS ABOUT TO FLASH (2026-10-22).
# The firmware holds its OTA window only after a download (the delay lives in
# `on_download_finished`), so a wake that only checks sleeps after ~7 seconds
# whatever the window says. The default is 20 seconds; nothing sets a minute or
# more except the "Prepare for update" button, which sets 300 and puts the old
# value back after the next wake. So a window at or above this makes every wake
# a drawing one, of the photo ALREADY on the glass when there is one: the
# picture does not change, the schedule does not move, and the panel stays up
# for the window.
FLASH_WINDOW_SECONDS = 60
# WAKE ON THE SCHEDULE'S CLOCK, NOT THE PANEL'S (2026-10-26).
# `sleep_seconds` used to be the bare interval, so the checks were a
# free-running timer that walked around the clock: 06:57, 12:54, 18:50,
# 00:46, 06:42. The 06:42 check was told "next draw 07:00" and slept six
# hours, so the 07:00 photo went up at about 12:40. Now every wake sleeps
# until the next SLOT: wall-clock times anchored on the draw hour (07:00,
# 13:00, 19:00, 01:00 at six hours), worked out in local time so a clock
# change moves nothing.
#
# The panel's deep-sleep clock runs FAST, about 1.1 % (measured 25-26 Oct
# 2026: six commanded hours came back as 5 h 56 min). So the sleep is
# stretched by RTC_FAST_ALLOWANCE and a margin is added on top, to land just
# after a slot rather than just before it. A wake that still lands early is
# the cheap failure: the next slot is minutes away, so it naps until then
# instead of sleeping a whole interval past the draw.
CHECK_MARGIN_SECONDS = 60
RTC_FAST_ALLOWANCE = 0.015
MIN_SLEEP_SECONDS = 60
HEARTBEAT =os.environ.get("HEARTBEAT_FILE", "/tmp/immichframe-heartbeat")
LAST_OK = os.environ.get("LAST_OK_FILE", "/tmp/immichframe-render-ok")


def _wall_clock(day: dt.date, minute: int) -> dt.datetime:
    """`minute` past midnight on `day`, local wall clock, with the offset true
    on that date. A time the spring change skips moves forward an hour."""
    return dt.datetime.combine(day, dt.time(minute // 60, minute % 60)).astimezone()


def sleep_until_next_check(now: dt.datetime, interval_h: float, refresh_hour: int,
                           due: dt.datetime | None = None) -> int:
    """Seconds the panel should sleep so it wakes just after the next slot.

    `now` is aware local time. Under a day, the slots are every `interval_h`
    from `refresh_hour`, so the draw hour is always one of them and the
    next slot is never further than the interval (plus an hour on the night
    the clocks go back). From a day up, the slots are `refresh_hour` each day:
    the latest within the interval, but never past the draw that is `due`.
    """
    interval_s = max(1.0, float(interval_h)) * 3600
    step = max(1, round(float(interval_h) * 60))
    anchor = (int(refresh_hour) % 24) * 60
    minutes = range(anchor % step, 1440, step) if step < 1440 else [anchor]
    today = now.date()
    slots = sorted({_wall_clock(today + dt.timedelta(days=d), m)
                    for d in range(-1, int(interval_s // 86400) + 3) for m in minutes})
    slots = [s for s in slots if s > now]
    if step < 1440:
        chosen = slots[0]
    else:
        within = [s for s in slots if (s - now).total_seconds() <= interval_s]
        chosen = within[-1] if within else slots[0]
        if due is not None:
            draw = next((s for s in slots if s >= due), None)
            if draw is not None and draw < chosen:
                chosen = draw
    gap = (chosen - now).total_seconds()
    sleep = gap * (1 + RTC_FAST_ALLOWANCE) + CHECK_MARGIN_SECONDS
    # A grid that does not divide the day can leave a long gap overnight; the
    # interval (plus the clock-change hour) stays the ceiling, and the wake
    # after that one is back on the grid.
    ceiling = (interval_s + 3600) * (1 + RTC_FAST_ALLOWANCE) + CHECK_MARGIN_SECONDS
    return int(max(MIN_SLEEP_SECONDS, min(sleep, ceiling)))


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
    # Local hour for the scheduled draw, and the anchor of the check slots:
    # /wake sleeps the panel until the next slot, so a check lands just after
    # this hour on the draw day. Still "the first check at or after this
    # hour": a panel that wakes late draws late rather than not at all.
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
        """Write the source and settings ATOMICALLY (2026-10-22 review).

        This wrote the live file in place, so a crash or a full volume
        mid-write left half a JSON document, and `load` then fell back to
        Random and the defaults: the household's choice gone without a word.
        A temporary file beside it, flushed and fsynced, then renamed over
        it, means the file on disk is always the old one or the new one.
        """
        tmp = f"{self.path}.tmp"
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(tmp, "w") as handle:
                json.dump({"mode": self.mode, "person": self.person,
                           "people": self.people, "album": self.album,
                           "query": self.query, "days": self.days,
                           "settings": self.settings}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except OSError as exc:
            LOG.warning("could not persist source: %s", exc)
            try:
                os.unlink(tmp)
            except OSError:
                pass

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
    """Holds current, previous, acknowledged, and one downloading frame.

    Keeping the previous generation matters: the panel fetches the frame in
    strips, and a rotation landing between strip 3 and strip 4 would otherwise
    paste half of one photo onto half of another. A panel mid-fetch keeps
    reading the generation it started with.
    """

    def __init__(self, client: Immich, source: Source) -> None:
        self.client = client
        self.source = source
        # Explicit display acknowledgement once supported by the panel; legacy
        # firmware acknowledges a complete download. Keep these field names stable.
        self.ack_capable = False
        self._download_ranges = {}
        self.fetched_generation = 0
        # The heartbeat. On a multi-day draw cycle the FETCH timestamp cannot
        # tell you the panel is alive -- three days without one is normal --
        # so the check itself has to be the evidence. 0 means "the panel has
        # never called".
        #
        # SAVED TO DISK since 2026-09-24. It used to live only in memory, on
        # the grounds that 0 after a restart was "honest rather than stale".
        # But a saved wake time is not stale: it records a real event and its
        # AGE says how old it is. Keeping it in memory meant every renderer
        # restart -- every deploy, several a day -- blanked Home Assistant's
        # Last check-in and the dashboard's Next wake for up to a whole sleep
        # interval, on a frame that was fine. The draw time was always
        # persisted (the frame sidecar's `_fetched_at`); the heartbeat now is too.
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
        # NEXT IS A PREVIEW (2026-09-24). After the panel collects the newest
        # photo, the next one is rendered straight away and HELD for the
        # scheduled draw, so Home Assistant's "Up next" shows the photo that
        # will actually go up on Sunday instead of repeating the one already
        # on the wall. `preview` is what separates that held photo from one
        # somebody ASKED for with New photo now: an asked-for photo goes up at
        # the next check, a preview only at the scheduled draw. Renders are
        # serialised so a preview can never overwrite an asked-for photo.
        self.preview = False
        self._render_lock = threading.RLock()
        self.generations: dict[int, bytes] = {}
        # Encoded once per generation, not once per request. The panel fetches
        # a frame a handful of times a week, but /preview.png and the Home
        # Assistant sensor poll far more often, and re-encoding a PNG of
        # dithered noise is pure waste.
        self.encoded: dict[tuple[int, str], bytes] = {}
        self.meta: dict[int, dict] = {}
        self.current = 0
        self.next_generation = 1
        self.downloading_generation = 0
        self.recent: deque[str] = deque(maxlen=RECENT_MEMORY)
        self.last_error: str | None = None
        # Last, because it restores the state everything above declares.
        self._restore()
        self._restore_protocol()
        self._restore_heartbeat()
        self._restore_recent()

    # ── surviving a restart ───────────────────────────────────────────────
    # The state file has always held the source and the settings. It did not
    # hold the picture, so a container restart left generation 0 and every
    # image route answering 500 until something rendered successfully. With a
    # narrow source that has run dry -- an album with nothing in it yet -- that
    # is indefinitely, and the panel's next wake gets nothing at all.

    def _frame_path(self, slot: str = "frame") -> str:
        """Fixed latest, panel, and download slots; never a file per generation."""
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
        if not isinstance(meta, dict):
            meta = {}
        if meta.get("_payload_sha256") and meta["_payload_sha256"] != hashlib.sha256(payload).hexdigest():
            LOG.warning("saved %s frame does not match its details; ignoring", slot)
            return None
        return payload, meta

    def _recent_path(self) -> str:
        return os.path.join(os.path.dirname(self.source.path) or "/data", "recent.json")

    def _save_recent(self, ids: list[str]) -> None:
        """Remember what has been shown, across restarts.

        It lived only in memory, so every renderer restart -- every deploy,
        several a day -- forgot it, and the photos just shown were eligible
        again at once. With the album cycling properly that forgetting is
        what would still bring repeats back (2026-09-25).
        """
        path = self._recent_path()
        try:
            with open(path + ".tmp", "w") as handle:
                json.dump(ids, handle)
            os.replace(path + ".tmp", path)
        except OSError as exc:
            LOG.warning("could not save the recently shown list: %s", exc)

    def _restore_recent(self) -> None:
        try:
            with open(self._recent_path()) as handle:
                ids = json.load(handle)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            LOG.warning("could not restore the recently shown list: %s", exc)
            return
        if isinstance(ids, list):
            self.recent.extend(str(i) for i in ids if isinstance(i, str))

    def _restore_protocol(self) -> None:
        try:
            with open(os.path.join(os.path.dirname(self.source.path) or "/data", "panel-protocol.json")) as handle:
                self.ack_capable = json.load(handle).get("ack_capable") is True
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError) as exc:
            LOG.warning("could not restore panel protocol: %s", exc)

    def note_ack_capable(self) -> None:
        """A valid ACK opts this renderer into explicit ACKs, across restarts.

        Delete /data/panel-protocol.json to return to the legacy fallback
        (for example after reflashing pre-ACK firmware).
        """
        with self.lock:
            self.ack_capable = True
            self._download_ranges = {}
            path = os.path.join(os.path.dirname(self.source.path) or "/data", "panel-protocol.json")
            with open(path + ".tmp", "w") as handle:
                json.dump({"ack_capable": True}, handle)
            os.replace(path + ".tmp", path)

    def note_download(self, generation: int, offset: int, length: int) -> None:
        """Legacy firmware acknowledges only a completely written framebuffer."""
        with self.lock:
            if getattr(self, "ack_capable", False) or generation <= self.fetched_generation:
                return
            # A single pending panel download is retained, like the disk slot.
            ranges = getattr(self, "_download_ranges", {}).get(generation, [])
            ranges = sorted(ranges + [(offset, offset + length)])
            merged = []
            for start, end in ranges:
                if merged and start <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], end))
                else:
                    merged.append((start, end))
            self._download_ranges = {generation: merged}
            complete = merged == [(0, FRAME_BYTES)]
        if complete:
            self.note_panel_fetch(generation, legacy=True)

    def _heartbeat_path(self) -> str:
        return os.path.join(os.path.dirname(self.source.path) or "/data", "heartbeat.json")

    def note_wake(self) -> None:
        """Record a wake, in memory and on disk. A failed write costs only the
        restart case, never the wake: /wake must answer the panel regardless."""
        self.last_wake_at = time.time()
        path = self._heartbeat_path()
        try:
            with open(path + ".tmp", "w") as handle:
                json.dump({"last_wake_at": self.last_wake_at}, handle)
            os.replace(path + ".tmp", path)
        except OSError as exc:
            LOG.warning("could not save the heartbeat: %s", exc)

    def _restore_heartbeat(self) -> None:
        try:
            with open(self._heartbeat_path()) as handle:
                value = float(json.load(handle).get("last_wake_at") or 0)
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            LOG.warning("could not restore the heartbeat: %s", exc)
            return
        # Never a time in the future: a clock that jumped back must not make
        # the panel look like it checked in tomorrow.
        if 0 < value <= time.time():
            self.last_wake_at = value

    def _restore(self) -> None:
        """Restore stable identities, migrating unnumbered legacy snapshots."""
        try:
            slots = {slot: saved for slot in ("panel", "frame", "download")
                     if (saved := self._read_slot(slot)) is not None}
            self.next_generation = max(
                [1] + [value for _, meta in slots.values()
                       for value in (meta.get("_next_generation"),
                                     (meta.get("_generation") + 1
                                      if type(meta.get("_generation")) is int else None))
                       if type(value) is int and value > 0])
            self.downloading_generation = 0
            for slot, (payload, meta) in slots.items():
                generation = meta.get("_generation")
                if type(generation) is not int or generation <= 0:
                    same = (slot == "frame" and "panel" in slots
                            and payload == slots["panel"][0]
                            and meta.get("asset_id") == slots["panel"][1].get("asset_id"))
                    generation = (self.fetched_generation if same else
                                  max(self.next_generation, int(time.time())))
                    self.next_generation = max(self.next_generation, generation + 1)
                    meta = dict(meta, _generation=generation)
                    self._persist(payload, meta, slot=slot)
                if slot == "download" and generation <= self.fetched_generation:
                    self._clear_download()
                    continue
                self.generations[generation] = payload
                self.meta[generation] = {k: v for k, v in meta.items() if not k.startswith("_")}
                if slot == "panel" or (slot == "frame" and "panel" not in slots
                                       and meta.get("_was_on_panel")):
                    self.fetched_generation = generation
                    self.fetched_at = meta.get("_fetched_at")
                if slot == "frame":
                    self.current = generation
                    self.preview = bool(meta.get("_preview")) and generation != self.fetched_generation
                elif slot == "panel" and "frame" not in slots:
                    self.current = generation
                elif slot == "download":
                    self.downloading_generation = generation
        except Exception as exc:  # noqa: BLE001 - a bad file must not stop the frame
            LOG.warning("could not restore the saved frames: %s", exc)

    def _persist(self, payload: bytes, meta: dict, slot: str = "frame") -> bool:
        try:
            meta = dict(meta)
            generation = meta.get("_generation", self.fetched_generation if slot == "panel" else self.current)
            if generation:
                meta["_generation"] = generation
                meta["_next_generation"] = max(getattr(self, "next_generation", 1), generation + 1)
                meta["_payload_sha256"] = hashlib.sha256(payload).hexdigest()
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
            return True
        except OSError as exc:
            LOG.warning("could not persist the %s frame: %s", slot, exc)
            return False

    def _clear_download(self) -> None:
        self.downloading_generation = 0
        for suffix in ("", ".json"):
            try:
                os.remove(self._frame_path("download") + suffix)
            except FileNotFoundError:
                pass
            except OSError as exc:
                LOG.warning("could not remove the downloaded frame: %s", exc)

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
    def _refresh_due_at(self) -> dt.datetime | None:
        """The moment the next DRAW is due, in local time; None before the first.

        THE ONE PLACE this is worked out (2026-10-22 review). It used to be
        done three times, each on `fromtimestamp(...).astimezone()`, which
        carries the FIXED offset of the last collection. Adding days kept that
        offset across a clock change, so after 25 Oct 2026 "07:00" meant 06:00
        GMT to Home Assistant while the panel drew at 07:00 GMT. Now the date
        and hour are wall-clock (naive local) and the offset is the one true
        on the due date.
        """
        if not self.fetched_at:
            return None
        cfg = self.source.settings
        days = int(cfg.get("refresh_days", 3))
        hour = int(cfg.get("refresh_hour", 7))
        last = dt.datetime.fromtimestamp(self.fetched_at)  # naive local wall clock
        due = dt.datetime.combine(last.date() + dt.timedelta(days=days), dt.time(hour))
        return due.astimezone()  # the zone's offset ON that date

    def scheduled_refresh_due(self) -> bool:
        """Is this the first check at or after the refresh hour, on the day
        the picture is due to change?

        Date arithmetic, not elapsed seconds, and deliberately so. "Every
        three days at 7am" against a clock that drifts (deep sleep is not
        precise, and the panel wakes on its own timer) has to mean "the first
        check on or after that morning", or the draw slides a little later
        every cycle until it happens at night. A check on a LATER day still
        waits for the hour, so a missed morning does not become a 3am draw.
        """
        hour = int(self.source.settings.get("refresh_hour", 7))
        now = dt.datetime.now().astimezone()
        if now.hour < hour:
            return False
        due = self._refresh_due_at()
        if due is None:
            # Never collected anything. /wake's `first_ever` covers generation
            # 0; past that, draw rather than wait days to start the cycle.
            return True
        return now >= due

    def next_refresh_at(self) -> float | None:
        """When the next DRAW is due, as a timestamp; None before the first one.

        The same moment `scheduled_refresh_due` waits for, as a number Home
        Assistant can use. Until 2026-09-24 the only machine-readable times
        were the last collection and the last wake, and the dashboard derived
        "Next Wake" from the collection -- which since the check/draw split is
        one to three days old, so it read "Due Now" permanently.
        """
        due = self._refresh_due_at()
        return due.timestamp() if due else None

    def next_refresh_description(self) -> str:
        """For the log line on a check, so a quiet wake still says something."""
        due = self._refresh_due_at()
        if due is None:
            return "unknown (nothing collected yet)"
        return f"{due:%a %d %b %H:%M}"

    def next_sleep_seconds(self, drawing: bool = False,
                           now: dt.datetime | None = None) -> int:
        """The `sleep_seconds` for this wake: until the next slot.

        A DRAWING wake has not been collected yet when /wake answers, so
        `fetched_at` still points at the last draw and the due date it gives
        is today's. Plan from the draw happening now instead, the same date
        arithmetic `_refresh_due_at` will do once the panel acknowledges it.
        """
        cfg = self.source.settings
        now = now or dt.datetime.now().astimezone()
        hour = int(cfg.get("refresh_hour", 7))
        if drawing:
            days = int(cfg.get("refresh_days", 3))
            due = dt.datetime.combine(now.date() + dt.timedelta(days=days),
                                      dt.time(hour)).astimezone()
        else:
            due = self._refresh_due_at()
        return sleep_until_next_check(now, float(cfg.get("sleep_hours", 6)), hour, due)

    def rotate(self, preview: bool = False) -> int:
        """Render the next photo; `preview` holds it for the scheduled draw.

        Serialised: an asked-for render and a preview render never overlap,
        so whichever finishes last is the one its flag describes.
        """
        with self._render_lock:
            generation = self._rotate()
            with self.lock:
                if self.current == generation:
                    self.preview = preview
            meta_path = self._frame_path("frame") + ".json"
            try:
                with open(meta_path) as handle:
                    saved = json.load(handle)
                saved["_preview"] = preview
                with open(meta_path + ".tmp", "w") as handle:
                    json.dump(saved, handle)
                os.replace(meta_path + ".tmp", meta_path)
            except (OSError, ValueError) as exc:
                LOG.warning("could not record the preview flag: %s", exc)
            return generation

    def _rotate(self) -> int:
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

        # ANY ACCEPTABLE PHOTO, NOT ALWAYS THE CALMEST (2026-09-25).
        # Max busyness is the quality gate; below it, every photo is good
        # enough for the panel. This used to take the calmest candidate every
        # time, and with twenty candidates scored from a 36-photo album that
        # is more than half the album per draw -- so the same three or four
        # calmest photos won again and again. Davide: "I added 39 photos but
        # only 3/4 are displayed". Now the pick is random among the
        # acceptable ones; the calmest is only the fallback when every
        # candidate is too busy.
        import random as _random
        scored.sort(key=lambda row: row[0])
        acceptable = [row for row in scored if row[0] <= max_busyness]
        busyness, chosen, img = _random.choice(acceptable) if acceptable else scored[0]
        rejected = sum(1 for row in scored if row[0] > max_busyness)
        if not acceptable:
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
            generation = max(self.current + 1, self.next_generation)
            meta = {
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
            saved = dict(meta, _generation=generation, _was_on_panel=False,
                         _fetched_at=None)
            if not self._persist(payload, saved):
                raise OSError("could not save the rendered generation")
            self.generations[generation] = payload
            self.meta[generation] = meta
            # Keep the new frame, the one before it, and whatever the panel is
            # actually displaying. That last one is the point: press Next photo
            # three times before a wake and the panel is three generations
            # behind, so evicting by age alone would throw away the only copy
            # of the picture hanging on the wall.
            keep = {generation, generation - 1, self.fetched_generation,
                    self.downloading_generation}
            for stale in [g for g in self.generations if g not in keep]:
                self.generations.pop(stale, None)
                self.meta.pop(stale, None)
            for key in [k for k in self.encoded if k[0] not in keep]:
                self.encoded.pop(key, None)
            self.current = generation
            self.next_generation = generation + 1
            self.recent.append(asset.id)
            recent_snapshot = list(self.recent)
        self._save_recent(recent_snapshot)
        LOG.info("gen %d: %s busyness %.1f (of %d scored) in %.2fs",
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

    def note_panel_fetch(self, generation: int, *, legacy: bool = False) -> None:
        """Record display, with complete-download compatibility for old firmware."""
        with self.lock:
            if legacy and getattr(self, "ack_capable", False):
                return
            if generation < self.fetched_generation:
                raise KeyError(generation)
            payload = self.generations[generation]
            if generation == self.fetched_generation:
                return
            fetched_at = time.time()
            saved = dict(self.meta.get(generation, {}))
            saved["_generation"] = generation
            saved["_was_on_panel"] = True
            saved["_fetched_at"] = fetched_at
            if not self._persist(payload, saved, slot="panel"):
                raise OSError("could not save the acknowledged generation")
            self.fetched_generation = generation
            self.fetched_at = fetched_at
            if getattr(self, "downloading_generation", 0) <= generation:
                self._clear_download()
            collected_newest = generation == self.current
            if collected_newest:
                self.preview = False
        if collected_newest:
            self.render_preview_soon()

    def get(self, generation: int | None, *, pin: bool = False) -> tuple[int, bytes]:
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
            if pin and generation > self.fetched_generation:
                if generation != getattr(self, "downloading_generation", 0):
                    saved = dict(self.meta[generation], _generation=generation)
                    if not self._persist(self.generations[generation], saved, slot="download"):
                        raise OSError("could not save the downloaded generation")
                self.downloading_generation = generation
            return generation, self.generations[generation]

    def ensure(self) -> None:
        with self.lock:
            has_frame = self.current in self.generations
        if not has_frame:
            self.rotate()

    def render_preview(self) -> None:
        """Render the photo for the next scheduled draw, if none is waiting.

        Only when the panel already has the newest photo: a waiting photo,
        preview or asked-for, is never replaced by this. Runs in the
        background so a collection never waits on Immich.
        """
        with self._render_lock:
            with self.lock:
                nothing_waiting = (self.current != 0
                                   and self.fetched_generation == self.current)
            if not nothing_waiting:
                return
            try:
                generation = self.rotate(preview=True)
                LOG.info("preview: gen %d held for the next scheduled draw", generation)
            except Exception as exc:  # noqa: BLE001 - a failed preview costs the preview only
                LOG.warning("preview render failed: %s", exc)

    def render_preview_soon(self) -> None:
        threading.Thread(target=self.render_preview, daemon=True).start()


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

    def _legacy_ack(self, record) -> None:
        """Count a completed panel download as the draw, for pre-ACK firmware.

        Called only AFTER the 200 is written, so a failure here is logged and
        never answered: a second response on the same socket corrupts it.
        """
        try:
            record()
        except (KeyError, OSError) as exc:
            LOG.warning("legacy display acknowledgement not recorded: %s", exc)
            self.store.last_error = f"{type(exc).__name__}: {exc}"

    def _authorised(self) -> bool:
        """Accept a bearer header, never a query token that logs in proxies."""
        supplied = self.headers.get("Authorization", "")
        if supplied.lower().startswith("bearer "):
            supplied = supplied[7:].strip()
        else:
            supplied = self.headers.get("X-InkFrame-Token", "")
        return bool(supplied) and hmac.compare_digest(supplied, self.token)

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        self._handle_request("GET")

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        self._handle_request("POST")

    def _handle_request(self, method: str) -> None:
        url = urlparse(self.path)
        query = parse_qs(url.query, keep_blank_values=True)
        # Docker needs an unauthenticated liveness probe, but every endpoint
        # that reveals images/state or changes the frame requires the bearer.
        if url.path != "/healthz" and not self._authorised():
            self._json(401, {"error": "authorization required"})
            return
        try:
            if url.path == "/frame/ack":
                if method != "POST":
                    self._json(405, {"error": "display acknowledgement requires POST"})
                    return
                values = query.get("gen", [])
                try:
                    if (len(values) != 1 or not values[0].isascii()
                            or not values[0].isdecimal()):
                        raise ValueError("one positive generation is required")
                    generation = int(values[0])
                    if generation <= 0:
                        raise ValueError("one positive generation is required")
                except ValueError:
                    self._json(400, {"error": "one positive generation is required"})
                    return
                try:
                    self.store.note_panel_fetch(generation)
                except KeyError:
                    self._json(404, {"error": f"generation {generation} is no longer held"})
                    return
                # Opt in to strict ACKs only on a valid, recorded ACK: a stray
                # or malformed POST must not switch off the legacy fallback
                # the current firmware depends on.
                try:
                    self.store.note_ack_capable()
                except OSError as exc:
                    LOG.warning("could not persist the ACK opt-in: %s", exc)
                self._json(200, {"generation": generation})
            else:
                self._route(url.path, query)
        except Exception as exc:  # noqa: BLE001 - any failure becomes a 500, never a crash
            LOG.exception("request failed: %s", self.path)
            self.store.last_error = f"{type(exc).__name__}: {exc}"
            self._json(500, {"error": str(exc)})

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
            store.note_wake()
            cfg = store.source.settings
            with store.lock:
                pending = (store.current != 0
                           and store.fetched_generation != store.current)
                preview = pending and store.preview
            first_ever = store.current == 0
            scheduled = store.scheduled_refresh_due()
            asked = pending and not preview

            # A photo somebody ASKED for outranks the schedule and is never
            # rotated past: it is delivered before a new one is made, which is
            # the whole reason /wake and /next are different endpoints. A
            # PREVIEW is waiting too, but for the schedule: a check leaves it.
            draw = asked or scheduled or first_ever
            flashing = int(cfg["ota_window_seconds"]) >= FLASH_WINDOW_SECONDS
            if flashing and not draw:
                # Somebody is waiting to flash, and only a draw holds the OTA
                # window. Redraw what the panel already shows, so nothing on
                # the wall or in the schedule moves: the acknowledgement of a
                # generation already acknowledged changes nothing.
                with store.lock:
                    shown = store.fetched_generation
                    held = shown in store.generations
                generation = shown if held else store.current
                LOG.info("wake: OTA window %ss asked for; redrawing gen %d so the "
                         "panel holds it", cfg["ota_window_seconds"], generation)
                self._json(200, {"generation": generation, "bytes": FRAME_BYTES,
                                 "draw": True,
                                 "sleep_seconds": store.next_sleep_seconds(),
                                 "ota_window_seconds": int(cfg["ota_window_seconds"])})
                return
            if draw and not pending:
                generation = store.rotate()
                LOG.info("wake: drawing gen %d (%s)", generation,
                         "scheduled refresh" if scheduled else "first frame")
            elif draw:
                generation = store.current
                LOG.info("wake: gen %d %s, serving it", generation,
                         "was asked for and not yet collected" if asked
                         else "is the held preview and the draw is due")
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
                             "sleep_seconds": store.next_sleep_seconds(drawing=draw),
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
                             # The waiting photo is held for the scheduled draw,
                             # not asked for: it goes up at next_refresh_at.
                             "next_is_preview": bool(store.preview and not on_panel),
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
            # CHANGE THE NEXT PHOTO, NOT THE PHOTO NOW (2026-09-25).
            #
            # By default this renders a different photo and HOLDS it for the
            # scheduled draw, exactly like the preview made after each draw:
            # the frame still changes on its schedule, with this photo instead.
            # It used to render an ASKED-FOR photo, which the next check (within
            # hours) delivers -- a redraw nobody meant, from a button pressed to
            # see what else the album had.
            #
            # `?now=1` keeps the old meaning for anyone who wants it: the next
            # check draws it.
            now = query.get("now", ["0"])[0] in ("1", "true", "yes")
            generation = store.rotate(preview=not now)
            store.last_error = None
            LOG.info("next: gen %d %s", generation,
                     "asked for, the next check draws it" if now
                     else "held for the next scheduled draw")
            self._json(200, {"generation": generation, "bytes": FRAME_BYTES,
                             "width": 800, "height": 480,
                             "held": not now})
            return

        if path == "/frame.bin":
            store.ensure()
            asked = query.get("gen", [None])[0]
            try:
                generation, payload = store.get(int(asked) if asked else None, pin=True)
            except (KeyError, ValueError):
                self._json(404, {"error": f"generation {asked} is no longer held"})
                return
            offset = int(query.get("offset", ["0"])[0])
            length = int(query.get("len", [str(FRAME_BYTES)])[0])
            if offset < 0 or offset > FRAME_BYTES:
                self._json(416, {"error": "offset out of range"})
                return
            chunk = payload[offset:offset + length]
            self._send(200, chunk, "application/octet-stream",
                       {"X-Frame-Generation": str(generation),
                        "X-Frame-Total": str(FRAME_BYTES)})
            self._legacy_ack(lambda: store.note_download(generation, offset, len(chunk)))
            return

        if path in ("/frame.png", "/frame.bmp", "/preview.png"):
            store.ensure()
            asked = query.get("gen", [None])[0]
            try:
                gen, _ = store.get(int(asked) if asked else None, pin=path != "/preview.png")
            except (KeyError, ValueError):
                # A generation that has been evicted, or one that never
                # existed. Saying so beats serving a different photo under the
                # caller's label.
                self._json(404, {"error": f"generation {asked} is no longer held"})
                return
            fmt = "bmp" if path == "/frame.bmp" else "png"
            body = store.encode(gen, fmt)
            self._send(200, body,
                       "image/bmp" if fmt == "bmp" else "image/png",
                       {"Cache-Control": "no-store",
                        "X-Frame-Generation": str(gen)})
            if path == "/frame.bmp":
                # The firmware on the panel before the ACK firmware fetches
                # exactly /frame.bmp and never POSTs /frame/ack. One complete
                # body, so the finished write IS the complete download. Inert
                # once any valid ACK has been recorded (note_panel_fetch).
                self._legacy_ack(lambda: store.note_panel_fetch(gen, legacy=True))
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
        # If the panel already has the newest photo, hold the next one now,
        # so "Up next" is a preview from the first minute. A restart that
        # restored a waiting photo (preview or asked-for) makes this a no-op,
        # so deploys do not burn photos.
        store.render_preview_soon()
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
