"""The framebuffer is copied byte-for-byte into the panel, so its shape and
polarity are contracts, not details."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import pytest
from PIL import Image
from immich import FRAME_BYTES, PANEL_H, PANEL_W, pack, render


def test_frame_is_exactly_one_panel():
    assert FRAME_BYTES == PANEL_W * PANEL_H // 8 == 48000


def test_render_always_produces_a_full_panel_regardless_of_input_shape():
    for size in [(1920, 1440), (4032, 3024), (800, 480), (200, 100), (3000, 500)]:
        out = render(Image.new("RGB", size, "grey"))
        assert out.size == (PANEL_W, PANEL_H), size
        assert out.mode == "1", size


def test_pack_inverts_polarity():
    """PIL stores 255 for white; the panel wants a set bit to mean ink. An
    un-inverted buffer shows a photographic negative, which reads as 'broken
    display' rather than 'wrong constant'."""
    white = Image.new("1", (PANEL_W, PANEL_H), 1)
    assert set(pack(white)) == {0x00}

    black = Image.new("1", (PANEL_W, PANEL_H), 0)
    assert set(pack(black)) == {0xFF}


def test_pack_length_is_the_panel_size():
    assert len(pack(Image.new("1", (PANEL_W, PANEL_H), 1))) == FRAME_BYTES


def test_pack_refuses_a_wrongly_sized_frame():
    """A short buffer would be accepted by the panel and drawn as garbage."""
    with pytest.raises(ValueError):
        pack(Image.new("1", (400, 240), 1))


# --- busyness -------------------------------------------------------------

import numpy as np  # noqa: E402
from immich import detail_score  # noqa: E402


def test_flat_image_scores_near_zero():
    assert detail_score(Image.new("L", (1600, 960), 128)) < 1.0


def test_noise_scores_far_higher_than_a_gradient():
    """The score has to separate fine texture from smooth tone, because that is
    exactly the difference between a photo that dithers cleanly and one that
    turns into speckle."""
    rng = np.random.default_rng(0)
    noise = Image.fromarray(rng.integers(0, 256, (960, 1600), dtype=np.uint8))
    gradient = Image.fromarray(
        np.tile(np.linspace(0, 255, 1600, dtype=np.uint8), (960, 1)))
    assert detail_score(noise) > 10 * detail_score(gradient)


def test_score_is_independent_of_input_resolution():
    """Immich previews vary in size; a score that moved with resolution would
    make the threshold meaningless."""
    rng = np.random.default_rng(1)
    base = Image.fromarray(rng.integers(0, 256, (600, 1000), dtype=np.uint8))
    small = detail_score(base.resize((1000, 600)))
    large = detail_score(base.resize((2000, 1200)))
    assert abs(small - large) / max(small, large) < 0.5
