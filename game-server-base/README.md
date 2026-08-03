# Build a game add-on on `game-server-base`

**Not an installable Home Assistant app.** This folder has no `config.yaml` on purpose so the HAOS App store never lists it. Only thin game add-ons (like Necesse) are installable.

Most people visiting this repository want a **specific game**. If that’s you, start at the [repository README](../README.md) and open that game’s guide (for example [Necesse](../necesse-dedicated-server/README.md)).

This document is for the other journey: **you want to run a different Steam dedicated server** on the same supervisor (auto-update, backups, crash restart, HA Ingress/status, Steam rate gate).

---

## What you are building

`game-server-base` is a **game-agnostic** SteamCMD supervisor. It does not know Necesse — or any other title.

A game add-on is a thin layer around it:

1. Vendored copy of `game_server/` (keep in sync with the script below)
2. One plugin file: `games/game.yaml` (Steam app id, launch command, args, optional log patterns)
3. Runtime packages the game needs (Java, etc.) in **that** add-on’s Dockerfile
4. Home Assistant metadata: `config.yaml`, translations, ports, docs

**Hard rule:** do not put game names, Steam app ids, ports, or runtimes into `game-server-base/`. If `rg -i yourgamename game-server-base` finds anything, it belongs in the game layer instead.

---

## Fast path (copy an existing game)

The Necesse add-on is the reference thin layer:

1. Copy `necesse-dedicated-server/` to something like `mygame-dedicated-server/`.
2. Edit `games/game.yaml` for your Steam dedicated server (app id, executable, args, data/log dirs).
3. Change the Dockerfile runtime (drop OpenJDK if you don’t need it; add whatever your binary needs).
4. Update HA `config.yaml`: name, slug, ports, options/schema for your game flags.
5. Rewrite that add-on’s `README.md` / `DOCS.md` for **players of your game** (install → configure → port-forward → join). Don’t leave a stub that only links elsewhere.
6. From the repo root, after any supervisor change:

   ```bash
   ./scripts/sync-game-server-base.sh
   ```

   This copies **only** `game_server/` into each known add-on. It never overwrites `games/*.yaml`.

7. Install via the HA add-on repo, or run with Docker using a compose file modeled on Necesse’s.

---

## Plugin YAML (the game identity)

Point the container at your plugin with `GAME_PLUGIN` (Necesse’s `run.sh` does this for you).

Minimum useful fields:

| Field | Purpose |
| --- | --- |
| `name` | Display / notification label |
| `steam_app_id` | SteamCMD app id for the dedicated server |
| `executable` | argv to launch the server |
| `install_marker` | File that means “install looks present” (e.g. `Server.jar`) |
| `arg_map` | Map HA/options keys → CLI flags |
| `data_dir` / `logs_dir` / `working_dir` | Usually under `/data/...` |
| `stop_stdin_commands` | Optional graceful stop (`save` / `exit`, etc.) |
| `backup_paths` | What to archive (usually the whole data dir) |
| `world_save` | Active world artifact for status UI (`strategy: named_path` + `paths` templates). Separate from backups. |
| `log_patterns` | **Active** regexes (`game_version`, player count, version mismatch, …). Prefer empty until proven, except informational captures like `game_version`. |
| `log_pattern_candidates` | Extra dry-run regexes for Ingress highlighting |

Shape reference (synthetic, not a real game):  
`game-server-base/tests/fixtures/example.game.yaml`

### Log patterns without shooting yourself in the foot

- Ship with `log_patterns: {}` until you’ve watched real logs.
- Built-in generic candidates only **highlight** lines in Ingress (`/api/logs/patterns`); they do not gate players or force updates.
- Promote a regex into `log_patterns` only after it cleanly matches the real event.
- If active player patterns are missing, empty-server gating stays inactive so Steam `buildid` updates still work.

---

## What the supervisor already does for you

You should not re-implement these in game-specific scripts:

- Read HA `/data/options.json` (+ env overrides)
- SteamCMD install/update with a **rate gate** (serialize, spacing, exponential backoff, cooldowns)
- Process supervision, crash restarts, privilege drop to `gameserver`
- World backups with retention profiles
- HA Core notifications (no MQTT) + `/data/supervisor/status.json`
- Ingress/status HTTP and log capture toolkit
- Mirror useful streams to the HA Logs tab (`[game]`, `[game-log]`, `[steamcmd]`)

---

## Local base image (optional)

```bash
docker build -f game-server-base/Dockerfile -t game-server-base .
```

The base image has SteamCMD + Python only. A real game still needs its runtime and `GAME_PLUGIN` — that’s why game add-ons have their own Dockerfiles.

---

## Layout reminder

| Path | Role |
| --- | --- |
| `game-server-base/game_server/` | Shared Python package |
| `game-server-base/Dockerfile` | Generic base image |
| `game-server-base/tests/` | Unit tests + synthetic plugin fixture |
| `game-server-base/games/` | Intentionally empty of real games — plugins live in each add-on |

---

## Tests

```bash
PYTHONPATH=game-server-base python3 game-server-base/tests/test_config_and_monitor.py
```

When you change the supervisor, sync, then rebuild/reinstall the game add-on before expecting HAOS to pick up a new version (version bump lives in that add-on’s `config.yaml`).
