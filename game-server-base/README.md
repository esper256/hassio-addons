# Build a game add-on on `game-server-base`

**Not an installable Home Assistant app** — no `config.yaml` on purpose. Only thin game folders (like Necesse) appear in the App store.

Most visitors want a **specific game**: start at the [repository README](../README.md) (e.g. [Necesse](../necesse-dedicated-server/README.md)).

This guide is for packaging **another Steam dedicated server** on the same supervisor (auto-update, by-kind world backups, crash restart, Ingress status, Steam rate gate).

---

## What you are building

`game-server-base` is a **game-agnostic** SteamCMD supervisor. It does not know Necesse — or any other title.

A game add-on is a thin layer:

1. Vendored copy of `game_server/` (keep in sync with the script below)
2. Plugin: `games/game.yaml` (Steam app id, launch command, args, `world_save`, log patterns)
3. Runtime packages in **that** add-on’s Dockerfile (Java, etc.)
4. Home Assistant metadata: `config.yaml`, translations, ports, `README.md` / `DOCS.md`

**Hard rule:** do not put game names, Steam app ids, ports, runtimes, or game option env keys into `game-server-base/`. If `rg -i yourgamename game-server-base` finds anything, it belongs in the game layer. Docker/compose game options are contributed by each plugin via `docker_env_keys()` (derived from `arg_map` / `settings_map` / templates, plus optional `env_options`).

---

## Fast path (copy Necesse)

1. Copy `necesse-dedicated-server/` → e.g. `mygame-dedicated-server/`.
2. Edit `games/game.yaml` for your dedicated server (app id, executable, args, data/log dirs, `world_save`).
3. Adjust the Dockerfile runtime for your binary.
4. Update HA `config.yaml`: name, slug, ports, options/schema.
5. Rewrite that add-on’s `README.md` / `DOCS.md` for **players of your game** (install → configure → port-forward → join).
6. After any supervisor change, from the repo root:

   ```bash
   ./game-server-base/sync-into-addons.sh
   ```

   Copies **only** `game_server/` into each sibling add-on that has `config.yaml` + `games/`. Never overwrites `games/*.yaml`. Not part of the Docker build.

7. Bump that add-on’s `config.yaml` version, then install via the HA repo or Docker compose modeled on Necesse’s.

---

## Plugin YAML (game identity)

Point the container at your plugin with `GAME_PLUGIN` (Necesse’s `run.sh` does this).

| Field | Purpose |
| --- | --- |
| `name` | Display / notification label |
| `steam_app_id` | SteamCMD app id |
| `executable` | argv to launch the server |
| `install_marker` | File that means “install looks present” |
| `arg_map` | HA/options keys → simple CLI flags (`-flag value`) |
| `argv_prefix` | Ordered tokens after the executable; `{option}` templates; empty → omitted |
| `settings_flag` / `settings_map` / `fixed_settings` | Optional `-settings Key Value …` style block (Unity servers, etc.) |
| `env_options` | Extra UPPER_SNAKE Docker/compose env vars (optional). Keys from `arg_map` / `settings_map` / `{option}` templates are accepted automatically |
| `data_dir` / `logs_dir` / `working_dir` | Usually under `/data/...` |
| `stop_stdin_commands` | Optional graceful stop |
| `world_save` | Active world artifact: `strategy: named_path` + `paths` templates. Drives status UI, upload restore, and **by-kind backups** (file = copy as-is; folder = zip). |
| `backup_paths` | Fallback roots when no named world exists yet; also used to restore legacy `*.tar.gz` snapshots |
| `log_patterns` | Active regexes (ready, players, version, `players_empty`, …). Prefer empty until proven. |
| `log_pattern_candidates` | Extra dry-run regexes for Ingress highlighting |
| `player_tracking_mode` | `count` (default, numeric/named) or `presence` (Idle vs Players Active) |

Shape reference: `game-server-base/tests/fixtures/example.game.yaml`

### Log patterns

- Ship `log_patterns: {}` until you’ve watched real logs.
- Generic dry-run candidates only **highlight** in Ingress; they do not gate updates.
- Promote a regex only after it cleanly matches the real event.
- Without active join/leave patterns, “update only when empty” cannot wait for players to leave.

---

## What the supervisor already provides

- HA `/data/options.json` (+ env overrides)
- SteamCMD install/update with a rate gate (serialize, spacing, backoff)
- Process supervision, crash restarts, privilege drop to `gameserver`
- By-kind world backups + retention profiles; Ingress restore / NEW WORLD / upload
- HA Core notifications + `/data/supervisor/status.json`
- Ingress status HTTP and log capture toolkit
- Mirrored streams on the HA Logs tab (`[game]`, `[game-log]`, `[steamcmd]`)

---

## Tests

```bash
PYTHONPATH=game-server-base python3 -m pytest game-server-base/tests -q
```

After supervisor changes: sync → bump the game add-on version → rebuild/reinstall.

---

## Layout

| Path | Role |
| --- | --- |
| `game-server-base/game_server/` | Shared Python package |
| `game-server-base/Dockerfile` | Generic SteamCMD + Python image |
| `game-server-base/tests/` | Unit tests + synthetic plugin |
| `game-server-base/games/` | Empty on purpose — plugins live in each add-on |
