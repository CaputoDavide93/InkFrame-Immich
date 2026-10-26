"""Every acceptable photo in the album gets its turn.

Davide, 2026-09-25: "I added 39 photos in the album but only 3/4 are
displayed." 36 of the 39 were eligible (three PNGs have no camera metadata and
are skipped on purpose). The pick took the CALMEST of twenty scored candidates
every time -- more than half the album per draw -- so the same few calmest
photos won again and again, and the recently-shown list was forgotten at
every restart, so they came straight back.
"""
from __future__ import annotations

import collections
import sys
import tempfile
import threading
from collections import deque
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import app  # noqa: E402


def _source_text() -> str:
    return (Path(__file__).resolve().parents[1] / "src" / "app.py").read_text(encoding="utf-8")


def test_the_pick_is_random_among_the_acceptable_not_the_calmest() -> None:
    body = _source_text()
    body = body[body.index("    def _rotate(self)"):body.index("    def _pool(self)")]
    assert "_random.choice(acceptable)" in body, "the pick is the calmest again"
    assert "row[0] <= max_busyness" in body


def test_a_small_album_spreads_across_its_photos() -> None:
    """Simulate the pick over an album where busyness varies but all pass."""
    import random
    random.seed(7)
    scores = {f"p{i}": 3 + i * 0.1 for i in range(36)}        # all well under 22
    wins = collections.Counter()
    for _ in range(360):
        sample = random.sample(list(scores), 20)
        scored = sorted((scores[k], k) for k in sample)
        acceptable = [row for row in scored if row[0] <= 22]
        wins[random.choice(acceptable)[1]] += 1
    assert len(wins) == 36, "some acceptable photos never won"
    assert max(wins.values()) < 30, "one photo still dominates"


def test_the_recently_shown_list_survives_a_restart() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        def store():
            s = app.FrameStore.__new__(app.FrameStore)
            s.source = mock.Mock(); s.source.path = str(Path(tmp) / "source.json")
            s.recent = deque(maxlen=120)
            return s
        first = store()
        first._save_recent(["a", "b", "c"])
        second = store()
        second._restore_recent()
        assert list(second.recent) == ["a", "b", "c"]
        (Path(tmp) / "recent.json").write_text("not json")
        third = store(); third._restore_recent()
        assert list(third.recent) == []


def test_preview_cannot_replace_a_photo_requested_while_waiting_for_render() -> None:
    """The decision to render a preview belongs inside the render lock."""
    attempted = threading.Event()

    class Gate:
        def __init__(self):
            self.lock = threading.Lock()

        def __enter__(self):
            attempted.set()
            self.lock.acquire()

        def __exit__(self, *_args):
            self.lock.release()

    gate = Gate()
    store = app.FrameStore.__new__(app.FrameStore)
    store._render_lock = gate
    store.lock = threading.Lock()
    store.current = 1
    store.fetched_generation = 1
    store.rotate = mock.Mock(return_value=3)

    gate.lock.acquire()
    worker = threading.Thread(target=store.render_preview)
    worker.start()
    try:
        assert attempted.wait(timeout=2)
        # /next has rendered a requested generation while the preview waited.
        with store.lock:
            store.current = 2
    finally:
        gate.lock.release()
    worker.join(timeout=2)
    assert not worker.is_alive()
    store.rotate.assert_not_called()
