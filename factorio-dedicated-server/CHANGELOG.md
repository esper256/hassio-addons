# Changelog

## 1.0.1

- Install from Wube’s **free headless package** (factorio.com), not SteamCMD — anonymous Steam returns “No subscription” for app 427520
- Shared supervisor: generic `package_install` HTTP archive path + clearer “View recent game output” link (game process only; install/update stays in the HA Logs tab)
- Docs / HA option text: install needs no login; Factorio.com username + token are only for public listing

## 1.0.0

- Initial Factorio dedicated-server add-on
- Thin game layer over shared `game-server-base` supervisor
- Generic supervisor additions: `config_files` (server-settings.json + config.ini) and `world_prepare` (`--create` when the save is missing)
- Port UDP **34197**; Ingress status UI with black / Factorio-orange theme
- World saves as single `.zip` under `/data/world/saves/<name>.zip` with by-kind file-copy backups
- Player tracking via Factorio `[JOIN]` / `[LEAVE]` console lines (presence mode)
- Blank server name → stable `HAOS Factorio ####` per install
