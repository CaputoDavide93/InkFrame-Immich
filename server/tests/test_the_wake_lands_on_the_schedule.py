"""The panel wakes on the schedule's clock, not its own.

Found 26 Oct 2026. The renderer answered every `/wake` with the bare sleep
interval, so the check-ins were a free-running timer that drifted around the
clock: 06:57, 12:54, 18:50, 00:46, 06:42. Each "six hours" came back about
3 min 55 s early, because the ESP32-C3's deep-sleep clock runs about 1.1 %
fast. On 26 Oct the 06:42 check was told "nothing new, next draw Mon 26 Oct
07:00" and went back to sleep for six hours, so the 07:00 photo went up at
about 12:40.

`sleep_seconds` is now "until the next slot". Slots are wall-clock times
anchored on the draw hour (07:00, 13:00, 19:00, 01:00 at a 6 h interval), with
a margin so the panel lands just AFTER a slot, never just before it. A panel
that still lands early is sent back to bed for a minute or two, never for a
whole interval. The firmware already sleeps for whatever `sleep_seconds` says,
so none of this needs a flash.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import app  # noqa: E402

UTC = dt.timezone.utc
# Measured from the renderer's log, 25-26 Oct 2026: six commanded hours came
# back as 5 h 56 min 5 s between checks, about 7 s of which is the wake itself.
MEASURED_FAST = 0.011
CHECK_AWAKE_S = 7


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


def _at(y, mo, d, h, mi=0, s=0):
    """A UTC instant, as the aware local time the renderer works in."""
    return dt.datetime(y, mo, d, h, mi, s, tzinfo=UTC).astimezone()


def _local_due(y, mo, d, hour=7):
    return dt.datetime(y, mo, d, hour).astimezone()


def _lands(now, sleep_s):
    return (now + dt.timedelta(seconds=sleep_s)).astimezone()


def _lands_on_this_clock(now, sleep_s):
    """Where the real panel lands: its clock runs fast, so over days the
    allowance for that is tens of minutes, and only the drift cancels it."""
    return (now + dt.timedelta(seconds=sleep_s * (1 - MEASURED_FAST))).astimezone()


class TheMorningOfTheBug(unittest.TestCase):

    def test_the_0642_check_comes_back_for_the_0700_draw(self):
        with _London():
            now = _at(2026, 10, 26, 6, 42, 38)  # GMT, so UTC == local
            sleep = app.sleep_until_next_check(now, 6, 7, _local_due(2026, 10, 26))
            lands = _lands(now, sleep)
            self.assertLess(sleep, 30 * 60, "not another six hours")
            self.assertGreaterEqual(lands, _at(2026, 10, 26, 7, 0, 30),
                                    "lands after 07:00, with room for a fast clock")
            self.assertLessEqual(lands, _at(2026, 10, 26, 7, 3))

    def test_a_drawing_wake_sleeps_to_the_next_slot(self):
        """The draw is due now: this wake draws, and the next one is 13:00."""
        with _London():
            now = _at(2026, 10, 26, 7, 1, 10)
            sleep = app.sleep_until_next_check(now, 6, 7, _local_due(2026, 10, 29))
            lands = _lands(now, sleep)
            self.assertGreaterEqual(lands, _at(2026, 10, 26, 13, 0, 30))
            self.assertLessEqual(lands, _at(2026, 10, 26, 13, 8))

    def test_a_check_a_moment_early_is_a_short_nap_not_a_whole_interval(self):
        with _London():
            now = _at(2026, 10, 26, 6, 59, 50)
            sleep = app.sleep_until_next_check(now, 6, 7, _local_due(2026, 10, 26))
            self.assertGreaterEqual(sleep, app.MIN_SLEEP_SECONDS)
            self.assertLessEqual(sleep, 3 * 60)
            self.assertGreater(_lands(now, sleep), _at(2026, 10, 26, 7, 0))

    def test_it_never_sleeps_less_than_the_floor(self):
        with _London():
            now = _at(2026, 10, 26, 6, 59, 59)
            sleep = app.sleep_until_next_check(now, 6, 7, None)
            self.assertGreaterEqual(sleep, app.MIN_SLEEP_SECONDS)


class AFastClockConvergesOnTheGrid(unittest.TestCase):

    def test_from_the_real_drift_every_check_lands_just_after_a_slot(self):
        """Replay the live drift: start at the 06:42 wake and let a clock
        1.1 % fast run for two days. Every wake after the first lands within
        ten minutes after 01:00, 07:00, 13:00 or 19:00, and the 07:00 draw
        happens at 07:00, not 12:40."""
        with _London():
            now = _at(2026, 10, 26, 6, 42, 38)
            landed = []
            for _ in range(9):
                sleep = app.sleep_until_next_check(now, 6, 7, _local_due(2026, 10, 29))
                real = sleep * (1 - MEASURED_FAST) + CHECK_AWAKE_S
                now = (now + dt.timedelta(seconds=real)).astimezone()
                landed.append(now)
            for when in landed:
                self.assertIn(when.hour, (1, 7, 13, 19), f"{when:%a %H:%M:%S}")
                self.assertLess(when.minute, 10, f"{when:%a %H:%M:%S}")
            self.assertEqual(landed[0].hour, 7)

    def test_a_clock_that_still_lands_early_gets_a_second_chance(self):
        """If a colder night makes the clock faster than the allowance, the
        early wake is followed by a nap to the slot, not a whole interval."""
        with _London():
            now = _at(2026, 10, 26, 1, 2)
            sleep = app.sleep_until_next_check(now, 6, 7, _local_due(2026, 10, 26))
            early = (now + dt.timedelta(seconds=sleep * (1 - 0.04))).astimezone()
            self.assertLess(early, _at(2026, 10, 26, 7, 0), "the premise: it landed early")
            again = app.sleep_until_next_check(early, 6, 7, _local_due(2026, 10, 26))
            self.assertLess(again, 20 * 60)
            self.assertGreater(_lands(early, again), _at(2026, 10, 26, 7, 0))


class TheClockChange(unittest.TestCase):

    def test_autumn_the_morning_slot_is_0700_gmt(self):
        """Sun 25 Oct 2026, 02:00 BST becomes 01:00 GMT. The wake the log
        shows at 06:57 GMT goes to 07:00 GMT, three minutes, not six hours."""
        with _London():
            now = _at(2026, 10, 25, 6, 57, 23)
            sleep = app.sleep_until_next_check(now, 6, 7, _local_due(2026, 10, 26))
            lands = _lands(now, sleep)
            self.assertGreaterEqual(lands, _at(2026, 10, 25, 7, 0))
            self.assertLessEqual(lands, _at(2026, 10, 25, 7, 3))

    def test_autumn_the_long_night_still_reaches_0700(self):
        """01:30 BST on the change night: the 01:00 slot has gone and the
        next is 07:00 GMT, six and a half real hours away. Still one sleep."""
        with _London():
            now = _at(2026, 10, 25, 0, 30)  # 01:30 BST
            sleep = app.sleep_until_next_check(now, 6, 7, _local_due(2026, 10, 25))
            lands = _lands(now, sleep)
            self.assertGreaterEqual(lands, _at(2026, 10, 25, 7, 0))
            self.assertLessEqual(lands, _at(2026, 10, 25, 7, 10))

    def test_spring_the_morning_slot_is_0700_bst(self):
        """Sun 28 Mar 2027, 01:00 GMT becomes 02:00 BST. 07:00 BST is
        06:00 UTC; a slot computed as a fixed offset would land at 08:00."""
        with _London():
            now = _at(2027, 3, 28, 1, 30)  # 02:30 BST
            sleep = app.sleep_until_next_check(now, 6, 7, _local_due(2027, 3, 28))
            lands = _lands(now, sleep)
            self.assertGreaterEqual(lands, _at(2027, 3, 28, 6, 0))
            self.assertLessEqual(lands, _at(2027, 3, 28, 6, 10))

    def test_spring_the_slot_that_does_not_exist_is_still_a_sane_sleep(self):
        """01:00 does not exist on 28 Mar 2027. The evening before must still
        get a sleep no longer than the interval allows."""
        with _London():
            now = _at(2027, 3, 27, 19, 1)
            sleep = app.sleep_until_next_check(now, 6, 7, _local_due(2027, 3, 29))
            self.assertGreaterEqual(sleep, app.MIN_SLEEP_SECONDS)
            self.assertLessEqual(sleep, 7 * 3600 + 15 * 60)
            # And the following morning's 07:00 BST is reached from there.
            then = _lands(now, sleep)
            again = app.sleep_until_next_check(then, 6, 7, _local_due(2027, 3, 29))
            nxt = _lands(then, again)
            self.assertEqual((nxt.hour, nxt.utcoffset()), (7, dt.timedelta(hours=1)))


class LongIntervals(unittest.TestCase):

    def test_a_week_long_interval_still_wakes_for_the_draw(self):
        """At the public default of 168 h, the panel used to sleep a week and
        draw whenever it woke. It now wakes on the draw morning at 07:00."""
        with _London():
            now = _at(2026, 10, 26, 7, 1)
            sleep = app.sleep_until_next_check(now, 168, 7, _local_due(2026, 10, 29))
            lands = _lands_on_this_clock(now, sleep)
            self.assertGreaterEqual(lands, _at(2026, 10, 29, 7, 0))
            self.assertLessEqual(lands, _at(2026, 10, 29, 7, 30))

    def test_a_two_day_interval_with_no_draw_due_uses_the_whole_interval(self):
        with _London():
            now = _at(2026, 10, 26, 7, 1)
            sleep = app.sleep_until_next_check(now, 48, 7, None)
            lands = _lands_on_this_clock(now, sleep)
            self.assertGreaterEqual(lands, _at(2026, 10, 28, 7, 0))
            self.assertLessEqual(lands, _at(2026, 10, 28, 7, 30))


class TheWakeReplyUsesIt(unittest.TestCase):

    def test_both_wake_replies_send_the_aligned_sleep(self):
        source = (Path(__file__).resolve().parents[1] / "src" / "app.py").read_text(encoding="utf-8")
        wake = source[source.index('if path == "/wake":'):source.index('if path == "/status":')]
        self.assertNotIn('int(float(cfg["sleep_hours"]) * 3600)', wake,
                         "a bare interval drifts around the clock")
        self.assertEqual(wake.count('"sleep_seconds": store.next_sleep_seconds('), 2)

    def test_a_drawing_wake_counts_the_next_draw_from_today(self):
        """At /wake the draw has not been collected yet, so `fetched_at` is
        still the old one. A drawing wake must plan from today's draw, or a
        long interval would sleep straight past the next one."""
        with _London():
            store = app.FrameStore.__new__(app.FrameStore)
            store.source = type("S", (), {"settings": {
                "refresh_days": 3, "refresh_hour": 7, "sleep_hours": 168}})()
            store.fetched_at = _at(2026, 10, 23, 7, 1).timestamp()
            now = _at(2026, 10, 26, 7, 1)
            sleep = store.next_sleep_seconds(drawing=True, now=now)
            lands = _lands_on_this_clock(now, sleep)
            self.assertGreaterEqual(lands, _at(2026, 10, 29, 7, 0))
            self.assertLessEqual(lands, _at(2026, 10, 29, 7, 30))


if __name__ == "__main__":
    unittest.main()
