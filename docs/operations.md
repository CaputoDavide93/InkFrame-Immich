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

`/data/state.json` holds the source selection and every runtime setting.
Two frames are saved beside it, each with a small `.json`: `frame.bin` is the
newest render, and `panel.bin` is the one the panel actually collected. They
are different pictures whenever something has rendered since the panel last
woke, which on a three-day cycle is most of the time.

Saving only the newest lost the collected one on every restart, and
`On the panel` in Home Assistant went blank until the panel's next wake, days
away. It read unknown rather than showing the wrong photo, which was the right
failure, but a blank card describing a wall with a picture on it is still
wrong.

The frame is saved for a reason worth knowing: before it was, a restart left
the renderer with nothing to serve, every image route answered 500, and with a
source that had run dry it stayed that way indefinitely. It is written to a
temporary name and renamed into place, so a crash mid-write cannot leave half a
frame that restores as a band of noise, and a frame of the wrong length is
refused outright.

The save also records whether the panel had collected that frame. Without it a
restart made Home Assistant forget what was on the wall: `On the panel` read
unknown and `Up next` claimed something was waiting, while the wall had not
changed.

**A restart does not consume a photo.** If a frame was restored, start-up keeps
it rather than rendering a new one. Otherwise a weekly frame would rotate every
time the container was rebuilt, and the panel would be a generation behind from
the moment it came back.

 It exists so a container restart, or a redeploy with different environment variables, never silently reverts a choice made from Home Assistant. Back it up if you care about the settings; delete it to return to the environment defaults.

## The API key

Create a key in Immich with the minimum scope: `asset.read`, `asset.view`, `asset.statistics`, `album.read`, `person.read`. Store it in a file the container can read (mode 0644; the process runs as uid 1000) and point `IMMICH_API_KEY_FILE` at it, or pass `IMMICH_API_KEY` directly for a quick test. Keep it separate from any key Home Assistant's own Immich integration uses, so revoking one does not break the other.

## Logs worth knowing

| Line | Meaning |
|---|---|
| `gen N: <file> busyness X (best of 20)` | A render happened and what it chose |
| `restored the last frame: X (on the panel: true/false)` | A restart kept the previous picture |
| `start-up: keeping the restored frame` | A restart deliberately did not rotate |
| `every candidate was busier than ...` | Threshold too tight for this source |
| `wake: gen N not yet collected, serving it` | The panel woke before collecting the previous render; no rotation |
| `settings changed by push` / `source set by push` | Home Assistant wrote something |
| `people counted: ...` | The daily eligibility count finished |

## Upgrading

Pull, rebuild, `docker compose up -d`. The state file carries your settings across. Nothing on the panel changes unless you reflash it.
