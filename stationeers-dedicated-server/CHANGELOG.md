# Changelog

## 1.0.15

- Hero card messages match the server status: lowercase (“running”, “player last joined…”, “up to date”)
- Pattern watching: **configured** / **stale** / **unused** (stale means a previous binary matched, this process has not); unused guesses collapse under an expander
- Replace highlighted lines with a copy-to-clipboard AI prompt for promoting `games/game.yaml` regexes; drop the extra “view recent game output” button (HA Logs already covers that)

## 1.0.14

- Free disk uses normal ink when healthy; warning color only when low
- Collapse pattern hits, log capture tools, and JSON API under one **Troubleshooting** expander
- World backups copy: restoring stops the server, makes a world backup, then restores the selected backup

## 1.0.13

- Backup card counts every restorable archive (scheduled, pre-update, pre-restore) — same set as the restore dropdown minus NEW WORLD
- Update card: when not up to date, show “Update available” and an in-card **Update now** button (replaces the “Checked … ago” hint)
- Join/leave games: Players card shows “Player last joined … ago” (green when likely occupied, amber when idle); exact count games keep a numeric count with “No count yet” while waiting

## 1.0.12

- Ingress UI polish for release users: primary status cards, update banner only when pending, button hierarchy, shorter backup copy, stacked restore/upload, collapsed troubleshooting logs, mobile layout, Steam vs package update wording

## 1.0.8

- Sync shared supervisor: broader dry-run log candidates; keep dry-run pattern rows visible alongside active ones

## 1.0.7

- Sync shared supervisor: package install clean-replace (no stale merge on HTTP archive updates)

## 1.0.6

- **Steam branch** option: Public (default) or Beta
- Sync shared supervisor: install-channel overrides, keep game stdin open, generic `mod_list` config_files format

## 1.0.5

- Sync shared supervisor: HTTP `package_install` path for non-Steam games; recent game output is game process only (Stationeers still uses SteamCMD)

## 1.0.4

- Sync shared supervisor: generic `config_files` + `world_prepare` launch helpers; signal-first stop when no stdin quit commands (Stationeers still uses stdin save/quit)

## 1.0.3

- Sync shared supervisor: presence unknown-leave clears to Idle; 24h max wait for empty before applying updates; log monitor follows `data_dir` logs without cross-source double-fires; drains/reopens across truncate/rotate

## 1.0.2

- Default world / map is **Mars2**; public server-browser listing defaults to **off**
- Server name is optional; blank → stable `HAOS Stationeers ####` per install
- Start-condition help text lists common kit ids (DefaultStart / Brutal / …)

## 1.0.1

- Promote proven log patterns: game version, client connect/disconnect, “No clients connected”
- `player_tracking_mode: presence` — Ingress shows Idle / Players Active (no numeric count)
- Shared supervisor: last 5 regex matches per pattern in the log-watch table

## 1.0.0

- Initial Stationeers dedicated-server add-on (Steam app 600760, Unity Linux binary)
- Docker/compose env options contributed by this plugin (`arg_map` / `settings_map` / templates → `docker_env_keys`), not the base supervisor
- Shared supervisor has no cross-game world-path heuristic; this plugin declares `world_save.paths`
- Thin game layer over shared `game-server-base` supervisor (no Java)
- Debian Trixie image for Stationeers’ glibc requirement
- Ports: UDP 27016 (game) + UDP 27015 (Steam query); Ingress status UI
- High-tech light-blue / dark-blue Ingress theme
- World saves as folders under `/data/world/saves/<name>/` with by-kind zip backups
- Log join/leave/ready patterns ship as dry-run candidates until proven
