# Changelog

## 1.0.0

- Initial Factorio dedicated-server add-on (Steam app 427520, Linux headless host)
- Thin game layer over shared `game-server-base` supervisor
- Generic supervisor additions used by this game: `config_files` (server-settings.json + config.ini) and `world_prepare` (`--create` when the save is missing)
- Port UDP **34197**; Ingress status UI with black / Factorio-orange theme
- World saves as single `.zip` under `/data/world/saves/<name>.zip` with by-kind file-copy backups
- Player tracking via Factorio `[JOIN]` / `[LEAVE]` console lines (presence mode)
- Blank server name → stable `HAOS Factorio ####` per install
