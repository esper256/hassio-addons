# game-server-base

Generic supervisor for SteamCMD dedicated game servers. Designed for Home Assistant OS add-ons and plain Docker/Portainer.

## Why this exists

Existing Necesse Docker images can install via SteamCMD, but wrapping them for HAOS was fragile:

- HA `options.json` parsing broke in slim images without reliable JSON tools
- Auto-update did not react to client version-mismatch pressure
- Updates were not gated on “no players online”
- No shared pattern for status, crash restarts, or world backups

This base implements that shared pattern once. Individual games only supply a plugin file (Steam app id, launch args, log regexes).

## Architecture

| Component | Responsibility |
| --- | --- |
| `config.py` | Read HA `/data/options.json` and/or env vars (no `jq` required) |
| `steamcmd.py` | First install + updates with retries; compare Steam build IDs |
| `process_manager.py` | Launch game process, restart on crash with rate limit |
| `monitor.py` | Tail logs / stdout for players and version-mismatch signals |
| `supervisor.py` | Orchestrate update timing (empty server / quiet hours / mismatch) |
| `status_http.py` | Optional HTTP dashboard + `/api/status` + `/healthz` |
| `backup.py` | Periodic and pre-update tar.gz world backups |
| `games/*.yaml` | Per-game plugin definitions |

```
options.json / env
        │
        ▼
   Supervisor ──► SteamCMD install/update
        │
        ├──► Game process (crash restart loop)
        ├──► Log monitor (players / version mismatch)
        ├──► Backup manager
        └──► Status HTTP (:8080)
```

## Build / run (Portainer or Docker)

From the repository root:

```bash
docker build -f game-server-base/Dockerfile -t game-server-base .
docker run -d --name necesse \
  -p 14159:14159/udp \
  -p 8080:8080 \
  -v $PWD/necesse-data:/data \
  -e WORLD_NAME=FamilyWorld \
  -e SERVER_PASSWORD=changeme \
  -e SERVER_SLOTS=10 \
  -e PAUSE_WHEN_EMPTY=true \
  -e UPDATE_ON_START=true \
  -e AUTO_UPDATE_INTERVAL_MINUTES=30 \
  -e UPDATE_WHEN_EMPTY_ONLY=true \
  -e UPDATE_ON_VERSION_MISMATCH=true \
  -e STATUS_HTTP_ENABLED=true \
  game-server-base
```

Status page: `http://<host>:8080/`

## Adding another game later

1. Copy `games/necesse.yaml` to `games/<game>.yaml`
2. Set `steam_app_id`, `executable`, `arg_map`, and `log_patterns`
3. Point `GAME_PLUGIN=/opt/games/<game>.yaml`
4. Expose the game’s ports

LinuxGSM and `gameservermanagers/steamcmd` are excellent for bare-metal/VPS fleets. This project intentionally stays smaller and HAOS-friendly: one Python supervisor, JSON options, ingress-ready status, and plugin YAML.

## Update policy

Updates apply when:

1. Steam reports a newer `buildid`, or logs show a version-mismatch rejection, and
2. Either the server is empty (default) or `update_when_empty_only=false`, and
3. The current hour is inside the optional update window

On apply: optional world backup → stop server → SteamCMD update → start server.
