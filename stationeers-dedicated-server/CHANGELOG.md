# Changelog

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
