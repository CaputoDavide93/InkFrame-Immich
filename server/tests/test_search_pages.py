"""A smart search stops after max_pages even when it never fills `want`.

CLIP ranks the whole library, so Immich always offers a next page. A query
whose matches are mostly portraits never reaches `want`, and the loop used to
walk every page of the library.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from immich import Immich  # noqa: E402

PORTRAIT = {"exifInfo": {"exifImageWidth": 3024, "exifImageHeight": 4032,
                         "orientation": "1", "make": "Apple"}}


def test_a_search_that_never_fills_up_stops_at_max_pages():
    client = Immich.__new__(Immich)
    pages: list[int] = []

    def fake_call(path, body=None, raw=False):
        pages.append(body["page"])
        if len(pages) > 50:
            raise AssertionError("walked the whole library")
        return {"assets": {"items": [PORTRAIT] * 100, "nextPage": str(body["page"] + 1)}}

    client._call = fake_call
    assert client.by_search("cat", max_pages=3) == []
    assert pages == [1, 2, 3]
