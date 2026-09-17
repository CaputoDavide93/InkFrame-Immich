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
                   require_camera: bool = True,
                   landscape_only: bool = True) -> list[dict]:
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
                if landscape_only and is_landscape(exif) is not True:
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

    def by_person(self, person_id: str, max_pages: int = 8, landscape_only: bool = True) -> list[dict]:
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
                if (not landscape_only or is_landscape(exif) is True) and has_camera(exif):
                    out.append(asset)
            page = assets.get("nextPage")
        return out

    def recent(self, days: int = 90, max_pages: int = 6, landscape_only: bool = True) -> list[dict]:
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
                if (not landscape_only or is_landscape(exif) is True) and has_camera(exif):
                    out.append(asset)
            page = assets.get("nextPage")
        return out

    def albums(self) -> dict[str, str]:
        """Album name -> id. Empty on this library today; offered anyway so
        the day an album is made it appears without a code change."""
        rows = self._call("/api/albums")
        return {a["albumName"]: a["id"] for a in rows if a.get("albumName")}

    def by_album(self, album_id: str, landscape_only: bool = True,
                 max_pages: int = 8) -> list[dict]:
        """Photographs in one album.

        Via search, NOT `/api/albums/{id}`: that endpoint returns the album's
        metadata and `assetCount` but no `assets` key at all, so reading assets
        from it silently yielded an empty list and the frame reported "no
        landscape photographs" about an album with sixteen in it. Blaming the
        library for a missing key is exactly the kind of error that sends
        somebody looking in the wrong place.

        A curated album is a deliberate choice, so the camera filter is not
        applied here: a scanned picture somebody added on purpose belongs on
        the wall. Orientation still applies, unless portraits are being
        cropped to fit.
        """
        out: list[dict] = []
        page: int | str | None = 1
        while page and int(page) <= max_pages:
            body = {"albumIds": [album_id], "size": 250, "page": int(page),
                    "withExif": True}
            assets = self._call("/api/search/metadata", body).get("assets", {})
            for asset in assets.get("items", []):
                exif = asset.get("exifInfo") or {}
                if landscape_only and is_landscape(exif) is not True:
                    continue
                out.append(asset)
            page = assets.get("nextPage")
        return out

    def faces(self, asset_id: str) -> list[dict]:
        """Face boxes for one asset, in the coordinate space of the ORIGINAL
        image. Immich reports `imageWidth`/`imageHeight` alongside each box so
        the caller can scale them onto whatever rendition it downloaded.

        Never raises: a frame without face data still renders, it just falls
        back to a centred crop. Needs the `face.read` permission on the key.
        """
        try:
            rows = self._call(f"/api/faces?id={asset_id}")
        except Exception as exc:  # noqa: BLE001 - cropping is better than failing
            LOG.warning("faces unavailable for %s: %s", asset_id[:8], exc)
            return []
        return rows if isinstance(rows, list) else []

    def by_search(self, query: str, landscape_only: bool = True,
                  want: int = 120) -> list[dict]:
        """Photographs matching a description, through Immich's CLIP search.

        This is the only way to put the cat on the frame: Immich clusters human
        faces, so a pet has no person to select. "cat" finds him; so do
        "beach", "snow" and "birthday cake".

        Ranked by relevance rather than shuffled, so the pool is trimmed to the
        best `want` matches. Taking everything would let a loose query pull in
        the whole library at the tail end of the ranking, which is how a smart
        search quietly becomes Random.
        """
        out: list[dict] = []
        page: int | str | None = 1
        while page and len(out) < want:
            body = {"query": query, "size": 100, "page": int(page),
                    "withExif": True}
            assets = self._call("/api/search/smart", body).get("assets", {})
            for asset in assets.get("items", []):
                exif = asset.get("exifInfo") or {}
                if landscape_only and is_landscape(exif) is not True:
                    continue
                if not has_camera(exif):
                    continue
                out.append(asset)
            page = assets.get("nextPage")
        return out[:want]

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


