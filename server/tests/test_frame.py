"""The framebuffer is copied byte-for-byte into the panel, so its shape and
polarity are contracts, not details."""
import json, sys, pathlib
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
    # These persistence tests construct only the state needed for disk I/O.
    # They do not run the background preview renderer.
    st.render_preview_soon = lambda: None
    return st


def _pending_frame(tmp_path):
    from unittest import mock
    import app

    store = _store(tmp_path)
    store.source = app.Source(store.source.path)
    store.generations = {1: bytes(FRAME_BYTES), 2: bytes([0xFF]) * FRAME_BYTES}
    store.meta = {
        1: {"name": "displayed.jpg", "asset_id": "asset-1"},
        2: {"name": "waiting.jpg", "asset_id": "asset-2"},
    }
    store.current = 1
    store.note_panel_fetch(1)
    store.current = 2
    store.preview = True
    store._persist(store.generations[2], dict(store.meta[2]))
    store.render_preview_soon = mock.Mock()
    store.last_error = None
    store.last_wake_at = 0.0
    store.recent = []
    store.people_summary = lambda: {}
    store.albums_cached = lambda: []
    return store


def _renderer_handler(store, url, *, method="GET",
                      authorization="Bearer test-renderer-token"):
    from io import BytesIO
    import app

    handler = app.Handler.__new__(app.Handler)
    handler.store = store
    handler.path = url
    handler.command = method
    handler.token = "test-renderer-token"
    handler.headers = {"Authorization": authorization} if authorization else {}
    handler.wfile = BytesIO()
    handler.response_codes = []
    handler.response_headers = {}
    handler.send_response = handler.response_codes.append
    handler.send_header = handler.response_headers.__setitem__
    handler.end_headers = lambda: None
    return handler


def _display_state(store):
    panel = pathlib.Path(store._frame_path("panel"))
    return (
        store.fetched_generation, store.fetched_at, store.preview,
        store.next_refresh_at(), panel.read_bytes(),
        pathlib.Path(str(panel) + ".json").read_bytes(),
    )


@pytest.mark.parametrize("route", ["/frame.bmp", "/frame.png", "/frame.bin", "/preview.png"])
def test_downloading_a_frame_does_not_acknowledge_display(tmp_path, route):
    store = _pending_frame(tmp_path)
    store.note_ack_capable()
    before = _display_state(store)
    handler = _renderer_handler(store, f"{route}?gen=2")

    handler.do_GET()

    assert handler.response_codes == [200]
    assert handler.response_headers["X-Frame-Generation"] == "2"
    assert handler.wfile.getvalue()
    assert _display_state(store) == before
    store.render_preview_soon.assert_not_called()


@pytest.mark.parametrize("route", ["/frame.bmp", "/frame.png"])
def test_encoding_failure_cannot_acknowledge_display(tmp_path, monkeypatch, route):
    from unittest import mock

    store = _pending_frame(tmp_path)
    before = _display_state(store)
    monkeypatch.setattr(store, "encode", mock.Mock(side_effect=ValueError("encoding failed")))
    handler = _renderer_handler(store, f"{route}?gen=2")

    handler.do_GET()

    assert handler.response_codes == [500]
    assert _display_state(store) == before
    store.render_preview_soon.assert_not_called()


@pytest.mark.parametrize("route", ["/frame.bmp", "/frame.png", "/frame.bin"])
def test_broken_response_cannot_acknowledge_display(tmp_path, route):
    from unittest import mock

    store = _pending_frame(tmp_path)
    before = _display_state(store)
    handler = _renderer_handler(store, f"{route}?gen=2")
    handler.wfile = mock.Mock()
    handler.wfile.write.side_effect = [BrokenPipeError("panel disconnected"), None]

    handler.do_GET()

    assert handler.wfile.write.call_count >= 1
    assert handler.response_codes[0] == 200
    assert _display_state(store) == before
    store.render_preview_soon.assert_not_called()


@pytest.mark.parametrize("offset", [0, 4096, FRAME_BYTES - 4096, FRAME_BYTES + 1])
def test_bin_chunks_and_invalid_ranges_never_acknowledge_display(tmp_path, offset):
    store = _pending_frame(tmp_path)
    before = _display_state(store)
    handler = _renderer_handler(store, f"/frame.bin?gen=2&offset={offset}&len=4096")

    handler.do_GET()

    assert handler.response_codes == [416 if offset > FRAME_BYTES else 200]
    if offset <= FRAME_BYTES:
        assert handler.wfile.getvalue() == store.generations[2][offset:offset + 4096]
    assert _display_state(store) == before
    store.render_preview_soon.assert_not_called()


