# Changelog

## 2.1.23

- **Update only when empty** copy clarifies it needs working player join/leave detection
- Remove HA `backup_interval_minutes` and `server_port` options (parallel/confusing knobs)
  - Scheduled backups run daily; history is controlled only by **Backup retention**
  - Necesse always listens on UDP **14159** inside the container; remap the host port on the Network tab
- **Backup before update** keeps only the newest pre-update archive (no growing trail)
- Add **Keep restore safety backups (days)** (default 7) for pre-restore / new-world safety copies
- Backup families are now distinct: rolling retention archives, one pre-update snapshot, age-limited pre-restore copies

## 2.1.22

- Version bump so Home Assistant refreshes the Configuration schema (2.1.21 follow-ups were invisible to already-installed apps)
- **Debug mode** toggle moved next to update settings; when off, Number of players hero stays hidden unless an *active* `player_count` log pattern exists (join/leave still used for empty-server updates)

## 2.1.21

- Activate Necesse `version_mismatch` log pattern for `Client "…" had wrong version (…)` — probes Steam for a newer build first; only then schedules stop/apply (bypass quiet hours, wait for empty, orderly `save`/`exit` with 240s budget, SteamCMD)
- Ingress theme colors come from per-game `ui_theme` in `games/game.yaml` (Necesse keeps green/amber)
- World restore UI: style restore like other action buttons; drop separate empty-world button; add **NEW WORLD** at the bottom of the backup selector
- Free disk hero no longer shows the “Min 512 MiB” hint (threshold still enforced for backups/updates)
- Ingress hero order: Uptime → Crashes … World save → Backups → Free disk; world save name links to download (file as-is, folder as stdlib zip)
- HA option **Debug mode** (default off): when off, hide Ingress log-watch pattern tooling; also hide Number of players until an active `player_count` pattern exists
- Log-watch table: one row per category, “Recent possible matches” (up to 3 lines per regex), Pattern column removed
- Base dry-run candidate regexes made cross-game (dropped Necesse-specific ready/player_count phrasing)

## 2.1.20

- Fix Ingress status page crash on GET `/` (`KeyError: '"archive"'`) caused by unescaped JSON examples in the HTML `str.format` template; add full-page render + placeholder lint tests so this class of bug fails CI

## 2.1.19

- Orderly stop: on HA/Docker SIGTERM, ask Necesse to `save`/`exit` and wait for a voluntary quit before SIGTERM/SIGKILL; use most of the 300s add-on stop grace for the game (240s) so supervisor cleanup can still finish; exit 0 on intentional stop; abort in-flight SteamCMD when stop is requested

## 2.1.18

- Ingress: **Start new empty world** — same confirm → stop → optional pre-restore safety copy → clear world files → restart flow as restore, but with no archive (game creates a fresh world)
- Save-game safety: refuse to wipe/replace live world data without a successful safety backup on disk; safety copies skip the "tiny world" skip; retention is the only archive deletion path (removed keep-5 pre-restore prune); restore API requires `confirm:true`

## 2.1.17

- Baseline cleanup: explicit `lifecycle` for status/healthz (crash-loop no longer looks healthy forever); `/healthz` uses a cheap snapshot; status reads no longer mutate `local_build_id`; shared privilege helpers; `outside_rotation` safety backups; `html.escape`; dead install-age formatter removed; UI tests assert goals rather than exact copy

## 2.1.16

- Ingress: restore a world backup with confirm → stop server → save current world as a pre-restore safety copy (outside normal rotation) → replace world → restart
- Status hero again shows **World save** and **Free disk** cards, grouped at the end
- Home Assistant notification when backups fail (interval unchanged)

## 2.1.15

- Ask Steam for game updates once daily at local 05:00 by default (was every 30 minutes)
- Plain-language status copy: schedule restarts for when nobody is online — drop “gating” jargon
- Ingress: **Update game server now** button (confirms first; stops the server, updates from Steam, restarts — disconnects anyone playing)
- Confine capture downloads; require POST to create captures; bind compose status port to localhost

## 2.1.14

- Fix fresh SteamCMD installs failing with `Missing file permissions` by running SteamCMD as the `gameserver` user (same owner as `/data/game` / `/data/steam-home`) instead of root
- Pin the Linux Steam platform on app-info readiness probes (same pin as `app_update`)
- On post-readiness `Missing configuration`, keep the normal retry/backoff budget instead of hard-aborting after the first failure (no appcache wipe — that only forces extra anonymous Steam traffic)
- Do not treat empty `steamapps/` scaffolding as an existing install; ensure `HOME`/`STEAM_HOME` point at `/data/steam-home` from `run.sh`

## 2.1.13