def crop_box(img_w: int, img_h: int, faces: list[dict] | None = None,
             aspect: float = PANEL_W / PANEL_H) -> tuple[int, int, int, int]:
    """The 800x480-shaped window to take out of an image.

    With faces, the window is placed so every face fits and their centre of
    mass sits about a third of the way down, which is where a portrait wants
    its subject. Without faces it is a centred crop biased slightly high,
    because heads and horizons both sit above the middle.

    This is what lets a portrait onto a landscape panel at all: scaling one to
    fit would use 45% of the glass, and a plain centre crop of a standing
    person takes their chest.
    """
    if img_w / img_h >= aspect:                      # already wide enough
        box_h = img_h
        box_w = min(img_w, int(round(img_h * aspect)))
    else:
        box_w = img_w
        box_h = min(img_h, int(round(img_w / aspect)))

    if faces:
        # Face boxes arrive in the original image's coordinates; scale them.
        src_w = faces[0].get("imageWidth") or img_w
        src_h = faces[0].get("imageHeight") or img_h
        sx, sy = img_w / src_w, img_h / src_h
        xs1 = [f["boundingBoxX1"] * sx for f in faces if "boundingBoxX1" in f]
        xs2 = [f["boundingBoxX2"] * sx for f in faces if "boundingBoxX2" in f]
        ys1 = [f["boundingBoxY1"] * sy for f in faces if "boundingBoxY1" in f]
        ys2 = [f["boundingBoxY2"] * sy for f in faces if "boundingBoxY2" in f]
        if xs1 and ys1:
            fx = (min(xs1) + max(xs2)) / 2
            fy = (min(ys1) + max(ys2)) / 2
            left = fx - box_w / 2
            # Where to put the face vertically depends on how much of the
            # frame it fills. A small face means a full-body or group shot, and
            # a third of the way down leaves room for the body. A face filling
            # the crop is a close-up, and thirding it pushes the chin out of
            # frame -- seen on a real photo, which is why this is not a
            # constant. Blend between the two rather than switching, so a
            # mid-sized face does not jump.
            face_h = max(ys2) - min(ys1)
            fill = (face_h / box_h) if box_h else 0.0
            # Below 35% of the crop's height the subject has a body worth
            # showing, so the face goes a third down. Above 70% it is a
            # close-up and centring is the only way to keep the chin. In
            # between, slide, so no photo jumps between the two rules.
            ramp = min(1.0, max(0.0, (fill - 0.35) / 0.35))
            placement = (1 / 3) + (0.5 - 1 / 3) * ramp
            top = fy - box_h * placement
            # Widen to contain every face if they are spread out.
            if max(xs2) - min(xs1) < box_w:
                left = min(left, min(xs1))
                left = max(left, max(xs2) - box_w)
            if max(ys2) - min(ys1) < box_h:
                top = min(top, min(ys1))
                top = max(top, max(ys2) - box_h)
            left = int(round(max(0, min(left, img_w - box_w))))
            top = int(round(max(0, min(top, img_h - box_h))))
            return left, top, left + box_w, top + box_h

    left = (img_w - box_w) // 2
    top = int(round((img_h - box_h) * 0.38))         # slightly above centre
    return left, top, left + box_w, top + box_h


def render(img: Image.Image, smooth: float = 0.45, curve: float = 0.35,
           edge: int = 55, contrast: float = 1.05,
           faces: list[dict] | None = None) -> Image.Image:
    """Photo -> 1-bit Floyd-Steinberg frame at exactly 800x480.

    Order matters: crop, autocontrast, flatten texture, push tones off
    mid-grey, restore edges, then dither. Sharpening after dithering would only
    amplify dither noise. An earlier version sharpened before any smoothing and
    turned grass into a field of specks -- the complaint that prompted this.
    """
    img = ImageOps.exif_transpose(img).convert("L")
    # Crop first, then scale. ImageOps.fit would centre a portrait's crop on
    # the middle of the frame, which for a standing subject is their chest.
    img = img.crop(crop_box(img.width, img.height, faces))
    img = img.resize((PANEL_W, PANEL_H), Image.LANCZOS)
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
