# Changelog

## 1.0.0

- Initial Stationeers dedicated-server add-on (Steam app 600760, Unity Linux binary)
- Thin game layer over shared `game-server-base` supervisor (no Java)
- Debian Trixie image for Stationeers’ glibc requirement
- Ports: UDP 27016 (game) + UDP 27015 (Steam query); Ingress status UI
- High-tech light-blue / dark-blue Ingress theme
- World saves as folders under `/data/world/saves/<name>/` with by-kind zip backups
- Log join/leave/ready patterns ship as dry-run candidates until proven
