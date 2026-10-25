# 🚢 Releasing

Three things ship from this directory, by **three different routes**. A green
deploy moves one of them. Knowing which is the whole content of this page.

| Part | Ships when | Live when |
|---|---|---|
| **Renderer** (`server/src/`, `server/Dockerfile`) | you rebuild the image: `docker compose up -d --build` in `server/` | the container restarts |
| **Integration** (`custom_components/inkframe/`) | a **tagged release** of the public repository, downloaded by HACS | **Home Assistant restarts** |
| **Firmware** (`firmware/`) | never automatically | you flash it, inside the panel's OTA window |

On one occasion the renderer was updated and answered its new
`/albums` route while `button.inkframe_refresh_albums` did not exist in Home
Assistant at all. Both halves of one feature, both correct, one of them live.
That is the normal state between a merge and a release, and it looks exactly
like a broken feature.

## Releasing the integration

1. **Roll the changelog.** `[Unreleased]` becomes `[X.Y.Z] - YYYY-MM-DD`; add
   the compare links at the bottom.
2. **Bump `custom_components/inkframe/manifest.json`.** HACS reads the version
   from there, and shows the update only when it differs from what is installed.
3. Run `make check`, then merge. CI runs the renderer tests, the generated
   docs check, hassfest, HACS validation and the ESPHome config check;
   **that run is the verdict**.
4. Tag and release:
   ```bash
   git tag -a vX.Y.Z -m "InkFrame for Immich vX.Y.Z"
   git push origin vX.Y.Z
   gh release create vX.Y.Z --title "vX.Y.Z" --notes "…"
   ```
   HACS follows releases once a repository has one, so an untagged `main`
   reaches nobody.

## Getting it onto Home Assistant

HACS caches the repository. After a release it still shows the old version
until it re-reads:

```bash
# websocket: hacs/repository/refresh   -> then available_version updates
# websocket: hacs/repository/download  -> writes the files to /config
```

The files land on disk immediately. **They are not loaded.** Python has the old
modules imported, and a config-entry reload is refused, so:

**Restart Home Assistant, then check an entity that only the new version
creates.** Not the version in HACS, not the manifest on disk, an entity:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HA/api/states/button.inkframe_refresh_albums"     # "Entity not found." means it did not load
```

Then press it, and read the renderer's log. A button that exists and does
nothing is the failure this check is for.

## Releasing the renderer alone

Pull, rebuild and restart. Confirm by asking the container:

```bash
docker compose up -d --build
docker compose logs --tail 5
curl -s -H "Authorization: Bearer $TOKEN" http://<renderer>:8099/status | python3 -m json.tool | head
```

A restart does **not** consume a photo or lose the picture: the frame and the
panel's collected generation are both persisted, and start-up keeps a restored
frame rather than rendering a new one.
