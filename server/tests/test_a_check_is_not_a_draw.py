"""Most wakes must cost seven seconds, not thirty-five.

A wake that draws runs about 35s: associate, /wake, fetch 48 KB, refresh the
e-paper, hold the OTA window. A wake that only asks "is there a photo for me?"
skips the fetch, the refresh AND the OTA hold -- that hold lives inside
`on_download_finished`, so no download means no hold. About 7s.

That is the whole basis of the cadence: four checks a day plus a draw every
third day is ~40s awake per day, against ~105s for drawing every eight hours.
Responsive when somebody asks for a photo, and cheaper than before.

The invariant worth defending is that a check does NOT rotate. Rendering a
photo nobody will collect burns a generation and leaves `on_panel` false until
the next draw -- which is precisely the "a newer photo is waiting" signal, so
it would then be lying on every quiet wake.
"""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import app  # noqa: E402


class _Settings(dict):
    pass


class _Store:
    """Only the parts scheduled_refresh_due touches."""

    def __init__(self, fetched_at, days=3, hour=7):
        self.fetched_at = fetched_at
        self.source = mock.Mock()
        self.source.settings = {"refresh_days": days, "refresh_hour": hour}

    scheduled_refresh_due = app.FrameStore.scheduled_refresh_due
    next_refresh_description = app.FrameStore.next_refresh_description


def _at(y, m, d, hh, mm=0):
    return dt.datetime(y, m, d, hh, mm).astimezone()


class ACheckIsNotADraw(unittest.TestCase):

    def _due(self, last, now, days=3, hour=7):
        store = _Store(last.timestamp(), days, hour)
        with mock.patch.object(app.dt, "datetime", wraps=dt.datetime) as fake:
            fake.now.return_value = now
            fake.fromtimestamp = dt.datetime.fromtimestamp
            return store.scheduled_refresh_due()

    def test_it_waits_the_configured_days(self):
        last = _at(2026, 9, 21, 7, 30)
        self.assertFalse(self._due(last, _at(2026, 9, 22, 12)), "day 1")
        self.assertFalse(self._due(last, _at(2026, 9, 23, 12)), "day 2")
        self.assertTrue(self._due(last, _at(2026, 9, 24, 12)), "day 3 is due")

    def test_it_does_not_draw_before_the_refresh_hour(self):
        """The first check AFTER 7am, never the 01:00 one."""
        last = _at(2026, 9, 21, 7, 30)
        self.assertFalse(self._due(last, _at(2026, 9, 24, 1)),
                         "01:00 on the due day is before the refresh hour")
        self.assertTrue(self._due(last, _at(2026, 9, 24, 7)),
                        "07:00 on the due day is the one")

    def test_the_schedule_cannot_drift_later_each_cycle(self):
        """Date arithmetic, not elapsed seconds.

        With `now - last >= 3 days` a draw at 18:00 pushes the next one to
        18:00 three days later, and the cycle walks around the clock until it
        happens at night. Comparing DATES keeps it anchored to the morning.
        """
        evening = _at(2026, 9, 21, 18, 0)
        self.assertTrue(
            self._due(evening, _at(2026, 9, 24, 7, 5)),
            "an evening draw must still leave the next one at the refresh "
            "hour three days later, not at the same evening time")

    def test_a_longer_cycle_is_honoured(self):
        last = _at(2026, 9, 21, 7, 30)
        self.assertFalse(self._due(last, _at(2026, 9, 26, 12), days=7))
        self.assertTrue(self._due(last, _at(2026, 9, 28, 12), days=7))

    def test_nothing_collected_yet_draws(self):
        store = _Store(0)
        with mock.patch.object(app.dt, "datetime", wraps=dt.datetime) as fake:
            fake.now.return_value = _at(2026, 9, 24, 9)
            self.assertTrue(store.scheduled_refresh_due(),
                            "a panel that has never collected should draw "
                            "rather than wait days to start the cycle")

    def test_the_wake_endpoint_reports_the_decision(self):
        """`draw` has to be in the reply, or the panel cannot obey it."""
        source = (Path(__file__).resolve().parents[1]
                  / "src" / "app.py").read_text(encoding="utf-8")
        self.assertIn('"draw": draw', source,
                      "/wake no longer tells the panel whether to draw")
        self.assertIn("last_wake_at", source,
                      "the heartbeat is gone; on a multi-day draw cycle the "
                      "fetch timestamp cannot show the panel is alive")

    def test_a_quiet_wake_does_not_rotate(self):
        """The expensive mistake: burning a photo nobody will see.

        Since 2026-09-24 a photo IS rendered between draws -- the held preview
        -- but never on a check: it renders in the background after a
        collection, and a check leaves it waiting (see the preview tests)."""
        source = (Path(__file__).resolve().parents[1]
                  / "src" / "app.py").read_text(encoding="utf-8")
        wake = source[source.index('if path == "/wake":'):]
        wake = wake[:wake.index('if path == "/status":')]
        self.assertIn("if draw and not pending:", wake,
                      "rotate() is no longer gated on drawing. A check that "
                      "rotates renders a photo nobody collects, and leaves "
                      "on_panel false until the next draw.")


