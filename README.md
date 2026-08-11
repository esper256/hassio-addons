# esper256 Home Assistant game servers

A small ecosystem of **dedicated game server** apps for Home Assistant OS, built on one shared supervisor (`game-server-base`).

Each game add-on is a thin layer: Steam (or package) identity, ports, and log patterns. The supervisor supplies auto-updates, player-aware restarts, generational world backups, crash recovery, and an Ingress **Open Web UI** for day-to-day management.

![Open Web UI example (Necesse)](necesse-dedicated-server/images/ingress-ui.png)

> **AI experiment:** This repository is a deliberate experiment in AI-assisted coding. The add-ons work and are useful, but the project has been **100% written with AI**.

## Games

Pick a game guide for features, Home Assistant install steps, ports, Docker, and screenshots:

| Game | GitHub guide |
| --- | --- |
| **[Necesse](https://necessegame.com/)** | [necesse-dedicated-server/GUIDE.md](necesse-dedicated-server/GUIDE.md) |
| **[Stationeers](https://store.steampowered.com/app/544550/Stationeers/)** | [stationeers-dedicated-server/GUIDE.md](stationeers-dedicated-server/GUIDE.md) |
| **[Factorio](https://factorio.com/)** | [factorio-dedicated-server/GUIDE.md](factorio-dedicated-server/GUIDE.md) |

**Quick start in Home Assistant:** Settings → Apps → App store → ⋮ → Repositories → add `https://github.com/esper256/hassio-addons`, install the game app, then follow that game’s guide (and the in-app **Documentation** tab after install). Current titles are **amd64 only**.

Inside Home Assistant, each app shows a short `README.md` on Info and spartan `DOCS.md` on the Documentation tab. The `GUIDE.md` files above are for readers on GitHub.

## Shared supervisor

`game-server-base` is not an installable app. It is the reusable engine every game folder vendors:

- SteamCMD or HTTP package install/update, with a Steam rate gate
- Process supervision and crash restarts
- By-kind world backups (scheduled, pre-update, pre-restore) and Ingress restore / NEW WORLD / upload
- Log-pattern toolkit (dry-run → promote) so updates can wait for an empty server
- Ingress status HTTP used as **Open Web UI**

Packaging another dedicated server is mostly: copy a game folder, fill in `games/game.yaml`, keep game identity out of the base package, sync, bump version.

→ [How to package a game](game-server-base/README.md)

## Layout

| Path | Role |
| --- | --- |
| `*-dedicated-server/GUIDE.md` | GitHub end-user guide (features, install, screenshot) |
| `*-dedicated-server/README.md` | Short HA Info / store blurb |
| `*-dedicated-server/DOCS.md` | HA Documentation tab (configure / ports / Open Web UI) |
| `game-server-base/` | Shared supervisor; sync into game apps with `sync-into-addons.sh` |
| `tests/` | Repo checks for HA app `config.yaml` rules |
