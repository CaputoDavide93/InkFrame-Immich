#!/usr/bin/env python3
"""Regenerate the inventory tables in the docs from the code.

Hand-typed tables drift. Three of them here have a machine source of truth:

  env       every os.environ.get(...) in server/src/app.py
  settings  SETTING_SPEC in server/src/app.py
  endpoints every `if path == "/x"` route in the handler, described below

Each lands between <!-- AUTOGEN:name --> and <!-- /AUTOGEN:name --> markers.
`--check` exits 1 if any file would change, for CI.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "server" / "src" / "app.py"
if not APP.exists():  # running inside the source monorepo, before export
    APP = ROOT / "src" / "app.py"

TARGETS = [ROOT / "README.md", ROOT / "docs" / "api.md"]

# Endpoint descriptions are prose and stay hand-written -- but a route with no
# description, or a description for a route that no longer exists, fails the
# build. That is the drift guard.
ENDPOINTS = {
    "/healthz": "Liveness. Carries `generation`, which setup uses to tell a renderer from any other listener",
    "/status": "Everything in one document: current photo, source, settings, people, `on_panel`, `last_error`",
    "/wake": "**The panel's one call per wake.** Rotates only if the current frame was already collected; returns `sleep_seconds` and `ota_window_seconds`",
    "/next": "Render a new photo now. Home Assistant's button. The panel never calls this",
    "/frame.bmp": "The current frame as a 1-bit BMP. **Marks the frame as collected**",
    "/frame.png": "The current frame as a 1-bit PNG. **Marks the frame as collected**",
    "/frame.bin": "Raw 48,000-byte framebuffer, `?gen=&offset=&len=` for strip fetching. **Marks the frame as collected**",
    "/preview.png": "The same frame for humans and for Home Assistant. Does **not** mark it as collected",
    "/source": "Read or set where photos come from. Persisted",
    "/settings": "Read or set runtime settings. Validated; persisted",
    "/people": "Named faces with landscape counts and `eligible`",
    "/albums": "Album names, read live. Also refreshes the cache `/status` serves",
}

ENV_NOTES = {
    "IMMICH_URL": "Your Immich server",
    "IMMICH_API_KEY_FILE": "Path to a file holding the API key (preferred)",
    "IMMICH_API_KEY": "The API key inline, for quick tests",
    "LISTEN_HOST": "Bind address",
    "LISTEN_PORT": "Port",
    "STATE_FILE": "Where the source and settings persist",
    "RECENT_MEMORY": "Photos not shown again until this many others have been",
    "MIN_PERSON_PHOTOS": "A person is offered as a source only above this many landscape photographs",
    "PEOPLE_RECOUNT_SECONDS": "How often the per-person counts refresh",
    "RENDER_SMOOTH": "Default for `smooth`",
    "RENDER_CURVE": "Default for `curve`",
    "RENDER_EDGE": "Default for `edge`",
    "RENDER_CONTRAST": "Default for `contrast` (not exposed in Home Assistant)",
    "CANDIDATES": "Default for `candidates` (not exposed in Home Assistant)",
    "MAX_BUSYNESS": "Default for `max_busyness`",
    "REQUIRE_CAMERA": "Default for `require_camera`; `0` to allow non-camera images",
    "LANDSCAPE_ONLY": "Default for `landscape_only`; `0` to crop portraits instead of skipping them",
    "SLEEP_HOURS": "Default for `sleep_hours`",
    "OTA_WINDOW_SECONDS": "Default for `ota_window_seconds`",
    "HEARTBEAT_FILE": "Touched every 30 s; for external liveness checks",
    "LAST_OK_FILE": "Touched after every successful render",
    "LOG_LEVEL": "Python logging level",
}

SETTING_NOTES = {
    "smooth": "Edge-preserving texture flattening before dithering",
    "curve": "How hard tones are pushed away from mid-grey",
    "edge": "Unsharp mask percent applied after smoothing",
    "contrast": "Global contrast. Overlaps `curve`; not exposed in Home Assistant",
    "candidates": "Photos downloaded and scored per pick. Not exposed in Home Assistant",
    "max_busyness": "Reject anything scoring above this",
    "require_camera": "Only assets with a camera make in EXIF",
    "landscape_only": "Skip portraits. Off means they are cropped to fit, with the window placed on the faces Immich found",
    "sleep_hours": "Delivered to the panel on `/wake`",
    "ota_window_seconds": "Delivered to the panel on `/wake`",
}
HA_EXPOSED = {"smooth", "curve", "edge", "max_busyness", "require_camera",
              "landscape_only", "sleep_hours", "ota_window_seconds"}


def env_table(source: str) -> str:
    """Every os.environ.get(NAME[, default]) call, via the AST so that a default
    written as an expression (str(24 * 3600)) is seen, not just string literals."""
    found: dict[str, str] = {}
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and ast.unparse(node.func.value) == "os.environ"):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        name = node.args[0].value
        default = ""
        if len(node.args) > 1:
            try:
                default = str(ast.literal_eval(node.args[1]))
            except ValueError:
                try:
                    default = str(eval(ast.unparse(node.args[1]), {"__builtins__": {"str": str}}))
                except Exception:  # noqa: BLE001 - show the expression rather than guess
                    default = ast.unparse(node.args[1])
        found.setdefault(name, default)
    missing = sorted(set(found) - set(ENV_NOTES))
    if missing:
        sys.exit(f"gen_docs: env vars read by the code with no description: {missing}")
    stale = sorted(set(ENV_NOTES) - set(found))
    if stale:
        sys.exit(f"gen_docs: described env vars the code no longer reads: {stale}")
    rows = ["| Variable | Purpose | Default |", "|---|---|---|"]
    for name in ENV_NOTES:  # documented order
        default = found[name]
        rows.append(f"| `{name}` | {ENV_NOTES[name]} | `{default}` |" if default else
                    f"| `{name}` | {ENV_NOTES[name]} | |")
    return "\n".join(rows)


def settings_table(source: str) -> str:
    tree = ast.parse(source)
    spec = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "SETTING_SPEC":
            spec = node.value
    if spec is None:
        sys.exit("gen_docs: SETTING_SPEC not found")
    rows = ["| Setting | Type | Range | Purpose | HA |", "|---|---|---|---|---|"]
    keys = []
    for key_node, val in zip(spec.keys, spec.values):
        key = key_node.value
        keys.append(key)
        kind = val.elts[0].id
        lo, hi = (ast.literal_eval(val.elts[1]), ast.literal_eval(val.elts[2]))
        rng = "on / off" if kind == "bool" else f"{lo} to {hi}"
        if key not in SETTING_NOTES:
            sys.exit(f"gen_docs: setting {key!r} has no description")
        rows.append(f"| `{key}` | {kind} | {rng} | {SETTING_NOTES[key]} | "
                    f"{'✅' if key in HA_EXPOSED else ''} |")
    stale = sorted(set(SETTING_NOTES) - set(keys))
    if stale:
        sys.exit(f"gen_docs: described settings that no longer exist: {stale}")
    return "\n".join(rows)


def endpoints_table(source: str) -> str:
    routes = set(re.findall(r'if path == "(/[a-z._]+)"', source))
    for group in re.findall(r'if path in \(([^)]*)\)', source):
        routes.update(re.findall(r'"(/[a-z._]+)"', group))
    missing = sorted(routes - set(ENDPOINTS))
    if missing:
        sys.exit(f"gen_docs: routes with no description: {missing}")
    stale = sorted(set(ENDPOINTS) - routes)
    if stale:
        sys.exit(f"gen_docs: described routes that no longer exist: {stale}")
    rows = ["| Path | Purpose |", "|---|---|"]
    for path in ENDPOINTS:  # documented order
        rows.append(f"| `GET {path}` | {ENDPOINTS[path]} |")
    return "\n".join(rows)


def splice(text: str, name: str, body: str) -> str:
    start, end = f"<!-- AUTOGEN:{name} -->", f"<!-- /AUTOGEN:{name} -->"
    if start not in text:
        return text
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    return f"{head}{start}\n{body}\n{end}{tail}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="exit 1 if anything is stale")
    args = parser.parse_args()

    source = APP.read_text()
    tables = {"env": env_table(source), "settings": settings_table(source),
              "endpoints": endpoints_table(source)}
    changed = []
    for target in TARGETS:
        if not target.exists():
            continue
        before = target.read_text()
        after = before
        for name, body in tables.items():
            after = splice(after, name, body)
        if after != before:
            changed.append(target)
            if not args.check:
                target.write_text(after)
    if args.check and changed:
        print("stale generated tables in: " + ", ".join(str(p.relative_to(ROOT)) for p in changed))
        print("run: python tools/gen_docs.py")
        return 1
    print("docs up to date" if not changed else
          "regenerated: " + ", ".join(str(p.relative_to(ROOT)) for p in changed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
