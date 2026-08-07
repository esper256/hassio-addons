# Changelog

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
