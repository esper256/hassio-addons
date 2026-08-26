# Changelog

## 1.0.2

- Ready pattern is `Listening on ip:` (UDP port bound). `Started session with info:` is GameInfo / public-IP print and can happen after a client already connected
- Join/leave promoted from a live session: in-world `[userid:…] player Name connected` and `Disconnected from userid:` (same internal userid). Steam id on auth does not match leave. No player_count (the game does not log a headcount)
- `App_Min` / `AppException_Max` / `Misc_Timeout` are disconnect reasons, not version mismatch — `App_Min` also appears on a normal leave
- JSON API expander removed. Troubleshooting has one **Log pattern prompt** link (`/api/logs/prompt`) and the debug textarea share the same plain-text block, including a log-file rescan. Unused list/tail/suggest/patterns JSON endpoints deleted.
- Debug promote prompt: join/leave identity must match; write regexes from sample lines not guess patterns; ready is port bind not a later GameInfo line; disconnect reasons are not version_mismatch; omit player_count without a headcount; edit game.yaml plus tests

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
