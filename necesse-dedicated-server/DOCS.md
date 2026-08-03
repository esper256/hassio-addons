# Necesse Dedicated Server

Runs a Necesse dedicated server on Home Assistant OS with SteamCMD auto-updates, crash restarts, world backups, and a status page (Ingress).

## Why version 2.x

The previous add-on wrapped a third-party image and tried to bridge HA options into that image’s environment variables. That path was brittle:

- options parsing depended on `jq` / awkward path remapping of `/data`
- auto-update did not reliably keep up with Steam client patches
- there was no “update when empty” or “update when clients are rejected for wrong version” behaviour

This version vendors a small generic Steam game-server supervisor (see `/game-server-base` in the repository) and configures it with a Necesse plugin.

## Installation

1. Add this repository to Home Assistant → Settings → Add-ons → Add-on store → Repositories
2. Install **Necesse Dedicated Server**
3. Set `world_name` and optional `server_password`
4. Start the add-on
5. Forward **UDP 14159** on your router to your HA host
6. Open the add-on Ingress panel for status

First start downloads/updates the server through SteamCMD and can take several minutes.

## Configuration

| Option | Purpose |
| --- | --- |
| `world_name` | Save / world name (`-world`) |
| `server_password` | Join password |
| `server_slots` | Max players |
| `server_port` | UDP port inside the container (map host port to match) |
| `pause_when_empty` | Pause simulation with no players |
| `update_on_start` | Run SteamCMD before every start |
| `auto_update_interval_minutes` | How often to poll Steam for a newer build (`0` disables) |
| `update_when_empty_only` | Only restart for updates when player count is 0 |
| `update_on_version_mismatch` | If logs show clients rejected for wrong version, schedule an update immediately (still waits until empty by default; bypasses quiet hours) |
| `update_window_start_hour` / `update_window_end_hour` | Optional quiet hours for routine Steam polls (local container time). Leave unset for any hour. |
| `backup_enabled` | Periodic tar.gz backups of `/data/world` |
| `backup_on_update` | Take a backup immediately before applying an update |
| `java_opts` | JVM memory / flags |

## Data layout

Persistent add-on data lives under `/data`:

```
/data/options.json          # written by Home Assistant
/data/world/                # Necesse -datadir (saves, cfg)
/data/logs/                 # Necesse logs
/data/backups/              # supervisor backups
/data/supervisor/           # supervisor state
```

Game binaries live in the container under `/opt/game` and are refreshed by SteamCMD.

## Status / Ingress

The supervisor serves:

- `/` HTML status page
- `/api/status` JSON
- `/healthz` health probe

Ingress is enabled by default. You can also map host TCP 8080 if you want LAN access without Ingress.

## Portainer / plain Docker

Prefer building the shared image from the repo root:

```bash
docker compose -f game-server-base/docker-compose.yml up -d --build
```

## Updating the game

1. Steam build poll finds a newer `buildid`, **or**
2. Logs match a version-mismatch pattern

Then, when the server is empty (default), the supervisor backs up the world, updates via SteamCMD, and restarts.

If your kids suddenly cannot join after a Steam patch, check the Ingress status page for `update_pending` / version mismatch counters. With defaults, the server should self-heal once nobody is connected (usually immediately, because mismatched clients cannot stay online).

## Migrating from 1.x

Version 1.x remapped the HA data volume onto `/home/necesse`. On start, this add-on copies legacy saves from `/home/necesse/.config/Necesse` into `/data/world` when it detects them. Keep a HA backup before upgrading.
