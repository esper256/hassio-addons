# esper256's Home Assistant OS game servers

A small ecosystem of **dedicated game server** apps for Home Assistant OS, built on one shared supervisor (`game-server-base`).

> **AI experiment:** This repository is a deliberate experiment in AI-assisted coding. The add-ons work and are useful, but the project has been **100% written with AI**.

## Games

| Game | Guide |
| --- | --- |
| **[Necesse](https://necessegame.com/)** | [necesse-dedicated-server/GUIDE.md](necesse-dedicated-server/GUIDE.md) |
| **[Stationeers](https://store.steampowered.com/app/544550/Stationeers/)** | [stationeers-dedicated-server/GUIDE.md](stationeers-dedicated-server/GUIDE.md) |
| **[Factorio](https://factorio.com/)** | [factorio-dedicated-server/GUIDE.md](factorio-dedicated-server/GUIDE.md) |
| **[Core Keeper](https://store.steampowered.com/app/1621690/Core_Keeper/)** | [core-keeper-dedicated-server/GUIDE.md](core-keeper-dedicated-server/GUIDE.md) |

Current titles are **amd64 only**.

## Quick start (Home Assistant)

1. **Settings → Apps → App store → ⋮ → Repositories** → add:

   ```text
   https://github.com/esper256/hassio-addons
   ```

2. Install the game you want from that repository.
3. Open that game’s [guide](#games) for ports and first-run notes (and the in-app **Documentation** tab after install).
4. Configure → **Start** → port-forward → join from the game client.

## What each app provides

Each Home Assistant app gives you automatic updates, world backups, Home Assistant notifications, and an HTTP dashboard to monitor the game server and supervisor — open it with **Open Web UI** on the app Info tab once the app is running:

![Open Web UI example (Necesse)](necesse-dedicated-server/images/ingress-ui.png)

---

## Shared supervisor

`game-server-base` is not an installable app. It is the reusable engine every game folder vendors. The base supervisor handles SteamCMD or HTTP package install and auto-update, process supervision, crash restarts, scheduled world save backups, and a log-pattern scraping toolkit to enable the supervisor to have some vision into the game server state.

Each game add-on is a thin layer on top (Steam/package identity, ports, world paths, log patterns, theme). Packaging another dedicated server is mostly: copy a game folder, fill in `games/game.yaml`, keep game identity out of the base package, sync, bump `{supervisor}.{minor}.{game patch}` (supervisor **3.0** → apps **3.0.0**).

→ [How to package a game](game-server-base/README.md)

## Docker without Home Assistant

Each game folder includes a `docker-compose.yml` that *may* run outside HAOS. That path is **not tested** as a first-class product: you would need to supply a Home Assistant–style options JSON (and related env) yourself, and there is **no separate documentation** for that setup. Prefer the Home Assistant apps above unless you are comfortable reverse-engineering from the compose file and `config.yaml` options.

## Repository layout

| Path | Role |
| --- | --- |
| `*-dedicated-server/GUIDE.md` | GitHub end-user guide (features, install, screenshot) |
| `*-dedicated-server/README.md` | Short HA Info / store blurb |
| `*-dedicated-server/DOCS.md` | HA Documentation tab (configure / ports / Open Web UI) |
| `game-server-base/` | Shared supervisor; sync into game apps with `sync-into-addons.sh` |
| `tests/` | Repo checks for HA app `config.yaml` rules |