- Promote proven Necesse log patterns from Ingress dry-run highlights: ready (`Started server using port`), player join/leave (SteamID64), and an earlier game-version line (`Loading dedicated server on version`)
- Empty-server update gating now uses join/leave tracking (not “saved players” / garbage-collection lines)
- Status hero: Backups card with archive count plus oldest and newest backup ages

## 2.1.12

- Reorganize status hero: Server, Number of players, Uptime, Game version, Update pending, Game server crashes
- Uptime hint shows since first start / crash restart / server update; supervisor uptime moves under crashes
- Game version card merges human version + Steam build + installed age (removes separate Game files / Restarts cards)
- Collapse “Game server log watching pattern hits” (table + highlighted lines) once any active pattern exists; hide dry-run rows/tags for categories that already have an active pattern
- Remove Recent output section (use the Home Assistant app Logs tab instead)

## 2.1.11

- Status UI polish: dual uptime (game process + supervisor), clearer restart wording (“First start” / “Last restart: game crash” / “Last restart: server update”), “Game server crashes” label, and “Game files installed / XYZ ago”
- Show SteamCMD client version next to the supervisor version line
- Soft-refresh the Ingress status page via `api/ui` (removes full-page meta refresh flicker)
- Shared world-save locator: plugin `world_save.paths` for the active artifact (UI size); `backup_paths` for archives; path-guessing quarantined behind explicit heuristic opt-in
- Capture human-readable game version from logs (e.g. `1.3.1`) and show it on the status page; Necesse activates the proven “game version …” startup pattern

## 2.1.10

- Status UI cleanup: “Dedicated server supervisor v…”, drop redundant App version / Steam build / Player gating squares
- Restarts no longer count the first boot; show last start reason (boot / crash / update)
- Update pending shows last Steam check age; Game files shows when the install was last updated; World save shows human-readable save size
- Strip ANSI color codes from game logs; broaden dry-run ready/empty-server highlights
- Log tools: human actions first, captures in a dropdown + download, raw tail falls back to recent output and can render as text
- Keep SteamCMD Linux-only (remove Windows depot fallback)

## 2.1.9

- Fix fresh-install SteamCMD failure `Failed to install app '1169370' (Missing configuration)` by **waiting for Steam app info readiness** (`app_info_print` buildid) before `app_update`, instead of retrying installs as "transient"
- Use CLI `+force_install_dir`/`+app_update`, persist Steam home under `/data/steam-home`, and pin Necesse to Linux Steam depots (no Windows fallback)
- Generate `en_US.UTF-8` in the image to silence SteamCMD locale warnings
- Tighten error handling: handle game crashes and Steam/SteamCMD failures explicitly; do not treat failed Steam checks as “up to date” or failed updates as success; stop broad `except Exception` swallows that hid supervisor bugs

## 2.1.8

- Align status UI with Home Assistant Ingress defaults (port **8099**, Supervisor-only peers, `X-Ingress-Path` base href)
- Remove host `8080` mapping entirely — use **OPEN WEB UI** after start (not the Ingress info chip)
- Print a clear `Home Assistant app version: …` banner at the earliest startup point (shell + Python logs)

## 2.1.7

- Fix HAOS App store discovery: Supervisor rejects `timeout` above 300, which silently hid this app from the repository
- Cap start timeout at 300, set `io.hass.type=app`, drop unused `share` map
- Document amd64-only availability and Apps (formerly Add-ons) UI paths

## 2.1.6

- Drop v1 upgrade path: remove `/home/necesse` and `/opt/game` migrations, and the generic `path_migrations` machinery that existed only for that
- Remove transitional backup `keep_*` option shims; `backup_retention` is the only retention setting

## 2.1.5

- Add a process-wide Steam gate: serialize SteamCMD, enforce spacing, exponential retry backoff, and long cooldowns on failure/rate-limit signals
- Stop the failed-update 30s tight loop that could hammer Steam; pause applies and keep the current build running
- Floor auto-update polling at 15 minutes; hard-cap SteamCMD retries at 3
- Rewrite docs around user journeys: repo landing → game install guide; separate guide for building on `game-server-base`

## 2.1.4

- Stream SteamCMD install/update output into the Home Assistant Logs tab (`[steamcmd]`)
- Mirror file-only game log lines to Logs (`[game-log]`) with short-window dedupe against `[game]` stdout
- Flush supervisor logging so HA Logs stay near-realtime

## 2.1.3

- Simplify backup UX to one `backup_retention` profile (`minimal` / `standard` / `extended`)
- Standard = 7 daily → 4 weekly → 12 monthly cascade

## 2.1.2

- Alpha-safe log watching: no active Necesse regexes by default
- Generic candidate regexes run dry-run only and highlight hits in Ingress
- Pattern hit table + stale detection via `/api/logs/patterns`
- When player patterns are inactive, Steam updates still run; mismatch/player gating stays off

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
