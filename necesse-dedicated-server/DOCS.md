# Necesse Dedicated Server

Runs a Necesse dedicated server on Home Assistant OS with SteamCMD auto-updates, crash restarts, generational world backups, HA notifications (no MQTT), and an Ingress status/log toolkit.

## Why version 2.x

The previous add-on wrapped a third-party image and tried to bridge HA options into that image’s environment variables. That path was brittle and did not keep up with Steam client patches reliably.

This version vendors a shared Steam game-server supervisor (`game-server-base`) configured by a Necesse plugin.

## Installation

1. Add this repository in **Settings → Add-ons → Add-on store → Repositories**
2. Install **Necesse Dedicated Server**
3. Set `world_name` and optional `server_password`
4. Start the add-on
5. Forward **UDP 14159** on your router to your HA host
6. Open the add-on Ingress panel for status + log tools

First start downloads/updates the server through SteamCMD and can take several minutes.

## Data layout

Everything important persists under `/data`:

```
/data/options.json
/data/game/                 # SteamCMD install (Server.jar, etc.)
/data/world/                # Necesse -datadir (saves, cfg)
/data/logs/                 # Necesse logs
/data/backups/              # generational tar.gz backups
/data/supervisor/
  status.json               # machine-readable status for REST sensors
  captures/                 # downloadable log captures (no SSH needed)
```

## Updates

Updates apply when:

1. Steam reports a newer `buildid`, or logs show a version-mismatch rejection, and
2. the server is empty (default), and
3. optional quiet hours allow it (mismatch bypasses quiet hours)

On apply: graceful save/exit → backup → SteamCMD update → restart.

## Backups

Backups use generational retention, not “keep last 7 daily and delete the rest”:

- always keep N recent
- one per day / week / month / year according to the keep_* settings

Empty/tiny worlds are refused. Failures use exponential backoff from `backup_interval_minutes` (capped at 24h by default). Disk-space guard skips backup/update when free space is too low.

## Notifications (no MQTT)

With `ha_notifications: true` (default), the add-on uses the Home Assistant Core API via Supervisor to create persistent notifications for:

- version mismatch
- crash / crash loop
- SteamCMD / update failures

It also continuously writes `/data/supervisor/status.json`.

Optional REST sensors (if you expose port 8080 or call through Ingress tooling):

```yaml
rest:
  - resource: http://homeassistant.local:8080/api/status
    sensor:
      - name: Necesse Players
        value_template: "{{ value_json.monitor.player_count }}"
      - name: Necesse Update Pending
        value_template: "{{ value_json.update_pending }}"
      - name: Necesse Build
        value_template: "{{ value_json.local_build_id }}"
```

## Log toolkit (no SSH / Portainer exec)

From Ingress:

- **Capture logs now** → packages recent stdout, log tail, analysis, status into a downloadable `.tar.gz`
- **Suggest patterns** → `/api/logs/suggest` finds unmatched lines that look like joins/leaves/version errors and proposes starter regexes
- **Raw log tail** → `/api/logs/raw`
- Auto-captures also happen on version mismatch and crashes

Use those captures to harden `games/game.yaml` log patterns without entering the container.

## First patch weekend checklist

1. Note current build on Ingress (`Build`)
2. After a Steam client patch, confirm kids either join or trigger mismatch capture
3. Watch `update_pending` flip true, then false after an empty-server update
4. Confirm a new archive appears under `/data/backups`
5. Confirm a notification appears in HA if something fails

## Portainer / plain Docker

```bash
docker compose -f necesse-dedicated-server/docker-compose.yml up -d --build
```

## Migrating from 1.x

Legacy path moves are declared in `games/game.yaml` (`path_migrations`) and applied by the generic supervisor on startup. Keep a HA backup before upgrading.
