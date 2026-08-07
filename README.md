# esper256 Home Assistant add-ons

Steam dedicated game servers for **Home Assistant OS** (and plain Docker).  
Each game app updates through SteamCMD, backs up the world, and can restart after crashes.

## Run a game

| Game | Guide |
| --- | --- |
| **Necesse** | [necesse-dedicated-server/README.md](necesse-dedicated-server/README.md) |
| **Stationeers** | [stationeers-dedicated-server/README.md](stationeers-dedicated-server/README.md) |
| **Factorio** | [factorio-dedicated-server/README.md](factorio-dedicated-server/README.md) |

### Add this repository in Home Assistant

**Settings → Apps → App store → ⋮ → Repositories** → add:

```text
https://github.com/esper256/hassio-addons
```

Install the game app from that repository, then follow its README (configure → start → port-forward → join).

Only folders with `config.yaml` appear in the store. `game-server-base/` is shared supervisor code, not an installable app.

**Architecture:** current Steam games here are **amd64 only**. On aarch64 HAOS the store correctly hides them.

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
