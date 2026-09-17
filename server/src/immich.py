"""Immich client + 1-bit e-paper rendering for the XIAO 7.5" panel."""
from __future__ import annotations

import io
import json
import logging
import urllib.request
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

LOG = logging.getLogger("immich")

# EXIF orientation 5-8 transpose the image, so the STORED width/height are
# swapped relative to what anybody actually sees. Immich's API reports the
# stored pair. Filtering on `width > height` alone therefore calls a sideways
# portrait a landscape -- measured against Immich's own orientation-corrected
# thumbnails, that mistake covers 86% of this library (12 of 14 sampled photos
# report 4032x3024 while rendering portrait). Verified 14/14 on 2026-09-16.
SWAPPED_ORIENTATIONS = {"5", "6", "7", "8"}

PANEL_W = 800
PANEL_H = 480
FRAME_BYTES = PANEL_W * PANEL_H // 8  # 48000


def is_landscape(exif: dict) -> bool | None:
    """True/False, or None when EXIF cannot answer and the caller must probe."""
    width, height = exif.get("exifImageWidth"), exif.get("exifImageHeight")
    if not width or not height:
        return None
    swapped = str(exif.get("orientation")) in SWAPPED_ORIENTATIONS
    return (width > height) != swapped


def has_camera(exif: dict) -> bool:
    """Was this taken by a camera, rather than screenshotted or downloaded?

    A photo frame should not show memes, receipts or web screenshots, and this
    library has plenty. `make` is populated by every phone and camera and by
    nothing else, so its absence is a clean, certain test -- no filename
    guessing. It rejects about 8% of otherwise-eligible landscape assets, and
    the meme it caught first was the single "cleanest-dithering" image in a
    25-photo sample: flat graphics score well on texture precisely because they
    have none.
    """
    return bool(exif.get("make"))


def detail_score(img: Image.Image) -> float:
    """How badly will this photo dither? Higher is busier is worse.

    Mean absolute Laplacian over the cropped frame. Fine texture everywhere --
    grass, foliage, gravel -- scores high and collapses into visible dot noise
    on a one-bit panel; a subject against a plain background scores low and
    survives. Measured range on this library is 2.7 to 59.5, so it separates
    cleanly. Showing one photo a week means we can reject the busy tail
    outright instead of hoping a cleverer dither rescues it.
    """
    arr = np.asarray(
        ImageOps.fit(ImageOps.exif_transpose(img).convert("L"),
                     (PANEL_W, PANEL_H), Image.LANCZOS, centering=(0.5, 0.42)),
        dtype=np.float64)
    lap = np.abs(4 * arr[1:-1, 1:-1] - arr[:-2, 1:-1] - arr[2:, 1:-1]
                 - arr[1:-1, :-2] - arr[1:-1, 2:])
    return float(lap.mean())


@dataclass(frozen=True)
class Asset:
    id: str
    name: str
    taken: str | None
    busyness: float = 0.0


