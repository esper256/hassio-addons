# esper256 Home Assistant add-ons

Dedicated game servers for **Home Assistant OS** (and plain Docker).  
Most titles update through SteamCMD; **Factorio** uses Wube’s free headless package from factorio.com. Each app backs up the world, can restart after crashes, and ships an **OPEN WEB UI** (Ingress) for status, restore, and troubleshooting.

> **AI experiment:** This repository is a deliberate experiment in AI-assisted coding. The add-ons work and are useful, but the project has been **100% written with AI**.

## Run a game

| Game | Guide | OPEN WEB UI |
| --- | --- | --- |
| **Necesse** | [necesse-dedicated-server/README.md](necesse-dedicated-server/README.md) | [screenshot](necesse-dedicated-server/images/ingress-ui.png) |
| **Stationeers** | [stationeers-dedicated-server/README.md](stationeers-dedicated-server/README.md) | [screenshot](stationeers-dedicated-server/images/ingress-ui.png) |
| **Factorio** | [factorio-dedicated-server/README.md](factorio-dedicated-server/README.md) | [screenshot](factorio-dedicated-server/images/ingress-ui.png) |

### Add this repository in Home Assistant

**Settings → Apps → App store → ⋮ → Repositories** → add:

```text
https://github.com/esper256/hassio-addons
```

Install the game app from that repository, then follow its README: configure → start → port-forward → join. With the app started, open **OPEN WEB UI** on the Info tab for the status page (no extra host port).

Only folders with `config.yaml` appear in the store. `game-server-base/` is shared supervisor code, not an installable app.

**Architecture:** current games here are **amd64 only**. On aarch64 HAOS the store correctly hides them.

## Add another Steam game

The shared supervisor is game-agnostic. Copy an existing game add-on, point `games/game.yaml` at your dedicated server, and keep game identity out of `game-server-base/`.

→ [How to package a game](game-server-base/README.md)

## Layout

| Path | Role |
| --- | --- |
| `necesse-dedicated-server/` | Necesse app |
| `stationeers-dedicated-server/` | Stationeers app (Unity / Linux Steam dedicated server) |
| `factorio-dedicated-server/` | Factorio app (free Linux headless package from factorio.com) |
| `game-server-base/` | Shared SteamCMD supervisor; sync into game apps with `sync-into-addons.sh` |
| `tests/` | Repo checks for HA app `config.yaml` rules |
