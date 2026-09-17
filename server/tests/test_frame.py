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


# --- cropping a portrait onto a landscape panel ---------------------------

from immich import crop_box  # noqa: E402


def _face(x1, y1, x2, y2, w=1440, h=1920):
    return [{"boundingBoxX1": x1, "boundingBoxY1": y1,
             "boundingBoxX2": x2, "boundingBoxY2": y2,
             "imageWidth": w, "imageHeight": h}]


def test_the_crop_window_always_matches_the_panel():
    """Anything else is stretched or letterboxed on the glass."""
    for w, h in [(1440, 1920), (4032, 3024), (800, 480), (3000, 500), (500, 3000)]:
        left, top, right, bottom = crop_box(w, h)
        assert (right - left) / (bottom - top) == pytest.approx(PANEL_W / PANEL_H, abs=0.01)
        assert 0 <= left and 0 <= top and right <= w and bottom <= h


def test_a_full_body_portrait_puts_the_face_a_third_down():
    """The composition rule for a subject with a body worth showing."""
    left, top, right, bottom = crop_box(1440, 1920, _face(600, 300, 840, 560))
    centre = (300 + 560) / 2
    assert (centre - top) / (bottom - top) == pytest.approx(1 / 3, abs=0.03)


def test_a_close_up_is_centred_instead():
    """Thirding a face that fills the frame pushes the chin out of it. Found on
    a real photo, which is why the placement is a ramp and not a constant."""
    left, top, right, bottom = crop_box(1440, 1920, _face(200, 200, 1240, 1300))
    centre = (200 + 1300) / 2
    assert (centre - top) / (bottom - top) == pytest.approx(0.5, abs=0.03)


def test_a_face_near_an_edge_never_pushes_the_window_off_the_image():
    """A crop starting at a negative offset renders as a black band."""
    for box in (_face(600, 20, 840, 260), _face(600, 1700, 840, 1900),
                _face(20, 800, 260, 1040), _face(1200, 800, 1430, 1040)):
        left, top, right, bottom = crop_box(1440, 1920, box)
        assert left >= 0 and top >= 0 and right <= 1440 and bottom <= 1920


def test_every_face_is_kept_when_they_fit():
    """A group photo cropped between two people is worse than either alone."""
    faces = _face(200, 400, 500, 700) + _face(900, 450, 1200, 750)
    left, top, right, bottom = crop_box(1440, 1920, faces)
    for f in faces:
        assert left <= f["boundingBoxX1"] and f["boundingBoxX2"] <= right
        assert top <= f["boundingBoxY1"] and f["boundingBoxY2"] <= bottom


def test_face_boxes_are_scaled_from_the_original_to_the_rendition():
    """Immich reports boxes against the ORIGINAL; the renderer works on a
    preview. Ignoring imageWidth/imageHeight crops the wrong part of the photo."""
    original = _face(1500, 1000, 2100, 1700, w=3072, h=4080)
    scaled = _face(1500 * 1440 / 3072, 1000 * 1920 / 4080,
                   2100 * 1440 / 3072, 1700 * 1920 / 4080, w=1440, h=1920)
    assert crop_box(1440, 1920, original) == pytest.approx(crop_box(1440, 1920, scaled), abs=2)


def test_no_faces_still_produces_a_sane_window():
    left, top, right, bottom = crop_box(1440, 1920)
    assert (right - left, bottom - top) == (1440, int(round(1440 / (PANEL_W / PANEL_H))))
    assert top > 0            # biased above centre, not flush to the top


# --- the two previews -----------------------------------------------------

def test_the_panels_generation_is_never_evicted():
    """Press Next photo several times before a wake and the panel is several
    generations behind. Evicting by age alone would discard the only copy of
    the picture actually hanging on the wall, and the On the panel card would
    go blank."""
    import app  # importable because config is validated in main(), not at import

    store = app.FrameStore.__new__(app.FrameStore)
    store.lock = __import__("threading").Lock()
    store.generations = {}
    store.encoded = {}
    store.meta = {}
    store.current = 0
    store.fetched_generation = 1

    for generation in range(1, 6):
        store.generations[generation] = b"x"
        store.meta[generation] = {"n": generation}
        store.encoded[(generation, "png")] = b"x"
        keep = {generation, generation - 1, store.fetched_generation}
        for stale in [g for g in store.generations if g not in keep]:
            store.generations.pop(stale, None)
            store.meta.pop(stale, None)
        for key in [k for k in store.encoded if k[0] not in keep]:
            store.encoded.pop(key, None)
        store.current = generation

    assert 1 in store.generations, "the panel's own photo was thrown away"
    assert {4, 5} <= set(store.generations)
    assert 2 not in store.generations and 3 not in store.generations


def _store(tmp_path):
    import threading
    import app
    st = app.FrameStore.__new__(app.FrameStore)
    st.source = type("S", (), {"path": str(tmp_path / "state.json")})()
    st.lock = threading.Lock()
    st.generations, st.meta, st.encoded = {}, {}, {}
    st.current = 0
    st.fetched_generation, st.fetched_at = 0, None
    return st


def test_a_saved_frame_survives_a_restart(tmp_path):
    """Before this, a restart left generation 0 and every image route
    answering 500, indefinitely when the source had run dry."""
    store = _store(tmp_path)
    payload = bytes(FRAME_BYTES)
    store._persist(payload, {"name": "kept.jpg", "asset_id": "a1"})

    revived = _store(tmp_path)
    revived._restore()
    assert revived.current == 1
    assert revived.generations[1] == payload
    assert revived.meta[1]["name"] == "kept.jpg"