class Immich:
    def __init__(self, base_url: str, api_key: str, timeout: int = 60) -> None:
        self.base = base_url.rstrip("/")
        self.key = api_key
        self.timeout = timeout

    def _call(self, path: str, body: dict | None = None, raw: bool = False):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"x-api-key": self.key, "Content-Type": "application/json"},
            method="POST" if body is not None else "GET",
        )
        response = urllib.request.urlopen(request, timeout=self.timeout)
        return response.read() if raw else json.load(response)

    def ping(self) -> bool:
        try:
            self._call("/api/server/ping")
            return True
        except Exception as exc:  # noqa: BLE001 - health check reports, never raises
            LOG.warning("immich ping failed: %s", exc)
            return False

    def candidates(self, pool: int = 100, rounds: int = 4, want: int = 20,
                   exclude: set[str] | None = None,
                   require_camera: bool = True) -> list[dict]:
        """Landscape photographs, before the expensive per-pixel scoring.

        Only ~13.5% of this library is landscape and ~8% of those are
        screenshots, so this over-fetches hard and filters on EXIF -- which is
        free -- to keep the number of images actually downloaded small.

        `rounds` is a ceiling, not a target. One round of 100 yields ~12
        eligible assets and costs ~55 ms; running all four unconditionally cost
        225 ms to build a pool three quarters of which was then thrown away by
        `pool[:CANDIDATES]`.
        """
        exclude = exclude or set()
        out: list[dict] = []
        for _ in range(rounds):
            for asset in self._call("/api/search/random",
                                    {"size": pool, "type": "IMAGE", "withExif": True}):
                if asset["id"] in exclude:
                    continue
                exif = asset.get("exifInfo") or {}
                if is_landscape(exif) is not True:
                    continue
                if require_camera and not has_camera(exif):
                    continue
                out.append(asset)
            if len(out) >= want:
                break
        return out

    def people(self) -> dict[str, str]:
        """Named people -> id. Face recognition is the only working selector
        here: this library has zero albums, and only four favourites."""
        data = self._call("/api/people")
        rows = data.get("people", data) if isinstance(data, dict) else data
        return {p["name"]: p["id"] for p in rows if p.get("name")}

    def by_person(self, person_id: str, max_pages: int = 8) -> list[dict]:
        """Every landscape photograph of one person.

        `total` in a search response counts the page, not the result set, so it
        cannot be used to size this -- the pages have to be walked. `nextPage`
        comes back as a string.
        """
        out: list[dict] = []
        page: int | str | None = 1
        while page and int(page) <= max_pages:
            body = {"personIds": [person_id], "type": "IMAGE",
                    "size": 250, "page": int(page), "withExif": True}
            assets = self._call("/api/search/metadata", body).get("assets", {})
            for asset in assets.get("items", []):
                exif = asset.get("exifInfo") or {}
                if is_landscape(exif) is True and has_camera(exif):
                    out.append(asset)
            page = assets.get("nextPage")
        return out

    def recent(self, days: int = 90, max_pages: int = 6) -> list[dict]:
        """Landscape photographs taken in the last N days."""
        import datetime
        after = (datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(days=days)).isoformat()
        out: list[dict] = []
        page: int | str | None = 1
        while page and int(page) <= max_pages:
            body = {"takenAfter": after, "type": "IMAGE", "size": 250,
                    "page": int(page), "withExif": True}
            assets = self._call("/api/search/metadata", body).get("assets", {})
            for asset in assets.get("items", []):
                exif = asset.get("exifInfo") or {}
                if is_landscape(exif) is True and has_camera(exif):
                    out.append(asset)
            page = assets.get("nextPage")
        return out

    def albums(self) -> dict[str, str]:
        """Album name -> id. Empty on this library today; offered anyway so
        the day an album is made it appears without a code change."""
        rows = self._call("/api/albums")
        return {a["albumName"]: a["id"] for a in rows if a.get("albumName")}

    def by_album(self, album_id: str) -> list[dict]:
        """Every landscape photograph in one album. /api/albums/{id} returns
        the assets inline with their EXIF, no paging."""
        data = self._call(f"/api/albums/{album_id}")
        out: list[dict] = []
        for asset in data.get("assets", []):
            exif = asset.get("exifInfo") or {}
            if is_landscape(exif) is True and has_camera(exif):
                out.append(asset)
        return out

    def preview(self, asset_id: str) -> Image.Image:
        """Immich's preview render, which is already orientation-corrected."""
        data = self._call(f"/api/assets/{asset_id}/thumbnail?size=preview", raw=True)
        return Image.open(io.BytesIO(data))


def _edge_preserving_smooth(arr: np.ndarray, radius: int = 2,
                            strength: float = 0.45) -> np.ndarray:
    """Flatten texture without softening the edges that carry the subject.

    A plain blur would destroy exactly what survives one bit best. This blends
    toward the blurred copy only where local variance is LOW -- the
    busy-but-featureless regions that dither into noise -- and leaves real
    boundaries alone.
    """
    img = Image.fromarray(arr.astype(np.uint8))
    blur = np.asarray(img.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float64)
    mean = np.asarray(img.filter(ImageFilter.BoxBlur(radius * 2)), dtype=np.float64)
    var = np.asarray(
        Image.fromarray((((arr - mean) ** 2) / 255).clip(0, 255).astype(np.uint8))
        .filter(ImageFilter.BoxBlur(radius * 2)), dtype=np.float64)
    edge = np.clip(var / 12.0, 0, 1)
    keep = edge + (1 - edge) * (1 - strength)
    return arr * keep + blur * (1 - keep)


def _s_curve(arr: np.ndarray, amount: float = 0.35) -> np.ndarray:
    """Push tones away from mid-grey.

    Dot density and therefore visible dither noise peak at 50%. Pulling
    midtones toward black and white trades tonal subtlety the panel cannot
    render anyway for a visibly cleaner picture.
    """
    x = arr / 255.0
    return np.clip(x - amount * np.sin(2 * np.pi * x) / (2 * np.pi), 0, 1) * 255


