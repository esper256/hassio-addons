# Changelog

## 1.0.1

- Promote Unity NetCode `RpcSystem received bad protocol version` as the active version-mismatch pattern (from a real client-too-old session). Dump headers that repeat that phrase, and disconnect reasons like `App_Min`, are not mismatch signals
- JSON API log-pattern links rescan the on-disk log with the same matchers as Ingress and return example lines for not-yet-configured categories (works without Debug mode)

## 1.0.0

- First Core Keeper dedicated-server app on the shared supervisor
- SteamCMD app `1963720` (anonymous), Unity binary under Xvfb (official Pugstorm requirement)
- Default join path is **Direct Connect** on UDP 7778 (`-port` + password); Steam Game ID join still works; no public server listing
- Stable per-install Game ID and join password when those options are left blank; invalid pins are ignored; Game ID recovered from GameID.txt / ServerConfig.json if needed
- World save is `worlds/<slot>.world.gzip` under `-datapath` `/data/world` (slots 0–29)
- Backups named with the slot file; retention and pre-update keep-one are per slot; restore of another slot’s archive is refused until World slot matches
- Launch wrapper prints official `GameInfo.txt` (and legacy `GameID.txt`) to HA Logs
- Ready / game-version log patterns promoted from a live dedicated-server boot
- Official Steam library capsule + store header used for HA `icon.png` / `logo.png`
