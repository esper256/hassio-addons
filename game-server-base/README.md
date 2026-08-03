# game-server-base

Generic supervisor for SteamCMD dedicated game servers. Designed for Home Assistant OS add-ons and plain Docker/Portainer.

## Architecture

| Component | Responsibility |
| --- | --- |
| `config.py` | Read HA `/data/options.json` and/or env vars (no `jq`) |
| `steamcmd.py` | First install + updates with retries; compare Steam build IDs |
| `process_manager.py` | Launch as non-root, graceful stop, crash restart |
| `monitor.py` | Tail logs / stdout for players and version-mismatch signals |
| `log_tools.py` | Ingress-friendly captures + regex suggestions (no SSH) |
| `supervisor.py` | Orchestrate update timing, status, notifications |
| `status_http.py` | Dashboard + `/api/status` + log endpoints |
| `backup.py` | Generational retention + empty-save backoff |
| `notify.py` | HA Core API persistent notifications (no MQTT) |
| `games/*.yaml` | Per-game plugins |

## Defaults that matter for lights-out use

- Game install path: `/data/game` (persistent)
- World path: `/data/world`
- Status file: `/data/supervisor/status.json`
- Log captures: `/data/supervisor/captures/`
- Backups: recent + daily + weekly + monthly + yearly keepers
- Notifications: HA persistent notifications when Supervisor token is available

## Build / run (Portainer or Docker)

From the repository root:

```bash
docker compose -f game-server-base/docker-compose.yml up -d --build
```

Status / log UI: `http://<host>:8080/`

### Log toolkit endpoints

| Endpoint | Purpose |
| --- | --- |
| `POST/GET /api/logs/capture` | Snapshot logs + analysis into downloadable tar.gz |
| `GET /api/logs/suggest` | Propose regexes from unmatched interesting lines |
| `GET /api/logs/raw?lines=400` | Tail current game log |
| `GET /api/logs/captures` | List prior captures |
| `GET /api/logs/captures/<id>/download` | Download one capture |

## Adding another game

1. Copy `games/necesse.yaml` → `games/<game>.yaml`
2. Set `steam_app_id`, `executable`, `arg_map`, `stop_stdin_commands`, `log_patterns`
3. Point `GAME_PLUGIN=/opt/games/<game>.yaml`
4. Use Ingress **Capture logs** + **Suggest patterns** after a real play session to harden regexes quickly

## Sync into the HA add-on

```bash
./scripts/sync-game-server-base.sh
```