def render(img: Image.Image, smooth: float = 0.45, curve: float = 0.35,
           edge: int = 55, contrast: float = 1.05) -> Image.Image:
    """Photo -> 1-bit Floyd-Steinberg frame at exactly 800x480.

    Order matters: crop, autocontrast, flatten texture, push tones off
    mid-grey, restore edges, then dither. Sharpening after dithering would only
    amplify dither noise. An earlier version sharpened before any smoothing and
    turned grass into a field of specks -- the complaint that prompted this.
    """
    img = ImageOps.exif_transpose(img).convert("L")
    # Centre slightly above the middle: faces and horizons both sit high.
    img = ImageOps.fit(img, (PANEL_W, PANEL_H), method=Image.LANCZOS,
                       centering=(0.5, 0.42))
    img = ImageOps.autocontrast(img, cutoff=1)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)

    arr = np.asarray(img, dtype=np.float64)
    if smooth > 0:
        arr = _edge_preserving_smooth(arr, strength=smooth)
    if curve > 0:
        arr = _s_curve(arr, amount=curve)

    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    if edge > 0:
        out = out.filter(ImageFilter.UnsharpMask(radius=3, percent=edge, threshold=6))
    return out.convert("1", dither=Image.FLOYDSTEINBERG)


# One 256-byte table beats a 48,000-iteration Python generator: bytes.translate
# runs the inversion in C. Measured 1.8 ms -> 0.02 ms.
_INVERT = bytes(255 - i for i in range(256))


def pack(frame: Image.Image) -> bytes:
    """1-bit image -> packed MSB-first framebuffer where a set bit means ink.

    PIL's mode "1" stores 255 for white, so every bit is inverted relative to
    what the panel wants.
    """
    if frame.size != (PANEL_W, PANEL_H):
        raise ValueError(f"expected {PANEL_W}x{PANEL_H}, got {frame.size}")
    packed = frame.tobytes().translate(_INVERT)
    if len(packed) != FRAME_BYTES:
        raise ValueError(f"expected {FRAME_BYTES} bytes, got {len(packed)}")
    return packed


def to_bmp(payload: bytes) -> bytes:
    """Packed framebuffer -> 1-bit BMP.

    The panel spends most of its waking life decoding. A PNG of dithered noise
    barely compresses -- 43.5 KB against a 48 KB raw frame, about 9% -- yet
    costs an inflate pass and a per-scanline unfilter on a 160 MHz core with no
    PSRAM. A 1-bit BMP is the same pixels with a 62-byte header, so decoding is
    essentially a copy.

    BMP rows are stored bottom-up and padded to 4 bytes. 800 px / 8 = 100 bytes
    per row, which is already a multiple of 4, so no padding is needed here --
    but the rows still have to be reversed.
    """
    row = PANEL_W // 8                      # 100 bytes, already 4-byte aligned
    pixel_bytes = row * PANEL_H
    offset = 14 + 40 + 8                    # file header + DIB + 2-colour palette
    out = bytearray()
    out += b"BM"
    out += (offset + pixel_bytes).to_bytes(4, "little")
    out += b"\0\0\0\0"
    out += offset.to_bytes(4, "little")
    out += (40).to_bytes(4, "little")       # DIB header size
    out += PANEL_W.to_bytes(4, "little", signed=True)
    out += PANEL_H.to_bytes(4, "little", signed=True)
    out += (1).to_bytes(2, "little")        # planes
    out += (1).to_bytes(2, "little")        # bits per pixel
    out += (0).to_bytes(4, "little")        # BI_RGB, uncompressed
    out += pixel_bytes.to_bytes(4, "little")
    out += (2835).to_bytes(4, "little", signed=True)   # ~72 DPI
    out += (2835).to_bytes(4, "little", signed=True)
    out += (2).to_bytes(4, "little")        # colours in palette
    out += (0).to_bytes(4, "little")        # all colours important
    # Palette: index 0 white, index 1 black. `payload` has a set bit meaning
    # ink, so index 1 must be black for the image to read the right way round.
    out += b"\xff\xff\xff\x00" + b"\x00\x00\x00\x00"
    for y in range(PANEL_H - 1, -1, -1):    # bottom-up
        out += payload[y * row:(y + 1) * row]
    return bytes(out)