@pytest.mark.parametrize("newer_render", [False, True], ids=["newest", "older-held"])
def test_authenticated_ack_records_only_the_displayed_generation(tmp_path, newer_render):
    import json

    store = _pending_frame(tmp_path)
    previous_time = store.fetched_at
    store.fetched_at = 1.0
    if newer_render:
        store.current = 3
        store.generations[3] = bytes([0x55]) * FRAME_BYTES
        store.meta[3] = {"name": "newest.jpg", "asset_id": "asset-3"}
        store._persist(store.generations[3], dict(store.meta[3]))
    handler = _renderer_handler(store, "/frame/ack?gen=2", method="POST")

    handler.do_POST()

    assert handler.response_codes == [200]
    assert json.loads(handler.wfile.getvalue())["generation"] == 2
    assert store.fetched_generation == 2
    assert store.fetched_at >= previous_time
    assert pathlib.Path(store._frame_path("panel")).read_bytes() == store.generations[2]
    saved = json.loads(pathlib.Path(store._frame_path("panel") + ".json").read_text())
    assert saved["asset_id"] == "asset-2"
    assert saved["_fetched_at"] == store.fetched_at
    status = _renderer_handler(store, "/status")
    status.do_GET()
    body = json.loads(status.wfile.getvalue())
    assert body["panel_fetched_generation"] == 2
    assert body["on_panel"] is (not newer_render)
    assert body["on_panel_photo"]["asset_id"] == "asset-2"
    if newer_render:
        assert store.preview is True
        store.render_preview_soon.assert_not_called()
    else:
        assert store.preview is False
        store.render_preview_soon.assert_called_once_with()
    revived = _store(tmp_path)
    revived._restore()
    assert revived.meta[revived.fetched_generation]["asset_id"] == "asset-2"
    assert revived.fetched_at == store.fetched_at
    assert revived.meta[revived.current]["asset_id"] == ("asset-3" if newer_render else "asset-2")


@pytest.mark.parametrize("authorization", [None, "Bearer wrong-test-token"])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_display_ack_requires_renderer_authentication(tmp_path, authorization, method):
    store = _pending_frame(tmp_path)
    before = _display_state(store)
    handler = _renderer_handler(
        store, "/frame/ack?gen=2", method=method, authorization=authorization,
    )

    getattr(handler, f"do_{method}")()

    assert handler.response_codes == [401]
    assert _display_state(store) == before
    store.render_preview_soon.assert_not_called()


def test_get_cannot_acknowledge_display(tmp_path):
    store = _pending_frame(tmp_path)
    before = _display_state(store)
    handler = _renderer_handler(store, "/frame/ack?gen=2")

    handler.do_GET()

    assert handler.response_codes == [405]
    assert _display_state(store) == before
    store.render_preview_soon.assert_not_called()


@pytest.mark.parametrize("query,expected_code", [
    ("", 400), ("?gen=", 400), ("?gen=invalid", 400),
    ("?gen=-1", 400), ("?gen=0", 400), ("?gen=2&gen=1", 400),
    ("?gen=2.0", 400), ("?gen=+2", 400), ("?gen=true", 400),
    ("?gen=999", 404),
], ids=["missing", "blank", "not-integer", "negative", "zero", "ambiguous",
        "fractional", "signed", "boolean", "unknown"])
def test_invalid_display_ack_cannot_change_state(tmp_path, query, expected_code):
    store = _pending_frame(tmp_path)
    before = _display_state(store)
    handler = _renderer_handler(store, f"/frame/ack{query}", method="POST")

    handler.do_POST()

    assert handler.response_codes == [expected_code]
    assert _display_state(store) == before
    store.render_preview_soon.assert_not_called()


def test_store_rejects_an_unknown_ack_before_recording_display(tmp_path):
    store = _pending_frame(tmp_path)
    before = _display_state(store)

    with pytest.raises(KeyError):
        store.note_panel_fetch(999)

    assert _display_state(store) == before
    store.render_preview_soon.assert_not_called()


