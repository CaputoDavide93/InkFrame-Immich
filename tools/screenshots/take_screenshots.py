#!/usr/bin/env python3
"""Take the README and setup screenshots from the real software, on demo data.

    make screenshots                 # builds .venv-screenshots on first use
    .venv-screenshots/bin/python tools/screenshots/take_screenshots.py [--keep] [--only a,b]

1. Starts a stand-in Immich (fake_immich.py: thirty drawn scenes, no photos).
2. Starts the real renderer (src/app.py) against it, on localhost, with a
   temporary state directory, and plays one panel wake and acknowledgement so
   the renderer has a frame on the glass and a different one waiting.
3. Starts a real Home Assistant (the version pinned in requirements.txt) in a
   temporary config directory with this repository's `inkframe` integration,
   completes onboarding through its API, and photographs the setup form, the
   created device and the entities in Chromium (Playwright), light and dark.
4. Photographs the renderer's own frame, in a bezel, light and dark.

Every image is docs/assets/screenshots/<screen>-{light,dark}.png, re-saved
without metadata. The data is demo data only: addresses are 192.0.2.x, the
token is a placeholder and the photographs are drawings.
Nothing outside the temporary directory is touched; --keep leaves it behind.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import aiohttp  # noqa: E402
import fake_immich  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from playwright.async_api import Locator, Page, async_playwright  # noqa: E402

SRC = ROOT / "server" / "src"
if not SRC.exists():
    SRC = ROOT / "src"
OUT = ROOT / "docs" / "assets" / "screenshots"
VIEWPORT = {"width": 1280, "height": 900}
SCALE = 2
THEMES = ("light", "dark")
USER = {"name": "Demo", "username": "demo", "password": "demo-password-0000"}
TOKEN = "demo-token-not-a-secret"
SHOWN_URL = "http://192.0.2.20:8099"  # what the form shows; the real one is localhost

CONFIGURATION = """\
homeassistant:
  name: Home
  unit_system: metric
  time_zone: UTC
  currency: EUR
  country: NL
  latitude: 52.37
  longitude: 4.89
  elevation: 0
http:
  server_host: 127.0.0.1
  server_port: {port}
frontend:
config:
history:
logger:
  default: warning
"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def renderer_call(base: str, path: str, method: str = "GET", raw: bool = False):
    request = urllib.request.Request(
        base + path, method=method, headers={"Authorization": f"Bearer {TOKEN}"},
        data=b"" if method == "POST" else None)
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read()
    return body if raw else json.loads(body)


def start_renderer(work: Path, immich_port: int, port: int) -> subprocess.Popen:
    env = {
        **os.environ,
        "IMMICH_URL": f"http://127.0.0.1:{immich_port}",
        "IMMICH_API_KEY": "demo-key",
        "INKFRAME_TOKEN": TOKEN,
        "LISTEN_HOST": "127.0.0.1",
        "LISTEN_PORT": str(port),
        "STATE_FILE": str(work / "data" / "state.json"),
        "HEARTBEAT_FILE": str(work / "heartbeat"),
        "LAST_OK_FILE": str(work / "render-ok"),
        "MIN_PERSON_PHOTOS": "5",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    (work / "data").mkdir()
    log = (work / "renderer.out").open("w")
    return subprocess.Popen([sys.executable, str(SRC / "app.py")], cwd=SRC, env=env,
                            stdout=log, stderr=subprocess.STDOUT)


def wait_for(url: str, proc: subprocess.Popen, seconds: int = 120) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"{url}: the process exited; see its log")
        try:
            urllib.request.urlopen(url, timeout=3).read()
            return
        except OSError:
            time.sleep(0.5)
    raise SystemExit(f"{url} did not answer within {seconds} seconds")


def play_a_panel(base: str) -> None:
    """One wake, one download, one acknowledgement; then a newer render waits.

    The same calls the firmware makes, so `On the panel` has a picture and
    `Up next` has a different one.
    """
    wake = renderer_call(base, "/wake")
    generation = wake["generation"]
    renderer_call(base, f"/frame.bmp?gen={generation}", raw=True)
    renderer_call(base, f"/frame/ack?gen={generation}", method="POST")
    renderer_call(base, "/next")


def prepare_home_assistant(config: Path, port: int) -> None:
    (config / "configuration.yaml").write_text(CONFIGURATION.format(port=port))
    storage = config / ".storage"
    storage.mkdir()
    (storage / "onboarding").write_text(json.dumps({
        "version": 4, "minor_version": 1, "key": "onboarding",
        "data": {"done": ["core_config", "analytics", "integration"]},
    }))
    (config / "custom_components").mkdir()
    shutil.copytree(ROOT / "custom_components" / "inkframe",
                    config / "custom_components" / "inkframe",
                    ignore=shutil.ignore_patterns("__pycache__"))


