# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Brand assets under `brand/`, drawn by `tools/gen_brand.py`.
- A demo image in the README: a synthetic scene beside its one-bit render.
- Issue templates and Dependabot for the GitHub Actions used by CI.

## [0.1.0] - 2026-09-17

### Added
- **Renderer**: landscape filter by EXIF orientation, camera-only filter, busyness scoring over twenty candidates, edge-preserving treatment, BMP, PNG and raw framebuffer output, persisted source and settings, `/wake` protocol that rotates only once the panel has collected the current frame.
- **Firmware**: ESPHome configuration for the Seeed XIAO 7.5" ePaper Panel. One wake a week; sleep interval and OTA window arrive from the renderer; one fetch retry; flash-backed Stay awake switch.
- **Home Assistant integration** `inkframe`: Source (Random, Recent, People, Album, or a person), per-person Include switches, Album select, Recent window, Max busyness, Sleep interval, OTA window, render knobs, Photographs only, Next photo, Preview image, Photo, Busyness, On panel, Last panel fetch, diagnostics.
- CI: renderer tests, generated-docs check, hassfest, HACS validation, ESPHome config validation.

[Unreleased]: https://github.com/CaputoDavide93/InkFrame-Immich/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/CaputoDavide93/InkFrame-Immich/releases/tag/v0.1.0
