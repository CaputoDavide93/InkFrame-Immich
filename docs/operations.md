# 📦 Operations

## Running the renderer

```bash
cd server
cp .env.example .env
docker compose up -d
docker compose logs -f
```

`docker-compose.yml` publishes port 8099, mounts the API key as a Docker secret, and mounts a named volume at `/data` for the state file. The health check hits `/healthz` every minute.

### What the health check does and does not prove

`/healthz` proves the listener answers. It does not assert that a frame is current, because on an e-paper frame a dead renderer looks exactly like a working one from across the room. `last_error` in `/status` is where a failing render shows up, and **Last error** in Home Assistant surfaces it.

## State

`/data/state.json` holds the source selection and every runtime setting. It exists so a container restart, or a redeploy with different environment variables, never silently reverts a choice made from Home Assistant. Back it up if you care about the settings; delete it to return to the environment defaults.

## The API key

Create a key in Immich with the minimum scope: `asset.read`, `asset.view`, `asset.statistics`, `album.read`, `person.read`. Store it in a file the container can read (mode 0644; the process runs as uid 1000) and point `IMMICH_API_KEY_FILE` at it, or pass `IMMICH_API_KEY` directly for a quick test. Keep it separate from any key Home Assistant's own Immich integration uses, so revoking one does not break the other.

## Logs worth knowing

| Line | Meaning |
|---|---|
| `gen N: <file> busyness X (best of 20)` | A render happened and what it chose |
| `every candidate was busier than ...` | Threshold too tight for this source |
| `wake: gen N not yet collected, serving it` | The panel woke before collecting the previous render; no rotation |
| `settings changed by push` / `source set by push` | Home Assistant wrote something |
| `people counted: ...` | The daily eligibility count finished |

## Upgrading

Pull, rebuild, `docker compose up -d`. The state file carries your settings across. Nothing on the panel changes unless you reflash it.
