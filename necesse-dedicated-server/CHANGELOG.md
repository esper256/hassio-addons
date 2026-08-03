# Changelog

## 2.1.1

- Enforce clean separation: generic supervisor has no game identity; Necesse is plugin YAML + Java + HA metadata only
- Move legacy path moves into `games/game.yaml` `path_migrations` (handled by generic code)
- Base image no longer bundles OpenJDK, game ports, or a default plugin

## 2.1.0

- Persist Steam game install under `/data/game` (survives container recreate)
- Run game process as `gameserver` after fixing volume ownership
- Graceful stop via stdin `save`/`exit` before SIGTERM, backup, and update
- Generational backup retention (recent/daily/weekly/monthly/yearly)
- Skip empty/tiny world backups with exponential backoff on failures
- Disk free-space guard for backups/updates
- HA persistent notifications via Core API (no MQTT)
- Continuously write `/data/supervisor/status.json`
- Ingress log toolkit: capture, suggest patterns, raw tail, downloadable archives
- Auto log capture on version mismatch and crash

## 2.0.0

- Replace the thin wrapper around `andreasgl4ser/necesse-server` with a first-party SteamCMD supervisor shared as `game-server-base`
- Read Home Assistant `/data/options.json` with Python (no `jq`, no remapping `/data` over `/home/necesse`)
- Auto-update from Steam build IDs on a timer, preferring empty-server restarts
- Detect version-mismatch style log lines and force an update cycle (bypasses quiet hours)
- Crash restart loop with per-hour rate limit
- Optional Ingress status page (`/`, `/api/status`, `/healthz`)
- Periodic + pre-update world backups under `/data/backups`
- Expose UDP 14159 by default again
- Migrate legacy saves from `/home/necesse/.config/Necesse` when present

## 1.7.0

- Previous generation based on Andreas Glaser's SteamCMD image and a bash HA entrypoint
