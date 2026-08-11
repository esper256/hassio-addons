# Build a game add-on on `game-server-base`

**Not an installable Home Assistant app** — no `config.yaml` on purpose. Only thin game folders (like Necesse) appear in the App store.

Most visitors want a **specific game**: start at the [repository README](../README.md) (e.g. [Necesse docs](../necesse-dedicated-server/DOCS.md)).

This guide is for packaging **another Steam dedicated server** on the same supervisor (auto-update, by-kind world backups, crash restart, Ingress status, Steam rate gate).

> **AI experiment:** like the rest of this repo, `game-server-base` is a deliberate AI-coding experiment. It works and is useful, and it has been **100% written with AI**. See the [repository README](../README.md).

---

## Home Assistant docs split

Home Assistant shows two markdown files from each game folder ([presentation docs](https://developers.home-assistant.io/docs/add-ons/presentation/)):

| File | Where it appears | Keep it |
| --- | --- | --- |
| `README.md` | Info / store panel under the HA chrome | Two short paragraphs: what it is (game name linked), then Documentation vs **Open Web UI**. No H1, no images (HA often breaks relative images), no amd64 / GitHub / Docker. |
| `DOCS.md` | Documentation tab after install | Spartan: configure, ports, **OPEN WEB UI**, essential settings. Screenshots belong on GitHub (root README), not here. |

Put GitHub landing content (install repository, multi-game gallery, Docker, AI note) in the **repo root** [README.md](../README.md) — HA never shows that file inside an app.

---

## What players see (Ingress)

Each game add-on vendors this supervisor and exposes **OPEN WEB UI** through Home Assistant Ingress. Example from Necesse:

![Example Ingress status UI (Necesse)](../necesse-dedicated-server/images/ingress-ui.png)

Primary cards answer “is it up / can people play / do I need to act?” World backups and a collapsed **Troubleshooting** section sit below. Your game plugin supplies theme colors, world-save paths, and log patterns; the layout is shared.

---

## What you are building

`game-server-base` is a **game-agnostic** SteamCMD supervisor. It does not know Necesse — or any other title.

A game add-on is a thin layer:

1. Vendored copy of `game_server/` (keep in sync with the script below)
2. Plugin: `games/game.yaml` (Steam app id, launch command, args, `world_save`, log patterns)
3. Runtime packages in **that** add-on’s Dockerfile (Java, etc.)
4. Home Assistant metadata: `config.yaml`, translations, ports, short `README.md`, spartan `DOCS.md`

**Hard rule:** do not put game names, Steam app ids, ports, runtimes, or game option env keys into `game-server-base/`. If `rg -i yourgamename game-server-base` finds anything, it belongs in the game layer. Docker/compose game options are contributed by each plugin via `docker_env_keys()` (derived from `arg_map` / `settings_map` / templates, plus optional `env_options`).

---

## Fast path (copy Necesse)

1. Copy `necesse-dedicated-server/` → e.g. `mygame-dedicated-server/`.
2. Edit `games/game.yaml` for your dedicated server (app id, executable, args, data/log dirs, `world_save`).
3. Adjust the Dockerfile runtime for your binary.
4. Update HA `config.yaml`: name, slug, ports, options/schema.
5. Rewrite that add-on’s **short** `README.md` (store) and **spartan** `DOCS.md` (Documentation tab). Put install-from-GitHub / Docker narrative in the repo root README, not in the app folder.
6. After any supervisor change, from the repo root:

   ```bash
   ./game-server-base/sync-into-addons.sh
   ```

   Copies **only** `game_server/` into each sibling add-on that has `config.yaml` + `games/`. Never overwrites `games/*.yaml`. Not part of the Docker build. CI runs `./game-server-base/check-addon-sync.sh` so forgotten syncs fail the build.

7. Bump that add-on’s `config.yaml` version, then install via the HA repo or Docker compose modeled on Necesse’s.

---

## Plugin YAML (game identity)

Point the container at your plugin with `GAME_PLUGIN` (Necesse’s `run.sh` does this).

| Field | Purpose |
| --- | --- |
| `name` | Display / notification label |
| `steam_app_id` | SteamCMD app id (required unless `package_install` is set) |
| `steam_branch` | Default SteamCMD branch (overridable by HA option `steam_branch`) |
| `package_install` | Optional non-Steam HTTP archive install (`version_url`, `version_json_path`, `download_url`, `strip_components`). `version_json_path` may include `{release_channel}` (HA option `release_channel`, default `stable`) |
| `executable` | argv to launch the server |
| `install_marker` | File that means “install looks present” |
| `arg_map` | HA/options keys → simple CLI flags (`-flag value`) |
| `argv_prefix` | Ordered tokens after the executable; `{option}` templates; empty → omitted |
| `settings_flag` / `settings_map` / `fixed_settings` | Optional `-settings Key Value …` style block (Unity servers, etc.) |
| `config_files` | Optional JSON/INI/`mod_list` files rewritten from options before each launch (`path`, `format`, `fixed`, `map`, `types`, or `mods` for mod_list) |
| `world_prepare` | Optional one-shot argv (same executable) when the active world is missing — e.g. create-save before host |
| `env_options` | Extra UPPER_SNAKE Docker/compose env vars (optional). Keys from `arg_map` / `settings_map` / `{option}` templates are accepted automatically |
| `data_dir` / `logs_dir` / `working_dir` | Usually under `/data/...` |
| `stop_stdin_commands` | Optional graceful stop |
| `world_save` | Active world artifact: `strategy: named_path` + `paths` templates. Drives status UI, upload restore, and **by-kind backups** (file = copy as-is; folder = zip). |
| `backup_paths` | Fallback roots when no named world exists yet; also used to restore legacy `*.tar.gz` snapshots |
| `log_patterns` | Active regexes (ready, players, version, `players_empty`, …). Prefer empty until proven. |
| `log_pattern_candidates` | Extra dry-run regexes for Ingress highlighting |
| `player_tracking_mode` | `count` (default, numeric/named) or `presence` (Idle vs occupied; unknown leave → idle) |

Shape reference: `game-server-base/tests/fixtures/example.game.yaml`

### Log patterns (dry-run first)

- **New games must ship `log_patterns: {}`** (empty active). Put guesses in `log_pattern_candidates` plus the shared generics in `patterns.py`.
- Generic + game candidates only **highlight** in Ingress Debug mode; they do **not** gate updates or player presence.
- Prefer many broad, case-insensitive guesses (over-match) over one clever regex. The debug table shows **one row per category** (Mode / Hits / recent matches); regex text stays out of the UI.
- Turn on **Debug mode**, start the server, watch which categories light up (green = active, orange = dry-run), then promote a precise regex into `log_patterns` for that category.
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
PYTHONPATH=game-server-base python3 -m unittest discover -s game-server-base/tests -q
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