async def wait_for_http(session: aiohttp.ClientSession, base: str, proc) -> None:
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit("Home Assistant exited during start-up; see its log")
        try:
            async with session.get(f"{base}/api/onboarding") as resp:
                if resp.status == 200:
                    return
        except aiohttp.ClientError:
            pass
        await asyncio.sleep(1)
    raise SystemExit("Home Assistant did not start within five minutes")


async def onboard(session: aiohttp.ClientSession, base: str) -> dict:
    client_id = f"{base}/"
    async with session.post(f"{base}/api/onboarding/users",
                            json={**USER, "client_id": client_id, "language": "en"}) as resp:
        resp.raise_for_status()
        code = (await resp.json())["auth_code"]
    async with session.post(f"{base}/auth/token",
                            data={"grant_type": "authorization_code", "code": code,
                                  "client_id": client_id}) as resp:
        resp.raise_for_status()
        tokens = await resp.json()
    return {**tokens, "hassUrl": base, "clientId": client_id,
            "expires": int(time.time() * 1000) + tokens["expires_in"] * 1000}


async def settle(session: aiohttp.ClientSession, base: str, token: str) -> None:
    """Wait for start-up, keep the HTTP settings for good, and dismiss the
    repairs that only say YAML is deprecated, so nothing unrelated reaches a
    picture."""
    async with session.ws_connect(f"{base}/api/websocket") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        if (await ws.receive_json())["type"] != "auth_ok":
            raise SystemExit("websocket authentication failed")
        ids = iter(range(1, 1_000_000))

        async def call(message: dict):
            await ws.send_json({"id": next(ids), **message})
            reply = await ws.receive_json()
            if not reply.get("success"):
                raise SystemExit(f"{message['type']} failed: {reply}")
            return reply["result"]

        for _ in range(600):
            if (await call({"type": "get_config"}))["state"] == "RUNNING":
                break
            await asyncio.sleep(1)
        else:
            raise SystemExit("Home Assistant did not finish starting")
        await call({"type": "http/config/promote"})
        for issue in (await call({"type": "repairs/list_issues"}))["issues"]:
            await call({"type": "repairs/ignore_issue", "domain": issue["domain"],
                        "issue_id": issue["issue_id"], "ignore": True})


# ── pictures ──────────────────────────────────────────────────────────────────
def strip_metadata(path: Path, radius: float = 0, quantise: bool = True) -> None:
    """Re-save the PNG with pixels only, and quantised to 256 colours (flat
    interface colours lose nothing visible and the file shrinks to a third).
    With a radius, the corners outside a dialog's rounded edge are transparent."""
    with Image.open(path) as image:
        pixels = image.convert("RGBA" if radius else "RGB")
    if radius:
        mask = Image.new("L", pixels.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, pixels.width - 1, pixels.height - 1), radius=radius * SCALE, fill=255)
        pixels.putalpha(mask)
    if quantise:
        pixels = pixels.quantize(
            256, method=Image.Quantize.FASTOCTREE if radius else Image.Quantize.MEDIANCUT,
            dither=Image.Dither.NONE)
    buffer = io.BytesIO()
    pixels.save(buffer, format="PNG", optimize=True)
    path.write_bytes(buffer.getvalue())


class Camera:
    def __init__(self, page: Page, only: set[str] | None) -> None:
        self.page = page
        self.only = only
        self.taken: list[Path] = []

    async def theme(self, name: str) -> None:
        await self.page.emulate_media(color_scheme=name)
        await self.page.wait_for_timeout(600)

    async def shoot(self, name: str, target: Locator | None = None, quantise: bool = True) -> None:
        """<name>-light.png and <name>-dark.png, of a dialog or the viewport."""
        if self.only and name not in self.only:
            return
        for theme in THEMES:
            await self.theme(theme)
            path = OUT / f"{name}-{theme}.png"
            radius = 0.0
            if target is None:
                await self.page.screenshot(path=path, animations="disabled")
            else:
                radius = await target.evaluate(
                    "e => parseFloat(getComputedStyle(e).borderTopLeftRadius) || 0")
                box = await target.bounding_box()
                if box is None:
                    raise SystemExit(f"{name}: nothing to photograph")
                await self.page.screenshot(path=path, clip=box, animations="disabled")
            strip_metadata(path, radius, quantise)
            self.taken.append(path)
            print(f"  {path.relative_to(ROOT)}")
        await self.theme("light")


def dialog(page: Page, host: str = "dialog-data-entry-flow") -> Locator:
    return page.locator(f"{host} ha-dialog wa-dialog dialog.dialog").first


async def call_ws(page: Page, message: dict):
    return await page.evaluate(
        "m => document.querySelector('home-assistant').hass.callWS(m)", message)