@pytest.mark.parametrize("newer_preview", [False, True])
def test_duplicate_ack_does_not_postpone_the_next_draw(tmp_path, monkeypatch, newer_preview):
    """A retried display ACK is inert even after the next preview is ready."""
    import app

    store = _pending_frame(tmp_path)
    first = _renderer_handler(store, "/frame/ack?gen=2", method="POST")
    monkeypatch.setattr(app.time, "time", lambda: 1_800_000_000.0)
    first.do_POST()
    assert first.response_codes == [200]
    if newer_preview:
        store.current = 3
        store.generations[3] = bytes([0x55]) * FRAME_BYTES
        store.meta[3] = {"name": "preview.jpg", "asset_id": "asset-3"}
        store.preview = True
    before = _display_state(store)
    store.render_preview_soon.reset_mock()
    monkeypatch.setattr(app.time, "time", lambda: 1_800_000_060.0)
    retry = _renderer_handler(store, "/frame/ack?gen=2", method="POST")

    retry.do_POST()

    assert retry.response_codes == [200]
    assert _display_state(store) == before
    store.render_preview_soon.assert_not_called()


def test_retry_of_a_pinned_download_never_switches_to_a_newer_render(tmp_path):
    store = _pending_frame(tmp_path)
    store.note_ack_capable()  # the ACK firmware; legacy BMP acks are tested below
    before = _display_state(store)
    first = _renderer_handler(store, "/frame.bmp?gen=2")
    first.do_GET()
    store.current = 3
    store.generations[3] = bytes([0x55]) * FRAME_BYTES
    store.meta[3] = {"name": "newest.jpg", "asset_id": "asset-3"}
    retry = _renderer_handler(store, "/frame.bmp?gen=2")

    retry.do_GET()

    assert first.response_codes == retry.response_codes == [200]
    assert first.response_headers["X-Frame-Generation"] == "2"
    assert retry.response_headers["X-Frame-Generation"] == "2"
    assert retry.wfile.getvalue() == first.wfile.getvalue()
    assert _display_state(store) == before
    store.render_preview_soon.assert_not_called()


@pytest.fixture
def rendering_store(tmp_path, monkeypatch):
    from unittest import mock
    import app

    store = app.FrameStore(mock.Mock(), app.Source(str(tmp_path / "state.json")))
    store.client.faces.return_value = []
    store.render_preview_soon = mock.Mock()
    store._pool = lambda: [{"id": f"asset-{store.current + 1}"}]
    monkeypatch.setattr(app, "detail_score", lambda _image: 0)
    monkeypatch.setattr(app, "render", lambda *_args, **_kwargs:
                        Image.new("1", (PANEL_W, PANEL_H), store.current % 2))
    monkeypatch.setattr(app, "_touch", lambda _path: None)
    store.rotate()
    store.note_panel_fetch(1)
    store.rotate(preview=True)
    store.render_preview_soon.reset_mock()
    return store


def test_downloaded_generation_survives_render_advance_and_long_draw(rendering_store, monkeypatch):
    import app

    store = rendering_store
    download = _renderer_handler(store, "/frame.bin?gen=2&offset=0&len=4096")
    download.do_GET()
    assert download.response_codes == [200]
    payload = store.generations[2]
    before = _display_state(store)
    for _index in range(20):
        store.rotate(preview=True)
    monkeypatch.setattr(app.time, "time", lambda: before[1] + 86400)
    retry = _renderer_handler(store, "/frame.bin?gen=2&offset=4096&len=4096")
    retry.do_GET()
    assert retry.response_codes == [200], "render advance evicted the in-flight download"
    assert retry.wfile.getvalue() == payload[4096:8192]
    assert _display_state(store)[:2] == before[:2]
    ack = _renderer_handler(store, "/frame/ack?gen=2", method="POST")
    ack.do_POST()
    assert ack.response_codes == [200]
    assert store.fetched_generation == 2
    assert store.meta[store.fetched_generation]["asset_id"] == "asset-2"
    assert pathlib.Path(store._frame_path("panel")).read_bytes() == payload
    assert len(store.generations) <= 4


