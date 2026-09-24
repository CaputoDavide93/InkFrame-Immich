# 🔌 Renderer API

Plain HTTP, JSON in and out, no authentication. See [SECURITY.md](../SECURITY.md).

## Endpoints

<!-- AUTOGEN:endpoints -->
| Path | Purpose |
|---|---|
| `GET /healthz` | Unauthenticated liveness only; carries `generation` but no photo or state |
| `GET /status` | Bearer-authenticated state: current photo, source, settings, people, `on_panel`, `last_error` |
| `GET /wake` | **The panel's one call per wake.** Rotates only if the current frame was already collected; returns `sleep_seconds` and `ota_window_seconds` |
| `GET /next` | Render a new photo now. Home Assistant's button. The panel never calls this |
| `GET /frame.bmp` | The current frame as a 1-bit BMP. **Marks the frame as collected** |
| `GET /frame.png` | The current frame as a 1-bit PNG. **Marks the frame as collected** |
| `GET /frame.bin` | Raw 48,000-byte framebuffer, `?gen=&offset=&len=` for strip fetching. **Marks the frame as collected** |
| `GET /preview.png` | The same frame for humans and for Home Assistant. Does **not** mark it as collected |
| `GET /source` | Read or set where photos come from. Persisted |
| `GET /settings` | Read or set runtime settings. Validated; persisted |
| `GET /people` | Named faces with landscape counts and `eligible` |
| `GET /albums` | Album names, read live. Also refreshes the cache `/status` serves |
<!-- /AUTOGEN:endpoints -->

## Settings

Runtime settings, readable and writable through `/settings`, persisted in the state file. Out-of-range values and unknown keys are refused with 400 rather than dropped, so a typo in a caller is an error and not a silent no-op.

<!-- AUTOGEN:settings -->
| Setting | Type | Range | Purpose | HA |
|---|---|---|---|---|
| `smooth` | float | 0.0 to 1.0 | Edge-preserving texture flattening before dithering | ✅ |
| `curve` | float | 0.0 to 1.0 | How hard tones are pushed away from mid-grey | ✅ |
| `edge` | int | 0 to 200 | Unsharp mask percent applied after smoothing | ✅ |
| `contrast` | float | 0.5 to 2.0 | Global contrast. Overlaps `curve`; not exposed in Home Assistant |  |
| `candidates` | int | 1 to 60 | Photos downloaded and scored per pick. Not exposed in Home Assistant |  |
| `max_busyness` | float | 1.0 to 100.0 | Reject anything scoring above this | ✅ |
| `require_camera` | bool | on / off | Only assets with a camera make in EXIF | ✅ |
| `landscape_only` | bool | on / off | Skip portraits. Off means they are cropped to fit, with the window placed on the faces Immich found | ✅ |
| `sleep_hours` | float | 1 to 336 | Delivered to the panel on `/wake` | ✅ |
| `ota_window_seconds` | int | 5 to 300 | Delivered to the panel on `/wake` | ✅ |
| `refresh_days` | int | 1 to 30 | How often the picture on the glass actually changes. Most wakes only CHECK (~7s); a draw is ~35s | ✅ |
| `refresh_hour` | int | 0 to 23 | Local hour for the scheduled draw. The first check at or after it, never an exact alarm | ✅ |
<!-- /AUTOGEN:settings -->

## Environment variables

Defaults for a fresh install. A value set through `/settings` is persisted and wins over the environment from then on.

<!-- AUTOGEN:env -->
| Variable | Purpose | Default |
|---|---|---|
| `IMMICH_URL` | Your Immich server | |
| `IMMICH_API_KEY_FILE` | Path to a file holding the API key (preferred) | |
| `IMMICH_API_KEY` | The API key inline, for quick tests | |
| `INKFRAME_TOKEN_FILE` | Path to the shared panel/Home Assistant bearer token (preferred) | |
| `INKFRAME_TOKEN` | The renderer token inline, for local tests only | |
| `LISTEN_HOST` | Bind address | `0.0.0.0` |
| `LISTEN_PORT` | Port | `8099` |
| `STATE_FILE` | Where the source and settings persist | `/data/state.json` |
| `RECENT_MEMORY` | Photos not shown again until this many others have been | `120` |
| `MIN_PERSON_PHOTOS` | A person is offered as a source only above this many landscape photographs | `20` |
| `PEOPLE_RECOUNT_SECONDS` | How often the per-person counts refresh | `86400` |
| `RENDER_SMOOTH` | Default for `smooth` | `0.45` |
| `RENDER_CURVE` | Default for `curve` | `0.35` |
| `RENDER_EDGE` | Default for `edge` | `55` |
| `RENDER_CONTRAST` | Default for `contrast` (not exposed in Home Assistant) | `1.05` |
| `CANDIDATES` | Default for `candidates` (not exposed in Home Assistant) | `20` |
| `MAX_BUSYNESS` | Default for `max_busyness` | `22` |
| `REQUIRE_CAMERA` | Default for `require_camera`; `0` to allow non-camera images | `1` |
| `LANDSCAPE_ONLY` | Default for `landscape_only`; `0` to crop portraits instead of skipping them | `1` |
| `SLEEP_HOURS` | Default for `sleep_hours` | `168` |
| `OTA_WINDOW_SECONDS` | Default for `ota_window_seconds` | `20` |
| `REFRESH_DAYS` | Default for `refresh_days` | `3` |
| `REFRESH_HOUR` | Default for `refresh_hour` | `7` |
| `HEARTBEAT_FILE` | Touched every 30 s; for external liveness checks | `/tmp/immichframe-heartbeat` |
| `LAST_OK_FILE` | Touched after every successful render | `/tmp/immichframe-render-ok` |
| `LOG_LEVEL` | Python logging level | `INFO` |
<!-- /AUTOGEN:env -->

## Source

`GET /source` returns the current selection; add query parameters to change it.

| Parameter | Values |
|---|---|
| `mode` | `random`, `person`, `people`, `recent`, `album`, `search` |
| `person` | a named face, for `person` |
| `people` | comma-separated names, for `people`. Photos of any of them |
| `album` | an album name, for `album` |
| `query` | a description, for `search`. Ranked by Immich's CLIP search |
| `days` | window for `recent` |

The people list and the album are remembered across mode changes, so switching to People or Album brings back the last choice.

## Status

`GET /status` is one document with everything Home Assistant needs, so no two entities can disagree about which generation they describe:

```json
{
  "generation": 12,
  "current": {
    "asset_id": "…", "name": "IMG_0197.heic", "taken": "2026-05-06T11:34:08Z",
    "busyness": 6.3, "source": "people:A,B",
    "candidates_scored": 20, "candidates_too_busy": 3,
    "settings": { "...": "as rendered" },
    "rendered_at": 1789594193.09, "render_seconds": 0.05
  },
  "source": "people:A,B",
  "source_people": ["A", "B"], "source_album": "", "source_days": 90,
  "on_panel": false,
  "panel_fetched_generation": 11, "panel_fetched_at": 1789500000.0,
  "settings": { "...": "live" },
  "people": { "A": { "landscape": 92, "eligible": true }, "...": {} },
  "albums": [],
  "recent_count": 12,
  "last_error": null
}
```
