# Changelog

## 1.0.6

- Promote proven Factorio log patterns to **active**: ready (`Hosting game at` / CreatingGame→InGame), `Factorio X.Y.Z` version, `[JOIN]` / `[LEAVE]` presence
- No version-mismatch pattern — Factorio did not log a usable line when an experimental client hit a stable server; option defaults off

## 1.0.5

- Log patterns: ship **dry-run only** again (empty active `log_patterns`); Factorio-specific regexes moved to `log_pattern_candidates` until Ingress Debug mode proves hits
- Shared supervisor: broader generic dry-run guesses; UI keeps dry-run rows visible even when an active pattern exists

## 1.0.4

- Fix package updates: **clean-replace** the headless install tree instead of merging (stale `quality/.../recycling.lua` from 2.0 left after a 2.1 overlay caused crash loops)

## 1.0.3

- **Space Age DLC** option (default **off**): writes `mods/mod-list.json` so base-game servers do not load quality / elevated-rails / space-age / recycler
- Saves created with Space Age on cannot simply turn it off — use NEW WORLD after disabling

## 1.0.2

- **Release channel** option: Stable (default) or Experimental headless builds from factorio.com
- Keep game stdin open so Factorio no longer logs a scary “Got EOF on stdin” Error after a successful host
- Package update-check log lines no longer say “Steam”

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