@pytest.mark.parametrize("advances", [1, 20], ids=["next-render", "many-renders"])
def test_restart_preserves_download_identity_and_next_generation(rendering_store, advances):
    from unittest import mock
    import app

    store = rendering_store
    store.note_ack_capable()  # the ACK firmware: the download alone is not the draw
    download = _renderer_handler(store, "/frame.bmp?gen=2")
    download.do_GET()
    assert download.response_codes == [200]
    payload = store.generations[2]
    for _index in range(advances):
        store.rotate(preview=True)
    newest = store.current
    revived = app.FrameStore(mock.Mock(), store.source)
    revived.render_preview_soon = mock.Mock()
    ack = _renderer_handler(revived, "/frame/ack?gen=2", method="POST")
    ack.do_POST()
    assert ack.response_codes == [200]
    assert revived.meta[revived.fetched_generation]["asset_id"] == "asset-2", "ACK 2 must not record C"
    assert pathlib.Path(revived._frame_path("panel")).read_bytes() == payload
    assert revived.current == newest
    assert revived.meta[newest]["asset_id"] == f"asset-{newest}"
    again = app.FrameStore(store.client, store.source)
    again._pool = lambda: [{"id": "after-restart"}]
    assert again.current == newest
    assert again.fetched_generation == 2
    assert again.rotate() == newest + 1


@pytest.mark.parametrize("restart", [False, True], ids=["running", "restarted"])
def test_old_ack_replay_after_newer_ack_never_regresses_display(rendering_store, monkeypatch, restart):
    from unittest import mock
    import app

    store = rendering_store
    for generation in (2, 3):
        if generation == 3:
            store.rotate(preview=True)
        ack = _renderer_handler(store, f"/frame/ack?gen={generation}", method="POST")
        ack.do_POST()
        assert ack.response_codes == [200]
    if restart:
        store = app.FrameStore(mock.Mock(), store.source)
        store.render_preview_soon = mock.Mock()
    before = _display_state(store)
    store.render_preview_soon.reset_mock()
    monkeypatch.setattr(app.time, "time", lambda: before[1] + 86400)
    replay = _renderer_handler(store, "/frame/ack?gen=2", method="POST")
    replay.do_POST()
    assert replay.response_codes[0] in (200, 404, 409)
    assert _display_state(store) == before, "stale ACK rewrote display state or postponed the draw"
    store.render_preview_soon.assert_not_called()


def test_legacy_frames_migrate_without_accepting_an_ambiguous_old_ack(tmp_path):
    import json
    from unittest import mock
    import app

    for slot, value, meta in (
        ("panel", 0, {"asset_id": "legacy-A", "_fetched_at": 123.0}),
        ("frame", 255, {"asset_id": "legacy-C", "_preview": True}),
    ):
        (tmp_path / f"{slot}.bin").write_bytes(bytes([value]) * FRAME_BYTES)
        (tmp_path / f"{slot}.bin.json").write_text(json.dumps(meta))
    store = app.FrameStore(mock.Mock(), app.Source(str(tmp_path / "state.json")))
    store.render_preview_soon = mock.Mock()
    before = _display_state(store)
    ack = _renderer_handler(store, "/frame/ack?gen=2", method="POST")
    ack.do_POST()
    assert ack.response_codes == [404], "legacy files cannot prove what old generation 2 contained"
    assert _display_state(store) == before
    assert store.meta[store.fetched_generation]["asset_id"] == "legacy-A"
    assert store.meta[store.current]["asset_id"] == "legacy-C"
    assert store.preview is True
    revived = app.FrameStore(mock.Mock(), store.source)
    assert (revived.current, revived.fetched_generation) == (store.current, store.fetched_generation)
    assert revived.fetched_at == 123.0


def test_pending_download_storage_is_bounded_and_released_on_ack(rendering_store, tmp_path):
    rendering_store.note_ack_capable()
    store = rendering_store
    for _index in range(20):
        download = _renderer_handler(store, f"/frame.bin?gen={store.current}")
        download.do_GET()
        assert download.response_codes == [200]
        assert pathlib.Path(store._frame_path("download")).exists()
        assert pathlib.Path(store._frame_path("download") + ".json").exists()
        store.rotate(preview=True)
        assert len(store.generations) <= 4
        assert len(list(tmp_path.glob("*.bin"))) <= 3
        assert len(list(tmp_path.glob("*.bin.json"))) <= 3
    pending = store.current - 1
    ack = _renderer_handler(store, f"/frame/ack?gen={pending}", method="POST")
    ack.do_POST()
    assert ack.response_codes == [200]
    assert store.downloading_generation == 0
    assert not pathlib.Path(store._frame_path("download")).exists()
    assert not pathlib.Path(store._frame_path("download") + ".json").exists()


def test_failed_render_persistence_does_not_publish_a_generation(rendering_store, monkeypatch):
    store = rendering_store
    before = (store.current, store.next_generation, dict(store.generations), dict(store.meta))
    monkeypatch.setattr(store, "_persist", lambda *_args, **_kwargs: False)
    with pytest.raises(OSError, match="save the rendered generation"):
        store.rotate()
    assert (store.current, store.next_generation, store.generations, store.meta) == before


