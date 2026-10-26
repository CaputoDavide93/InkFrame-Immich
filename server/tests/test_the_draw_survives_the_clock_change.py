"""The next draw is one moment, worked out once, true across a clock change.

Found by the 2026-10-22 review, three days before the clocks went back on
Sun 25 Oct 2026. `next_refresh_at`, `next_refresh_description` and
`scheduled_refresh_due` each did their own date arithmetic on
`fromtimestamp(...).astimezone()`, which carries the FIXED offset of the last
collection. Adding days kept that offset, so a photo collected in BST and due
after the change was reported to Home Assistant as 06:00 GMT while the panel,
reading the hour, drew at 07:00 GMT. One helper now builds the due date as
local wall-clock time and takes the offset true on that date.

Also here: the settings file is written atomically, so a crash mid-write can
no longer leave half a JSON document that `load` reads as "back to Random".
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import app  # noqa: E402


def _store(fetched_at, days=3, hour=7):
    store = app.FrameStore.__new__(app.FrameStore)
    store.source = type("S", (), {"settings": {"refresh_days": days, "refresh_hour": hour}})()
    store.fetched_at = fetched_at
    return store


class _London:
    """Run the test in Europe/London, whatever the machine's zone."""

    def __enter__(self):
        self.old = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/London"
        time.tzset()

    def __exit__(self, *exc):
        if self.old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.old
        time.tzset()


UTC = dt.timezone.utc


class TheNextDrawAcrossTheClockChange(unittest.TestCase):

    def test_autumn_collected_in_bst_due_at_07_00_gmt(self):
        with _London():
            # Thu 22 Oct 2026 14:00 BST = 13:00 UTC; due Sun 25 Oct 07:00 GMT.
            store = _store(dt.datetime(2026, 10, 22, 13, 0, tzinfo=UTC).timestamp())
            due = dt.datetime.fromtimestamp(store.next_refresh_at(), UTC)
            self.assertEqual(due, dt.datetime(2026, 10, 25, 7, 0, tzinfo=UTC))
            self.assertEqual(store.next_refresh_description(), "Sun 25 Oct 07:00")

    def test_spring_collected_in_gmt_due_at_07_00_bst(self):
        with _London():
            store = _store(dt.datetime(2027, 3, 25, 13, 0, tzinfo=UTC).timestamp())
            due = dt.datetime.fromtimestamp(store.next_refresh_at(), UTC)
            self.assertEqual(due, dt.datetime(2027, 3, 28, 6, 0, tzinfo=UTC))
            self.assertEqual(store.next_refresh_description(), "Sun 28 Mar 07:00")

    def test_the_draw_happens_when_home_assistant_was_told(self):
        """The decision and the published time are the same moment."""
        with _London():
            store = _store(dt.datetime(2026, 10, 22, 13, 0, tzinfo=UTC).timestamp())
            told = store.next_refresh_at()

            def due_at(utc_hour, utc_minute=0):
                now = dt.datetime(2026, 10, 25, utc_hour, utc_minute, tzinfo=UTC).astimezone()
                with mock.patch.object(app.dt, "datetime", wraps=dt.datetime) as fake:
                    fake.now.return_value = now
                    fake.fromtimestamp = dt.datetime.fromtimestamp
                    fake.combine = dt.datetime.combine
                    return store.scheduled_refresh_due()

            self.assertFalse(due_at(6, 59), "06:59 GMT is before the refresh hour")
            self.assertTrue(due_at(7, 0), "07:00 GMT is the one")
            self.assertEqual(told, dt.datetime(2026, 10, 25, 7, 0, tzinfo=UTC).timestamp())


class TheSettingsFileIsWrittenAtomically(unittest.TestCase):

    def test_a_failed_write_keeps_the_old_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "source.json")
            src = app.Source(path)
            src.mode = "album"
            src.album = "Holidays"
            src.save()
            before = Path(path).read_text()

            src.album = "Something else"

            def half_then_die(obj, handle, *a, **k):
                handle.write('{"mode": "alb')
                raise OSError("disk full")

            with mock.patch.object(app.json, "dump", half_then_die):
                src.save()
            self.assertEqual(Path(path).read_text(), before, "the live file was never touched")
            self.assertEqual(sorted(os.listdir(d)), ["source.json"], "no temp file left behind")
            self.assertEqual(app.Source(path).album, "Holidays")

    def test_it_renames_into_place(self):
        source = (Path(__file__).resolve().parents[1] / "src" / "app.py").read_text(encoding="utf-8")
        save = source[source.index("    def save(self) -> None:"):]
        save = save[:save.index("    @staticmethod")]
        self.assertIn("os.replace(tmp, self.path)", save)
        self.assertIn("os.fsync(", save)


if __name__ == "__main__":
    unittest.main()