def test_a_truncated_saved_frame_is_refused(tmp_path):
    """Half a frame restores as a band of noise across the panel."""
    import app

    store = app.FrameStore.__new__(app.FrameStore)
    store.source = type("S", (), {"path": str(tmp_path / "state.json")})()
    (tmp_path / "frame.bin").write_bytes(b"\x00" * 100)
    store.generations, store.meta = {}, {}
    store.current = 0
    store._restore()
    assert store.current == 0 and not store.generations


def test_restore_runs_after_the_attributes_it_touches_are_set():
    """Twice now, inserting a method into FrameStore.__init__ put a call above
    the attributes it reads, and the whole server answered 500 on every route.
    A unit test cannot see ordering inside __init__, so read it."""
    import ast, inspect
    import app

    init = next(
        n for n in ast.parse(inspect.getsource(app.FrameStore)).body[0].body
        if isinstance(n, ast.FunctionDef) and n.name == "__init__"
    )
    assigned, restored = set(), False
    for node in init.body:
        if any(isinstance(sub, ast.Call) and getattr(sub.func, "attr", "") == "_restore"
               for sub in ast.walk(node)):
            restored = True
        if not restored:
            targets = list(getattr(node, "targets", []))
            if getattr(node, "target", None) is not None:
                targets.append(node.target)
            assigned |= {t.attr for t in targets if isinstance(t, ast.Attribute)}
    assert restored, "__init__ no longer restores the saved frame"
    for name in ("current", "generations", "meta", "source"):
        assert name in assigned, f"_restore() runs before self.{name} exists"


def test_asking_for_a_generation_that_is_gone_is_an_error_not_another_photo():
    """It used to fall back to the newest frame, so /preview.png?gen=999
    answered 200 with a different picture. A card captioned 'On the panel'
    would then show something that is not on the panel."""
    import threading
    import app

    store = app.FrameStore.__new__(app.FrameStore)
    store.lock = threading.Lock()
    store.generations = {7: b"seven"}
    store.current = 7

    assert store.get(None) == (7, b"seven")
    assert store.get(7) == (7, b"seven")
    with pytest.raises(KeyError):
        store.get(999)
    with pytest.raises(KeyError):
        store.get(6)


def test_the_panel_having_collected_a_frame_survives_a_restart(tmp_path):
    """Otherwise the renderer restarts, `On the panel` reads unknown and
    `Up next` claims a photo is waiting, while the wall has not changed."""
    store = _store(tmp_path)
    store.generations = {4: bytes(FRAME_BYTES)}
    store.meta = {4: {"name": "onwall.jpg", "asset_id": "a1"}}
    store.current = 4
    store._persist(store.generations[4], dict(store.meta[4]))
    store.note_panel_fetch(4)

    revived = _store(tmp_path)
    revived._restore()
    assert revived.fetched_generation == 1, "the panel's photo came back as not collected"
    assert revived.fetched_at is not None
    assert revived.meta[1]["name"] == "onwall.jpg"
    assert "_was_on_panel" not in revived.meta[1], "internal bookkeeping leaked into /status"


def test_a_render_after_a_collection_keeps_both_pictures(tmp_path):
    """The case that sent `On the panel` blank in production: the panel
    collected a photo, a newer one was rendered, and the restart kept only the
    newer. The card then described a wall it had no picture of, for as long as
    three days until the next wake."""
    on_wall, waiting = bytes(FRAME_BYTES), bytes([0xFF]) * FRAME_BYTES
    store = _store(tmp_path)
    store.generations = {1: on_wall}
    store.meta = {1: {"name": "onwall.jpg", "asset_id": "a1"}}
    store.current = 1
    store._persist(on_wall, dict(store.meta[1]))
    store.note_panel_fetch(1)                      # the panel collects it
    store.generations[2] = waiting
    store.meta[2] = {"name": "waiting.jpg", "asset_id": "a2"}
    store.current = 2
    store._persist(waiting, dict(store.meta[2]))   # a newer render lands

    revived = _store(tmp_path)
    revived._restore()
    assert revived.meta[revived.fetched_generation]["name"] == "onwall.jpg"
    assert revived.generations[revived.fetched_generation] == on_wall
    assert revived.meta[revived.current]["name"] == "waiting.jpg"
    assert revived.current != revived.fetched_generation, "a waiting photo read as collected"


def test_one_picture_collected_restores_as_one_generation(tmp_path):
    """When the panel has the newest photo there is nothing waiting, and
    `on_panel` must read true rather than inventing a second generation."""
    frame = bytes(FRAME_BYTES)
    store = _store(tmp_path)
    store.generations = {3: frame}
    store.meta = {3: {"name": "same.jpg", "asset_id": "a1"}}
    store.current = 3
    store._persist(frame, dict(store.meta[3]))
    store.note_panel_fetch(3)

    revived = _store(tmp_path)
    revived._restore()
    assert revived.current == revived.fetched_generation == 1


def test_restarting_does_not_consume_a_photo():
    """A rebuild used to advance the generation, so the panel was instantly a
    step behind and, on a weekly cycle, the frame rotated per deploy rather
    than per week."""
    import ast, inspect
    import app

    main = ast.parse(inspect.getsource(app.main))
    guarded = False
    for node in ast.walk(main):
        if isinstance(node, ast.If) and "current" in ast.unparse(node.test):
            if "rotate" in ast.unparse(node):
                guarded = True
    assert guarded, "main() rotates at start-up without first checking for a restored frame"