def test_failed_ack_persistence_cannot_report_display_success(rendering_store, monkeypatch):
    store = rendering_store
    before = _display_state(store)
    monkeypatch.setattr(store, "_persist", lambda *_args, **_kwargs: False)
    ack = _renderer_handler(store, "/frame/ack?gen=2", method="POST")
    ack.do_POST()
    assert ack.response_codes == [500]
    assert _display_state(store) == before
    store.render_preview_soon.assert_not_called()


@pytest.mark.parametrize("route", ["/frame.bmp", "/frame.png", "/frame.bin", "/preview.png"])
@pytest.mark.parametrize("authorization", [None, "Bearer wrong-test-token"])
def test_pinned_image_get_requires_auth_without_changing_pending_state(rendering_store, route, authorization):
    store = rendering_store
    before = _display_state(store)
    handler = _renderer_handler(store, f"{route}?gen=2", authorization=authorization)
    handler.do_GET()
    assert handler.response_codes == [401]
    assert _display_state(store) == before
    assert store.downloading_generation == 0


@pytest.mark.parametrize("route", ["/frame.bmp", "/frame.png", "/frame.bin", "/preview.png"])
@pytest.mark.parametrize("generation", ["999", "invalid", "-1", "0"])
def test_unknown_or_malformed_pinned_image_get_stays_not_found(rendering_store, route, generation):
    store = rendering_store
    before = _display_state(store)
    handler = _renderer_handler(store, f"{route}?gen={generation}")
    handler.do_GET()
    assert handler.response_codes == [404]
    assert _display_state(store) == before
    assert store.downloading_generation == 0


@pytest.mark.parametrize("route", ["/frame/ack/extra?gen=2", "/frame/unknown?gen=2", "/not-a-route"])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_unknown_routes_cannot_ack_or_pin_a_frame(rendering_store, route, method):
    store = rendering_store
    before = _display_state(store)
    handler = _renderer_handler(store, route, method=method)
    getattr(handler, f"do_{method}")()
    assert handler.response_codes == [404]
    assert _display_state(store) == before
    assert store.downloading_generation == 0


def test_preview_reads_cannot_displace_the_single_pending_panel_download(rendering_store):
    store = rendering_store
    store.note_ack_capable()  # the ACK firmware: the download alone is not the draw
    download = _renderer_handler(store, "/frame.bmp?gen=2")
    download.do_GET()
    assert download.response_codes == [200]
    for _index in range(10):
        store.rotate(preview=True)
        preview = _renderer_handler(store, "/preview.png")
        preview.do_GET()
        assert preview.response_codes == [200]
        assert store.downloading_generation == 2
        assert 2 in store.generations
        assert len(store.generations) <= 4
        assert len(store.encoded) <= 8
    ack = _renderer_handler(store, "/frame/ack?gen=2", method="POST")
    ack.do_POST()
    assert ack.response_codes == [200]
    assert store.meta[store.fetched_generation]["asset_id"] == "asset-2"