class TheNextPhotoIsAPreview(unittest.TestCase):
    """After a collection the next photo is rendered and HELD for the draw.

    Davide, 2026-09-24, twice: "cannot be the same current photo as next".
    "Up next" repeated the photo on the wall until the next scheduled draw.
    Now it previews the one that will go up -- and the preview must never go
    up early, which is the difference between it and New photo now.
    """

    def _store(self, tmp):
        import threading
        store = app.FrameStore.__new__(app.FrameStore)
        store.lock = threading.Lock()
        store._render_lock = threading.RLock()
        store.source = mock.Mock()
        store.source.path = str(Path(tmp) / "source.json")
        store.current, store.fetched_generation, store.preview = 2, 2, False
        store.renders = []

        def fake_rotate():
            store.current += 1
            store.renders.append(store.current)
            return store.current
        store._rotate = fake_rotate
        return store

    def test_a_preview_is_held_and_an_asked_photo_is_not(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.render_preview()
            self.assertEqual(store.renders, [3])
            self.assertTrue(store.preview, "the rendered photo is not marked as held")
            # Something is waiting now, so a second preview is a no-op.
            store.render_preview()
            self.assertEqual(store.renders, [3])
            # New photo now replaces the preview with an ASKED-FOR photo.
            store.rotate()
            self.assertFalse(store.preview, "an asked-for photo reads as a held preview")

    def test_a_check_leaves_the_preview_but_the_draw_serves_it(self):
        source = (Path(__file__).resolve().parents[1] / "src" / "app.py").read_text(encoding="utf-8")
        wake = source[source.index('if path == "/wake":'):]
        wake = wake[:wake.index('if path == "/status":')]
        self.assertIn("asked = pending and not preview", wake)
        self.assertIn("draw = asked or scheduled or first_ever", wake,
                      "a held preview would go up at the next check")

    def test_collecting_the_newest_renders_the_next_preview(self):
        source = (Path(__file__).resolve().parents[1] / "src" / "app.py").read_text(encoding="utf-8")
        fetch = source[source.index("def note_panel_fetch"):]
        fetch = fetch[:fetch.index("def get(")]
        self.assertIn("render_preview_soon()", fetch)

if __name__ == "__main__":
    unittest.main()


def test_the_next_draw_is_a_timestamp_home_assistant_can_use(tmp_path):
    """`next_refresh_at` is the machine-readable twin of the prose schedule.

    The dashboard used to derive "Next Wake" from the last COLLECTION, which
    since the check/draw split is days old, so it read "Due Now" for ever
    (2026-09-24). The integration now exposes the heartbeat and this time
    instead; both must exist and agree with the description.
    """
    import datetime as dt
    import app

    store = app.FrameStore.__new__(app.FrameStore)
    store.source = type("S", (), {"settings": {"refresh_days": 3, "refresh_hour": 7}})()
    store.fetched_at = None
    assert store.next_refresh_at() is None

    last = dt.datetime(2026, 9, 22, 14, 47).astimezone()
    store.fetched_at = last.timestamp()
    due = dt.datetime.fromtimestamp(store.next_refresh_at()).astimezone()
    assert (due.year, due.month, due.day, due.hour, due.minute) == (2026, 9, 25, 7, 0)
    assert store.next_refresh_description() == f"{due:%a %d %b %H:%M}"


def test_the_heartbeat_survives_a_restart(tmp_path):
    """A renderer restart used to blank Last check-in until the next wake.

    Every deploy restarts the renderer, several a day, and the heartbeat was
    kept only in memory -- so Home Assistant read "unknown" and the dashboard
    "Next wake: —" for up to a whole sleep interval on a healthy frame
    (2026-09-24). It is saved beside the frame state now.
    """
    import time
    import app

    def store_at(path):
        store = app.FrameStore.__new__(app.FrameStore)
        store.source = type("S", (), {"path": str(path / "source.json")})()
        store.last_wake_at = 0.0
        return store

    first = store_at(tmp_path)
    first.note_wake()
    assert first.last_wake_at > 0

    second = store_at(tmp_path)        # a fresh process, same volume
    second._restore_heartbeat()
    assert second.last_wake_at == first.last_wake_at

    # A saved time in the future (a clock that jumped back) is refused.
    (tmp_path / "heartbeat.json").write_text('{"last_wake_at": %f}' % (time.time() + 86400))
    third = store_at(tmp_path); third._restore_heartbeat()
    assert third.last_wake_at == 0.0

    # A corrupt file costs the restored value, never the process.
    (tmp_path / "heartbeat.json").write_text("not json")
    fourth = store_at(tmp_path); fourth._restore_heartbeat()
    assert fourth.last_wake_at == 0.0
