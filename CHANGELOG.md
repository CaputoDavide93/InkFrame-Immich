# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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

### Fixed
- **An album with photos reported as empty.** `/api/albums/{id}` returns
  `assetCount` but no `assets` key, so album assets came back empty and the
  renderer blamed the library. They are fetched through `/api/search/metadata`
  with `albumIds` now.
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

[Unreleased]: https://github.com/CaputoDavide93/InkFrame-Immich/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/CaputoDavide93/InkFrame-Immich/releases/tag/v0.1.0