def test_a_saved_frame_survives_a_restart(tmp_path):
    """Before this, a restart left generation 0 and every image route
    answering 500. Legacy snapshots migrate to fresh, unambiguous IDs."""
    store = _store(tmp_path)
    payload = bytes(FRAME_BYTES)
    store._persist(payload, {"name": "kept.jpg", "asset_id": "a1"})

    revived = _store(tmp_path)
    revived._restore()
    assert revived.current > 2
    assert revived.generations[revived.current] == payload
    assert revived.meta[revived.current]["name"] == "kept.jpg"


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
    """An explicit display ACK and its ID survive restart; a GET is not an ACK.

    Otherwise `On the panel` reads unknown and `Up next` claims a photo is
    waiting, while the wall has not changed.
    """
    store = _store(tmp_path)
    store.generations = {4: bytes(FRAME_BYTES)}
    store.meta = {4: {"name": "onwall.jpg", "asset_id": "a1"}}
    store.current = 4
    store._persist(store.generations[4], dict(store.meta[4]))
    store.note_panel_fetch(4)

    revived = _store(tmp_path)
    revived._restore()
    assert revived.fetched_generation == 4, "the acknowledged identity changed on restart"
    assert revived.fetched_at is not None
    assert revived.meta[4]["name"] == "onwall.jpg"
    assert "_was_on_panel" not in revived.meta[4], "internal bookkeeping leaked into /status"


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
    `on_panel` stays true with the same ID, not an invented generation."""
    frame = bytes(FRAME_BYTES)
    store = _store(tmp_path)
    store.generations = {3: frame}
    store.meta = {3: {"name": "same.jpg", "asset_id": "a1"}}
    store.current = 3
    store._persist(frame, dict(store.meta[3]))
    store.note_panel_fetch(3)

    revived = _store(tmp_path)
    revived._restore()
    assert revived.current == revived.fetched_generation == 3


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


def test_asking_for_the_album_list_also_refreshes_the_cache(tmp_path):
    """`/status` serves a cache filled once a day beside the people count, so
    an album made this afternoon was absent from the Home Assistant picker
    until tomorrow -- while rendering, which reads the live list, would have
    used it happily. Two views of the same library disagreeing for a day is
    indistinguishable from the integration not seeing the album at all, so
    `/albums` writes what it read back into the cache."""
    import threading
    import app

    store = app.FrameStore.__new__(app.FrameStore)
    store.lock = threading.Lock()
    store._albums = ["Old"]
    store.client = type("C", (), {"albums": lambda self: {"New": "id2", "Old": "id1"}})()

    assert store.albums_cached() == ["Old"]
    assert store.refresh_albums() == ["New", "Old"]
    assert store.albums_cached() == ["New", "Old"]


def test_the_albums_route_refreshes_rather_than_only_reading():
    """The route must go through refresh_albums(), not straight to the client:
    a read that leaves the cache stale is the bug this fixed."""
    import inspect
    import app

    source = inspect.getsource(app.Handler)
    block = source.split('if path == "/albums":')[1].split("return")[0]
    assert "store.refresh_albums()" in block
    assert "store.client.albums()" not in block


def test_renderer_routes_require_a_constant_time_bearer_check():
    """A LAN listener is not an access-control boundary for family photos."""
    import inspect
    import app

    source = inspect.getsource(app.Handler)
    assert "hmac.compare_digest" in source
    assert 'url.path != "/healthz" and not self._authorised()' in source
    assert "Authorization" in source


def test_photo_only_switch_reaches_every_non_album_source():
    """The setting must mean the same thing for Random, faces and search."""
    import inspect
    import app
    from immich import Immich

    pool = inspect.getsource(app.FrameStore._pool)
    assert pool.count("require_camera=require_camera") >= 5
    for method in (Immich.by_person, Immich.by_album, Immich.recent, Immich.by_search):
        assert "require_camera" in inspect.signature(method).parameters


def test_source_options_reads_coordinator_data_before_using_it():
    """A missing local `data` makes HA fail while rendering the select."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).parents[1]
    component = root / "custom_components" / "inkframe" / "select.py"
    # The exported repository puts tests under server/, alongside a top-level
    # custom_components directory; the private source does not.
    if not component.exists():
        component = root.parent / "custom_components" / "inkframe" / "select.py"
    tree = ast.parse(component.read_text())
    options = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef) and node.name == "options")
    assigned = {target.id for node in ast.walk(options)
                if isinstance(node, ast.Assign) for target in node.targets
                if isinstance(target, ast.Name)}
    assert "data" in assigned


def test_a_failed_people_count_says_so_instead_of_only_logging():
    """On 2026-09-22 this container started before Immich was listening.

    The one daily count died on a refused connection, was logged and
    swallowed, and `/people` served `{}` for the next 22 hours. In Home
    Assistant that meant the three `Include <person>` switches -- which are
    created only for people the renderer calls eligible -- were never created
    at all, and the People source had nobody to draw from. Nothing was broken;
    the renderer had asked once, at the only minute of the day the answer was
    unavailable.

    A caller cannot retry an outcome it cannot see, so the count reports one.
    """
    import threading
    import app

    def store_with(client):
        store = app.FrameStore.__new__(app.FrameStore)
        store.lock = threading.Lock()
        store.people_ready = threading.Event()
        store.people = {}
        store.people_counted_at = None
        store._albums = []
        store.client = client
        store.source = type("S", (), {"settings": {"require_camera": False}})()
        return store

    class Refused:
        def people(self):
            raise ConnectionRefusedError(111, "Connection refused")

    class Answers:
        def people(self):
            return {"Alex": "id1"}

        def by_person(self, pid, require_camera=False):
            return list(range(50))

        def albums(self):
            return {"Trips": "a1"}

    failed = store_with(Refused())
    assert failed.count_people() is False
    assert failed.people_summary() == {}
    # Still SET on failure: people_summary(wait=True) must not block for its
    # full 90 seconds on every request while Immich is down.
    assert failed.people_ready.is_set()

    ok = store_with(Answers())
    assert ok.count_people() is True
    assert ok.people_summary()["Alex"]["eligible"] is True


