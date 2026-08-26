# Changelog

## 1.0.0

- First Core Keeper dedicated-server app on the shared supervisor
- SteamCMD app `1963720` (anonymous), Unity binary under Xvfb
- Default join path is Steam Datagram Relay (Game ID); no published UDP game port
- Stable per-install Game ID when the option is left blank
- World save is `worlds/<slot>.world.gzip` under `-datapath` `/data/world`
- Log patterns ship dry-run only until Ingress Debug mode proves hits
- Official Steam library capsule + store header used for HA `icon.png` / `logo.png`
