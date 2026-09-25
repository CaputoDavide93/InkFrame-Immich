# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.1] - 2026-09-25

### Changed
- **Up next is a preview.** After the panel collects a photo, the renderer
  renders the next one straight away and holds it for the scheduled draw, so
  *Up next* shows the photo that will actually go up instead of repeating the
  one on the panel. A held preview goes up only at the scheduled draw; a photo
  asked for with *New photo now* still goes up at the next check. The
  `Up next` image gains a `preview` attribute, and `/status` publishes
  `next_is_preview`.

## [0.3.0] - 2026-09-24

### Added
- **Check often, draw rarely.** The panel wakes every *Sleep interval* hours
  only to ask whether a new photo is due (about seven seconds awake), and
  draws a new one every *Photo every* days at *Photo hour* (about thirty-five
  seconds). `docs/wake-and-sleep.md` explains the two cadences.
- **Photo every** and **Photo hour** settings, so the photo cadence is
  controlled separately from the wake interval.
- **Last check-in** sensor: when the panel last woke, including checks that
  drew nothing. This is the heartbeat; *Last panel fetch* is the last draw.
- **Next photo** sensor: when the next new photo is due. The renderer's
  `/status` publishes it as `next_refresh_at`.

### Fixed
- **A failed people count retries** instead of waiting a day. A renderer that
  started before Immich was listening used to report no eligible people, and
  offer no *Include* switches, until the next daily count.
- **The panel sleeps for the interval you set**, not a fixed week.
- **The firmware example secrets list `inkframe_token`**, so the firmware
  validates when set up from the example.
- **The renderer no longer runs as root.** The image runs as uid 1000, as the
  documentation already said. A `immich-frame-volume-init` one-shot in
  `docker-compose.yml` chowns an existing state volume in place before the
  renderer starts, so a volume created by an earlier release keeps its saved
  source choice; a fresh volume inherits the right owner from the image.

## [0.2.1] - 2026-09-18

### Fixed
- **Renderer access is authenticated.** Every frame, wake, source, settings
  and status request now needs a shared bearer token. Docker liveness remains
  public but exposes no photo or source data. The ESPHome panel and Home
  Assistant integration send the token in an `Authorization` header.
- **Invalid Album/Search selections are no longer offered.** Their dedicated
  Album and Search controls first collect a value, then switch source; clearing
  an active search returns safely to Random instead of issuing an invalid
  empty search.
- **The Source entity no longer crashes while building its options.** Album
  and Search values are read from the coordinator before they are considered.
- **Existing integrations can upgrade to authentication.** Pre-token entries
  migrate safely and expose Home Assistant's Reconfigure action for the token,
  instead of failing with a missing-key exception.
- **Photographs only now means every source.** Person, People, Album, Recent
  and Search honour the same camera-EXIF setting as Random.
- **A recovered renderer clears its old error.** A successful render no longer
  leaves a historic failure looking current in Home Assistant diagnostics.
- **The nursery dashboard now reports actual playback, not merely page JavaScript.** A kiosk
  heartbeat advances only when the baby camera's video time advances. The
  page detects a player that never starts as well as a frozen frame, remounts
  it locally, then permits at most three HA page refreshes if playback stays
  stale; a confirmed playback heartbeat refills the budget.

## [0.2.0] - 2026-09-18

### Added
- **A Search source.** Immich's CLIP search picks photos by description, so
  `cat` puts the family pet on the frame -- face recognition clusters people,
  and a pet has no person to select. `beach` and `snow` work the same way.
  Paired with a **Search for** text entity in Home Assistant.
- **Portraits are cropped instead of skipped.** The 800x480 window is placed on
  the faces Immich detected, a third down for a full-body shot and centred for
  a close-up. Needs `face.read` on the API key; without it the crop falls back
  to centred and nothing breaks. Controlled by `landscape_only`.
- **Two previews in Home Assistant**: `On the panel` (what the panel fetched)
  and `Up next` (the newest render). They differ from the moment a photo is
  rendered until the panel next wakes, which on a weekly cycle is days.
- `/preview.png?gen=N` and `/frame.*?gen=N` serve one specific generation.
- The last frame is saved to `/data`, with whether the panel had collected it.
- Brand assets under `brand/`, drawn by `tools/gen_brand.py`.
- A demo image in the README: a synthetic scene beside its one-bit render.
- Issue templates and Dependabot for the GitHub Actions used by CI.
- **A `Refresh albums` button.** The album picker is filled from a cache the
  renderer rebuilds once a day beside the per-person counts, so an album made
  this afternoon was absent from Home Assistant until tomorrow -- while
  rendering, which reads Immich live, would have used it happily. `GET /albums`
  now writes what it read back into that cache, and the button reaches it.

### Fixed
- **An album with photos reported as empty.** `/api/albums/{id}` returns
  `assetCount` but no `assets` key, so album assets came back empty and the
  renderer blamed the library. They are fetched through `/api/search/metadata`
  with `albumIds` now.
- **A restart blanked `On the panel`** whenever a newer photo had been
  rendered since the panel collected one: only the newest frame was saved, so
  the collected picture was lost and the card had nothing to show until the
  next wake, up to three days later. The panel's frame now has its own slot.
- **A restart lost the picture**, leaving every image route answering 500 until
  something rendered, which with a source that had run dry was indefinitely.
- **A restart consumed a photo.** Start-up keeps a restored frame rather than
  rendering, so a weekly frame no longer rotates per rebuild.
- **An unheld generation returned 200 with a different photo.** Asking for one
  by number is a 404 when it is gone, so a card captioned `On the panel` can
  never show something that is not.
- The panel's collected-frame record survives a renderer restart, so
  `On the panel` no longer goes unknown after a rebuild.
- Configuration is validated in `main()` rather than at import, so the module
  can be imported by a test.

## [0.1.0] - 2026-09-17

### Added
- **Renderer**: landscape filter by EXIF orientation, camera-only filter, busyness scoring over twenty candidates, edge-preserving treatment, BMP, PNG and raw framebuffer output, persisted source and settings, `/wake` protocol that rotates only once the panel has collected the current frame.
- **Firmware**: ESPHome configuration for the Seeed XIAO 7.5" ePaper Panel. One wake a week; sleep interval and OTA window arrive from the renderer; one fetch retry; flash-backed Stay awake switch.
- **Home Assistant integration** `inkframe`: Source (Random, Recent, People, Album, or a person), per-person Include switches, Album select, Recent window, Max busyness, Sleep interval, OTA window, render knobs, Photographs only, Next photo, Preview image, Photo, Busyness, On panel, Last panel fetch, diagnostics.
- CI: renderer tests, generated-docs check, hassfest, HACS validation, ESPHome config validation.

[Unreleased]: https://github.com/CaputoDavide93/InkFrame-Immich/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/CaputoDavide93/InkFrame-Immich/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/CaputoDavide93/InkFrame-Immich/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/CaputoDavide93/InkFrame-Immich/releases/tag/v0.1.0
