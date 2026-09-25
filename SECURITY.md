# 🔒 Security Policy

## Reporting a vulnerability

Report privately through
[GitHub Security Advisories](https://github.com/CaputoDavide93/InkFrame-Immich/security/advisories/new)
rather than a public issue. You should hear back within a week.

## What this project touches

- **Your photographs.** The renderer downloads Immich previews, keeps the current and previous rendered frame in memory, and serves them over plain HTTP to clients that present the shared bearer token. Nothing is written to disk except the state file.
- **An Immich API key.** Read from a file or the environment at start. It is never logged and never returned by any endpoint. Scope it to `asset.read`, `asset.view`, `asset.statistics`, `album.read`, `person.read`; nothing here needs more.
- **Names of people** from Immich face recognition. They appear in `/status`, `/people` and the Home Assistant entities.
- **The state file** (`/data/state.json`): source selection and render settings. No secrets.

## What it does not do

- No per-user accounts. One shared bearer token (`INKFRAME_TOKEN_FILE` or `INKFRAME_TOKEN`) guards every endpoint except the `/healthz` liveness probe; whoever holds it can read the current photo, change the source and settings, and trigger renders.
- No TLS.
- No outbound connections except to your Immich server.

## Deployment checklist

- Run the renderer on a network you trust. The bearer token travels over plain HTTP, so anyone who can sniff the network can capture it. Do not expose port 8099 to the internet.
- The panel fetches over plain HTTP, so the panel and the renderer should share a trusted network.
- Mount the API key as a Docker secret or a read-only file. Mode 0644 is required for uid 1000 to read it; keep the directory private.
- Treat `/data` as confidential in backups only if the names of people in your library are sensitive to you.

## Supported versions

The latest commit on `main`.