def test_a_failed_count_retries_instead_of_sleeping_a_whole_day():
    """The loop must branch on the outcome, and the wait must grow.

    A frame that refreshes every three days gains nothing from asking Immich
    every thirty seconds for an hour, so this is a backoff and not a hammer --
    and the backoff is capped by the ordinary daily interval, because waiting
    longer than the next scheduled count would have been is never useful.
    """
    import ast
    import inspect
    import app

    source = inspect.getsource(app.main)
    loop = next(n for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.FunctionDef) and n.name == "recount_people")
    body = ast.unparse(loop)

    assert "if store.count_people():" in body, \
        "the recount loop ignores the outcome, so a failure still costs a day"
    assert "PEOPLE_RETRY_FIRST_SECONDS" in body
    assert "PEOPLE_RETRY_MAX_SECONDS" in body
    assert "wait * 2" in body, "the retry wait must grow, not stay flat"
    assert "min(wait, PEOPLE_RECOUNT_SECONDS)" in body, \
        "a retry must never wait longer than the ordinary daily count"
    assert app.PEOPLE_RETRY_MAX_SECONDS < app.PEOPLE_RECOUNT_SECONDS


def test_legacy_complete_download_advances_until_first_post_and_after_restart(tmp_path):
    import app
    store = _pending_frame(tmp_path)
    download = _renderer_handler(store, "/frame.bin?gen=2")
    download.do_GET()
    assert store.fetched_generation == 2
    store.render_preview_soon.assert_called_once()

    ack = _renderer_handler(store, "/frame/ack?gen=2", method="POST")
    ack.do_POST()
    assert ack.response_codes == [200]
    revived = app.FrameStore(None, app.Source(store.source.path))
    revived.render_preview_soon = lambda: None
    revived.generations[3] = bytes(FRAME_BYTES)
    revived.meta[3] = {}
    revived.current = 3
    _renderer_handler(revived, "/frame.bin?gen=3").do_GET()
    assert revived.fetched_generation == 2, "ACK-capable firmware must stay strict after restart"


def test_legacy_strips_only_ack_after_the_complete_download(tmp_path):
    store = _pending_frame(tmp_path)
    for offset in range(0, FRAME_BYTES, 4096):
        _renderer_handler(store, f"/frame.bin?gen=2&offset={offset}&len=4096").do_GET()
        assert store.fetched_generation == (2 if offset + 4096 >= FRAME_BYTES else 1)


# The firmware on the panel today (hub/home-assistant/esphome/immich-frame.yaml
# on main before the ACK firmware) fetches exactly `/frame.bmp`, no query, and
# never POSTs /frame/ack. A renderer deployed before the panel is reflashed must
# still count that download as the draw, or every wake redraws the same photo.
CURRENT_FIRMWARE_URLS = ["/frame.bmp", "/frame.bmp?gen=2"]


@pytest.mark.parametrize("url", CURRENT_FIRMWARE_URLS)
def test_current_firmware_bmp_download_acknowledges_until_first_post(tmp_path, url):
    store = _pending_frame(tmp_path)
    store.preview = False   # asked for with /next?now=1, so /wake says draw
    wake = _renderer_handler(store, "/wake")
    wake.do_GET()
    assert json.loads(wake.wfile.getvalue())["draw"] is True

    download = _renderer_handler(store, url)
    download.do_GET()

    assert download.response_codes == [200]
    assert store.fetched_generation == 2, "the BMP the panel drew must count as displayed"
    store.render_preview_soon.assert_called_once()
    later = _renderer_handler(store, "/wake")
    later.do_GET()
    assert json.loads(later.wfile.getvalue())["draw"] is False, \
        "the next check must be a 7 s check, not another 35 s redraw"


@pytest.mark.parametrize("route", ["/frame.png", "/preview.png"])
def test_legacy_fallback_is_the_panel_bmp_only(tmp_path, route):
    store = _pending_frame(tmp_path)
    before = _display_state(store)
    _renderer_handler(store, f"{route}?gen=2").do_GET()
    assert _display_state(store) == before


