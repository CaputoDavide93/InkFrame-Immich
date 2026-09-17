"""The landscape filter is the whole point of the service, so it is pinned hard.

Every case below is a real shape seen in this library on 2026-09-16, checked
against Immich's own orientation-corrected thumbnails (14/14 agreement).
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import pytest
from immich import is_landscape


# (stored_width, stored_height, exif_orientation, actually_landscape)
CASES = [
    # The trap: landscape-shaped storage, portrait on screen. Twelve of
    # fourteen sampled photos looked like this. A `width > height` filter
    # sends all of them to the panel sideways-cropped.
    (4032, 3024, "6", False),
    (3088, 2316, "6", False),
    (5712, 4284, "6", False),
    (3520, 1980, "6", False),
    # Genuinely landscape: no transposing orientation.
    (4080, 3072, "1", True),
    (3840, 2160, "1", True),
    (4032, 3024, "1", True),
    # Genuinely portrait, stored portrait.
    (3072, 4080, "1", False),
    (3024, 4032, "1", False),
    # Portrait storage plus a transposing orientation is landscape on screen.
    (3024, 4032, "6", True),
    # The other three transposing values behave identically.
    (4032, 3024, "5", False),
    (4032, 3024, "7", False),
    (4032, 3024, "8", False),
    # Non-transposing values leave the stored shape alone.
    (4032, 3024, "3", True),
    (4032, 3024, "2", True),
    (4032, 3024, "4", True),
]


@pytest.mark.parametrize("width,height,orientation,expected", CASES)
def test_orientation_decides_landscape(width, height, orientation, expected):
    exif = {"exifImageWidth": width, "exifImageHeight": height,
            "orientation": orientation}
    assert is_landscape(exif) is expected


def test_orientation_may_be_an_integer_not_a_string():
    """Immich has returned both. Comparing an int to a set of strings silently
    treats every transposed photo as landscape."""
    assert is_landscape({"exifImageWidth": 4032, "exifImageHeight": 3024,
                         "orientation": 6}) is False


def test_missing_orientation_falls_back_to_stored_shape():
    assert is_landscape({"exifImageWidth": 4032, "exifImageHeight": 3024}) is True


@pytest.mark.parametrize("exif", [
    {},
    {"exifImageWidth": 4032},
    {"exifImageHeight": 3024},
    {"exifImageWidth": 0, "exifImageHeight": 0},
])
def test_unanswerable_returns_none_rather_than_guessing(exif):
    """None means 'ask the pixels'. Returning False here would quietly drop
    every photo whose EXIF is incomplete; returning True would show them
    sideways. Neither is a decision this function is entitled to make."""
    assert is_landscape(exif) is None


def test_square_is_not_landscape():
    assert is_landscape({"exifImageWidth": 2000, "exifImageHeight": 2000,
                         "orientation": "1"}) is False


# --- screenshots and memes ------------------------------------------------

from immich import has_camera  # noqa: E402


def test_a_photograph_has_a_camera_make():
    assert has_camera({"make": "Google", "model": "Pixel 6 Pro"}) is True
    assert has_camera({"make": "Apple", "model": "iPhone 15 Pro"}) is True


@pytest.mark.parametrize("exif", [
    {},
    {"make": None},
    {"make": ""},
    {"model": "Pixel 6 Pro"},     # model without make is not a photograph
])
def test_screenshots_and_downloads_are_rejected(exif):
    """A photo frame should not show memes, receipts or web screenshots, and
    this library has plenty. In one 25-photo sample the single
    cleanest-dithering image was a meme: flat graphics score well on texture
    precisely because they have none, so the busyness score alone would have
    promoted it."""
    assert has_camera(exif) is False
