# esper256 Home Assistant add-ons

Steam-powered dedicated game servers for **Home Assistant OS** (and plain Docker/Portainer).  
Each game add-on keeps itself updated through SteamCMD, backs up worlds, and restarts after crashes — so a family server does not go stale after a client patch.

## I want to run a game

Pick the game and follow that guide. Everything you need to install and run it is there.

| Game | Start here |
| --- | --- |
| **Necesse** | [necesse-dedicated-server/README.md](necesse-dedicated-server/README.md) |

### Home Assistant in one line

**Settings → Add-ons → Add-on store → ⋮ → Repositories** → add:

`https://github.com/esper256/hassio-addons`

Then install the game add-on from that repository and continue in the game’s README.

## I want to package a different Steam game

This repo’s shared supervisor (`game-server-base`) is game-agnostic. Use it when you want another dedicated server on the same update/backup/status machinery.

→ [How to build on game-server-base](game-server-base/README.md)

## Repository layout (optional reading)

| Path | What it is |
| --- | --- |
| `necesse-dedicated-server/` | Necesse HA add-on + Docker image (what most people install) |
| `game-server-base/` | Shared SteamCMD supervisor (no game identity) |
| `scripts/sync-game-server-base.sh` | Copies the supervisor into game add-ons after base changes |