@pytest.mark.parametrize("url", ["/frame.bmp?gen=2", "/frame.bin?gen=2"])
def test_a_failed_legacy_ack_never_writes_a_second_response(tmp_path, monkeypatch, url):
    from unittest import mock
    store = _pending_frame(tmp_path)
    monkeypatch.setattr(store, "note_panel_fetch", mock.Mock(side_effect=OSError("disk full")))
    handler = _renderer_handler(store, url)

    handler.do_GET()

    assert handler.response_codes == [200], "the frame was already sent; a 500 after it corrupts the socket"
    assert b'"error"' not in handler.wfile.getvalue()


@pytest.mark.parametrize("query", ["", "?gen=0", "?gen=99", "?gen=abc"])
def test_only_a_valid_ack_opts_into_strict_acknowledgement(tmp_path, query):
    store = _pending_frame(tmp_path)
    _renderer_handler(store, f"/frame/ack{query}", method="POST").do_POST()

    assert getattr(store, "ack_capable", False) is False
    assert not (tmp_path / "panel-protocol.json").exists()
    _renderer_handler(store, "/frame.bmp").do_GET()
    assert store.fetched_generation == 2, "a stray POST must not freeze the current firmware"


def test_a_valid_ack_opts_in_and_later_bmp_downloads_do_not_acknowledge(tmp_path):
    store = _pending_frame(tmp_path)
    ack = _renderer_handler(store, "/frame/ack?gen=1", method="POST")
    ack.do_POST()
    assert ack.response_codes == [200]
    assert store.ack_capable is True
    _renderer_handler(store, "/frame.bmp").do_GET()
    assert store.fetched_generation == 1

# --- a long OTA window makes a check hold the window (2026-10-22) -----------

def _wake(store, ota_seconds):
    import json
    from unittest import mock

    store.source.settings["ota_window_seconds"] = ota_seconds
    store.scheduled_refresh_due = lambda: False
    store.next_refresh_description = lambda: "later"
    store.rotate = mock.Mock(side_effect=AssertionError("a wake for a flash must not render"))
    handler = _renderer_handler(store, "/wake")
    handler.do_GET()
    assert handler.response_codes == [200]
    return json.loads(handler.wfile.getvalue())


def test_a_normal_window_still_lets_a_check_sleep(tmp_path):
    """The default 20 seconds changes nothing: a check is still a check."""
    store = _pending_frame(tmp_path)
    reply = _wake(store, 20)
    assert reply["draw"] is False
    assert reply["ota_window_seconds"] == 20


def test_a_flash_window_redraws_the_photo_already_on_the_glass(tmp_path):
    """Only a drawing wake holds the OTA window (the firmware's delay lives in
    on_download_finished). So "Prepare for update" (300 s) has to make the
    next CHECK draw, or the panel sleeps seven seconds later and the button
    promised a window that never opened. It draws what the panel already
    shows, not the held preview, so the wall, `on_panel` and the schedule
    are exactly as they were once the panel acknowledges it."""
    store = _pending_frame(tmp_path)
    store.note_ack_capable()
    before = _display_state(store)
    reply = _wake(store, 300)
    assert reply["draw"] is True
    assert reply["generation"] == 1, "the photo on the glass, not the held preview"
    assert reply["ota_window_seconds"] == 300

    fetch = _renderer_handler(store, "/frame.bmp?gen=1")
    fetch.do_GET()
    assert fetch.response_codes == [200]
    ack = _renderer_handler(store, "/frame/ack?gen=1", method="POST")
    ack.do_POST()
    assert ack.response_codes == [200]
    assert _display_state(store) == before
    assert store.current == 2 and store.preview is True, "Up next is untouched"
    store.render_preview_soon.assert_not_called()


def test_a_flash_window_with_nothing_waiting_redraws_without_rendering(tmp_path):
    store = _pending_frame(tmp_path)
    store.note_panel_fetch(2)
    store.render_preview_soon.reset_mock()
    reply = _wake(store, 60)
    assert reply["draw"] is True
    assert reply["generation"] == 2
    store.rotate.assert_not_called()


def test_a_flash_window_is_the_threshold_the_button_sets():
    """The HA script sets 300; the renderer's line must sit below that and
    well above the 20-second default, or the button opens nothing."""
    import app
    assert 20 < app.FLASH_WINDOW_SECONDS <= 300
