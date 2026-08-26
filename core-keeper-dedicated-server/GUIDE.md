# Core Keeper Dedicated Server

Run a **[Core Keeper](https://store.steampowered.com/app/1621690/Core_Keeper/)** dedicated multiplayer server on Home Assistant OS (or Docker).  
SteamCMD keeps the build current, the world is backed up automatically, and **Open Web UI** (Ingress) is the day-to-day control surface.

> Looking at this from inside Home Assistant? Use the app’s **Documentation** tab (`DOCS.md`) for configure/start. This page is the GitHub guide.

---

## What you get

- SteamCMD install and updates (`public` or `beta` branch)
- **Game ID join** via Steam Datagram Relay (no router port-forward for the game)
- Player-aware update restarts (join/leave detection once patterns are promoted)
- Generational world backups, plus pre-update and pre-restore safety copies
- **Open Web UI**: status, players, game version / updates, world download, restore, upload, troubleshooting
- HA notifications for crash / update failure / version mismatch
- Image includes Xvfb — Core Keeper’s Unity dedicated server needs a virtual display

**Architecture:** amd64 only (SteamCMD). Not offered on aarch64 HAOS.

---

## Install in Home Assistant

1. **Settings → Apps → App store → ⋮ → Repositories** → add:

   ```text
   https://github.com/esper256/hassio-addons
   ```

2. Install **Core Keeper Dedicated Server**.
3. Open the app → **Documentation** tab for configuration, Game ID join, and Open Web UI notes.
4. Set at least **World name**, then **Start**.
5. Copy the **Game ID** from **Logs** (`Game ID: …`).
6. In Core Keeper → **Multiplayer** → **Join Game**, paste that Game ID.

With the app started, use **Open Web UI** on the Info tab (optional: **Show in sidebar**).

---

## Open Web UI

Ingress status page (no extra host port to publish):

- Server / players / game version / update
- World save download, backups, restore, and upload
- Collapsed **Troubleshooting** (log captures and JSON API)

Restoring stops the server, makes a world backup, then restores the selected backup. Anyone online is disconnected.

---

## Joining (Game ID, not IP)

Core Keeper’s dedicated server defaults to **Steam Datagram Relay**. Players paste a Game ID in-game. There is no published UDP game port, and you should not forward one unless you later switch the server to Direct Connect yourself (this app does not).

The Game ID is stable for this install when **Game ID** is left blank (generated once, reused on restart). Pin one only if you already have a code you want to keep.

---

## Docker / Portainer

```bash
docker compose -f core-keeper-dedicated-server/docker-compose.yml up -d --build
```

Set `WORLD_NAME` in the compose environment. Leave `GAME_ID` unset for a stable generated join code. Status UI on **localhost:8099** only (no Ingress auth outside HA — do not expose 8099 publicly). Data: `./data` → `/data`. No UDP game port is mapped.

---

## Data layout

```text
/data/game/          # Steam install (CoreKeeperServer)
/data/world/         # -datapath (ServerConfig.json, worlds/<n>.world.gzip)
/data/logs/          # Unity -logfile (server.log)
/data/backups/       # world backups
/data/supervisor/    # status.json, steam gate, log captures, instance salt
```

The `.world.gzip` for slot 0 often appears only after the first player is in the cavern for a short time.

---

## More

- In-app docs: [DOCS.md](DOCS.md)
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Shared supervisor / packaging another game: [game-server-base](../game-server-base/README.md)
- All games in this repo: [repository README](../README.md)