FRAME_PAGE = """<!doctype html><meta charset=utf-8>
<style>
:root{{--bg:#f4f1ea;--bezel:#1a1a1a;--ink:#1a1a1a;--muted:#7a746a}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16171a;--bezel:#2b2d31;--ink:#ecebe7;--muted:#9a978f}}}}
body{{margin:0;background:var(--bg);font:15px -apple-system,Helvetica,Arial,sans-serif;color:var(--ink);
  display:flex;align-items:center;justify-content:center;height:100vh}}
figure{{margin:0;text-align:center}}
.bezel{{background:var(--bezel);padding:34px 34px 46px;border-radius:22px;
  box-shadow:0 18px 40px rgba(0,0,0,.28)}}
img{{display:block;width:800px;height:480px;image-rendering:pixelated;background:#fff}}
figcaption{{margin-top:22px;color:var(--muted)}}
</style>
<figure><div class=bezel><img src="data:image/png;base64,{data}" alt=""></div>
<figcaption>The renderer's frame: 800 x 480, one bit, as the panel receives it</figcaption></figure>"""


async def shoot_frame(page: Page, camera: Camera, renderer: str) -> None:
    png = renderer_call(renderer, "/frame.png", raw=True)
    await page.set_viewport_size({"width": 1000, "height": 680})
    await page.set_content(FRAME_PAGE.format(data=base64.b64encode(png).decode()))
    await page.wait_for_timeout(500)
    await camera.shoot("frame", quantise=False)


async def shoot_home_assistant(page: Page, camera: Camera, base: str, renderer: str) -> None:
    await page.set_viewport_size(VIEWPORT)
    await page.goto(f"{base}/config/integrations/dashboard/add?domain=inkframe")
    await page.get_by_text("Do you want to set up InkFrame for Immich?").wait_for(timeout=60000)
    await page.get_by_role("button", name="OK", exact=True).click()
    url = page.get_by_role("textbox", name="Renderer URL")
    token = page.get_by_role("textbox", name="Renderer token")
    await url.wait_for(timeout=60000)
    await url.fill(SHOWN_URL)
    await token.fill(TOKEN)
    await page.get_by_text("The renderer that prepares photos").click()  # drop the selection
    await page.wait_for_timeout(800)
    await camera.shoot("setup-form", dialog(page))
    await url.fill(renderer)
    await page.get_by_role("button", name="Submit", exact=True).click()
    await page.get_by_text("Name and assign").wait_for(timeout=60000)
    await page.wait_for_timeout(1500)
    await camera.shoot("setup-created", dialog(page))
    for name in ("Finish", "Skip and finish"):
        button = page.get_by_role("button", name=name, exact=True)
        if await button.count():
            await button.last.click()
            break

    devices = await call_ws(page, {"type": "config/device_registry/list"})
    device = next(d for d in devices if any(i[0] == "inkframe" for i in d["identifiers"]))
    await page.set_viewport_size({"width": VIEWPORT["width"], "height": 2100})
    await page.goto(f"{base}/config/devices/device/{device['id']}")
    await page.get_by_text(device["name_by_user"] or device["name"], exact=True).first.wait_for(timeout=60000)
    await page.wait_for_timeout(4000)
    await camera.shoot("device")
    await page.set_viewport_size(VIEWPORT)


async def run(args: argparse.Namespace) -> None:
    only = set(args.only.split(",")) if args.only else None
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="inkframe-screens-"))
    config = work / "ha"
    config.mkdir()
    ha_port, renderer_port = free_port(), free_port()
    base = f"http://127.0.0.1:{ha_port}"
    renderer = f"http://127.0.0.1:{renderer_port}"
    print(f"working in {work}")

    immich = fake_immich.serve(free_port())
    renderer_proc = start_renderer(work, immich.server_address[1], renderer_port)
    prepare_home_assistant(config, ha_port)
    hass_log = (config / "hass.out").open("w")
    hass = subprocess.Popen([sys.executable, "-m", "homeassistant", "--config", str(config)],
                            stdout=hass_log, stderr=subprocess.STDOUT, cwd=config,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    try:
        wait_for(f"{renderer}/healthz", renderer_proc)
        play_a_panel(renderer)
        async with aiohttp.ClientSession() as session:
            await wait_for_http(session, base, hass)
            tokens = await onboard(session, base)
            await settle(session, base, tokens["access_token"])
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            context = await browser.new_context(
                viewport=VIEWPORT, device_scale_factor=SCALE, locale="en-GB",
                timezone_id="UTC", color_scheme="light")
            await context.add_init_script(
                f"localStorage.setItem('hassTokens', {json.dumps(json.dumps(tokens))});")
            page = await context.new_page()
            camera = Camera(page, only)
            try:
                await shoot_home_assistant(page, camera, base, renderer)
            except BaseException:
                await page.screenshot(path=work / "failure.png")
                print(f"the page at the failure: {work / 'failure.png'}")
                raise
            await shoot_frame(page, camera, renderer)
            await browser.close()
        print(f"{len(camera.taken)} screenshots in {OUT.relative_to(ROOT)}")
    finally:
        for proc in (hass, renderer_proc):
            proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(30)
            if proc.poll() is None:
                proc.kill()
        immich.shutdown()
        hass_log.close()
        if args.keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", action="store_true", help="keep the temporary directory")
    parser.add_argument("--only", help="comma-separated screen names to (re)take")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
