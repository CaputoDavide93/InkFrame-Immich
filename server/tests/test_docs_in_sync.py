"""The inventory tables in the docs are generated from the code. A table that
drifts from the code is a lie in a costume, so staleness fails the suite."""
import importlib.util
import pathlib
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve()
# Flat layout in the source monorepo (tools/ beside tests/); server/ layout in
# the public repository (tools/ one level above server/).
GEN_DOCS = next(
    p for p in (HERE.parents[1] / "tools" / "gen_docs.py",
                HERE.parents[2] / "tools" / "gen_docs.py")
    if p.exists()
)


@pytest.fixture
def gen_docs():
    spec = importlib.util.spec_from_file_location("gen_docs", GEN_DOCS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_endpoint_methods_include_only_post_for_display_ack(gen_docs, monkeypatch):
    source = '''
class Handler:
    def do_GET(self):
        self._handle_request("GET")

    def do_POST(self):
        self._handle_request("POST")

    def _handle_request(self, method):
        if url.path == '/frame/ack':
            if method != "POST":
                return
        else:
            self._route(url.path, query)

    def _route(self, path, query):
        if path in ('/frame.png', '/v2/frame.bin'):
            return
'''
    monkeypatch.setattr(gen_docs, "ENDPOINTS", {
        "/frame/ack": "Display acknowledgement",
        "/frame.png": "PNG download",
        "/v2/frame.bin": "Binary download",
    })

    table = gen_docs.endpoints_table(source)

    assert "`POST /frame/ack`" in table
    assert "`GET /frame/ack`" not in table
    for route in ("/frame.png", "/v2/frame.bin"):
        assert f"`GET {route}`" in table
        assert f"`POST {route}`" in table


@pytest.mark.parametrize("descriptions, message", [
    ({}, "routes with no description"),
    ({"/frame/ack": "ACK", "/retired": "Old route"},
     "described routes that no longer exist"),
])
def test_nested_endpoint_description_drift_fails(gen_docs, monkeypatch,
                                               descriptions, message):
    source = '''
class Handler:
    def do_POST(self):
        if path == "/frame/ack":
            return
'''
    monkeypatch.setattr(gen_docs, "ENDPOINTS", descriptions)

    with pytest.raises(SystemExit, match=message):
        gen_docs.endpoints_table(source)


def test_frame_endpoint_descriptions_explain_legacy_and_explicit_display_ack(gen_docs):
    table = gen_docs.endpoints_table(gen_docs.APP.read_text())
    assert "`POST /frame/ack`" in table
    assert "`GET /frame/ack`" not in table
    for route in ("/frame.png", "/frame.bmp", "/preview.png"):
        assert "does not acknowledge display" in gen_docs.ENDPOINTS[route]
    # The firmware on the panel before the ACK firmware fetches /frame.bmp.
    for route in ("/frame.bin", "/frame.bmp"):
        for detail in ("complete", "legacy firmware", "first valid authenticated POST", "restarts"):
            assert detail in gen_docs.ENDPOINTS[route], (route, detail)
    acknowledgement = gen_docs.ENDPOINTS["/frame/ack"]
    for detail in ("Authenticated", "?gen=N", "positive", "held", "idempotent"):
        assert detail in acknowledgement
    assert "collected" not in gen_docs.ENDPOINTS["/wake"]


def test_generated_tables_match_the_code():
    result = subprocess.run(
        [sys.executable, str(GEN_DOCS), "--check"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
