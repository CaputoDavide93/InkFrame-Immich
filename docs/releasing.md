# 🚢 Releasing

Three things ship from this directory, by **three different routes**. A green
deploy moves one of them. Knowing which is the whole content of this page.

| Part | Ships when | Live when |
|---|---|---|
| **Renderer** (`src/`, `Dockerfile`) | a push to `main` runs `deploy-services.yml` | the container restarts, automatically |
| **Integration** (`custom_components/inkframe/`) | a **tagged release** of the public repository, downloaded by HACS | **Home Assistant restarts** |
| **Firmware** (`firmware/`) | never automatically | you flash it, inside the panel's OTA window |

On 2026-09-18 the renderer deployed successfully and answered its new
`/albums` route while `button.inkframe_refresh_albums` did not exist in Home
Assistant at all. Both halves of one feature, both correct, one of them live.
That is the normal state of this repository between a merge and a release, and
it looks exactly like a broken feature.

## Releasing the integration

1. **Roll the changelog.** `[Unreleased]` becomes `[X.Y.Z] - YYYY-MM-DD`; add
   the compare links at the bottom.
2. **Bump `custom_components/inkframe/manifest.json`.** HACS reads the version
   from there, and shows the update only when it differs from what is installed.
3. `make ci` in the monorepo, then merge.
4. **Export**: `tools/export-public.sh`. It refuses if a private identifier is
   in the exported tree **or anywhere in the destination's git history** — see
   [open-findings §19](../../../docs/04-operations/open-findings.md) for why the
   second half exists.
5. Commit and push in `integrations/InkFrame-Immich/` as Davide, no trailers.
   Wait for its CI: hassfest, renderer tests, HACS validation, ESPHome config.
   **That run is the verdict**, not `make ci`.
6. Tag and release:
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
creates.** Not the version in HACS, not the manifest on disk — an entity:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HA/api/states/button.inkframe_refresh_albums"     # "Entity not found." means it did not load
```

Then press it, and read the renderer's log. A button that exists and does
nothing is the failure this check is for.

## If a private identifier ever reaches the public repository

`tools/export-public.sh` refuses the export, and since 2026-09-18 it reads the
destination's **git history** as well as the tree about to be committed. If it
refuses on history, a rewrite is not enough:

**GitHub keeps unreferenced objects and serves them by SHA.** After
`git filter-repo` and a force-push, every old commit still answered 200 on
`raw.githubusercontent.com`, in the web UI and through the API. The repository
has to be deleted and recreated — `tools/recreate-public-repo.sh` does the
restore, and refuses against a repository that still has commits.

Two things then look like failure and are not:

- **The old SHAs keep answering 200 for up to five minutes.** That is the raw
  CDN (`x-cache: HIT`, `source-age`, `max-age=300`), not GitHub; the API
  already says `Git Repository is empty`. Wait for `source-age` to reset. A
  query-string cache-buster does not defeat it.
- **HACS does not need re-adding.** It holds the deleted repository's numeric
  id, and one `hacs/repository/refresh` re-resolves the full name to the new
  one with `installed_version` intact. The integration runs off disk the whole
  time.

Deleting is only total when there are **no forks**. With a fork, the objects
live on in the fork network and deleting the origin does not clear them.

## Releasing the renderer alone

Merge to `main`. `deploy-services.yml` rebuilds and restarts the container.
Confirm by asking the container, not the workflow list — a rollout can be
cancelled by a later merge landing on top and still show green above it:

```bash
docker logs --tail 5 HA_ImmichFrame
curl -s http://<renderer>:8099/status | python3 -m json.tool | head
```

A restart does **not** consume a photo or lose the picture: the frame and the
panel's collected generation are both persisted, and start-up keeps a restored
frame rather than rendering a new one.
