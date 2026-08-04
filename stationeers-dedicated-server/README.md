# Stationeers Dedicated Server

Run a **Stationeers** (RocketWerkz) dedicated multiplayer server on Home Assistant OS (or Docker).  
SteamCMD keeps the build current, the world is backed up automatically, and **OPEN WEB UI** shows status, restore, and logs.

Other games / packaging your own: [repository README](../README.md) · [game-server-base](../game-server-base/README.md)

---

## Get running (Home Assistant)

Needs an **amd64** HAOS host (SteamCMD). On aarch64 the App store will not offer this app.

Stationeers’ Linux dedicated server needs a recent **glibc (2.40+)**. This image is based on Debian Trixie for that reason.

1. **Settings → Apps → App store → ⋮ → Repositories** → add `https://github.com/esper256/hassio-addons`
2. Install **Stationeers Dedicated Server**
3. **Configuration** — set at least:
   - **Save name** (default `FamilyStation` — no spaces)
   - **World / map** (default `Lunar`; used when the save does not exist yet)
   - **Server password** (recommended)
4. **Start** the app (first run downloads the server from Steam; can take several minutes — watch **Logs**)
5. Forward **UDP 27016** (game) and **UDP 27015** (Steam query) on your router to the Home Assistant host
6. In Stationeers, join via the server browser or direct connect to your HA host IP on port 27016

### OPEN WEB UI

With the app **started**, open the Info tab → **OPEN WEB UI** (optional: **Show in sidebar**).

That is the status page (build, players when known, world save, backups, restore, logs). It uses Home Assistant Ingress — no host port to publish. The Info “Ingress” chip that only explains ingress is not the UI.

---

## Settings worth knowing

| Setting | Notes |
| --- | --- |
| Save name / world map / server name / password / slots | What players join |
| List on server browser | Master-server listing (`ServerVisible`) |
| Pause when empty | Pause simulation with nobody online |
| Autosave / interval | World persistence (default every 300s) |
| Difficulty / start condition / location | Optional; only for **new** worlds. If you set condition or location, set difficulty too |
| Update on start | SteamCMD before launch (recommended) |
| Daily Steam check hour | Default **5** (5:00am local); clear to use the interval instead |
| Update only when empty | Wait for nobody online before restarting (needs join/leave detection) |
| Backup retention | `minimal` / `standard` / `extended` |
| HA notifications | Crash / update failure / version mismatch |
| Network → UDP ports | Host ports players use (defaults 27016 + 27015) |

Optional quiet hours (`update_window_start_hour` / `end`) further limit when a pending update may restart. Leave empty to allow any time once the server is empty.

Common **world / map** values for new saves: `Lunar`, `Mars2`, `Europa3`, `MimasHerschel`, `Vulcan`, `Venus`.

---

## Day to day

**After a Stationeers client patch** — with defaults, the app notices a newer Steam build and updates when empty (once player join/leave patterns are promoted). Confirm **OPEN WEB UI** shows a new build.

**Backups** under `/data/backups`:

| Kind | Role |
| --- | --- |
| `backup-*` | Daily history; thinned by retention |
| `pre-update-*` | One snapshot from the latest game update |
| `pre-restore-*` | Safety copies before restore / new world (kept 1 / 7 / 30 days by profile) |

Stationeers worlds are **folders**; backups **zip that folder**. Older `*.tar.gz` datadir snapshots can still be restored.

**Restore (OPEN WEB UI)** — pick a backup or **NEW WORLD** → confirm, or **Restore from upload**. The server stops, keeps a pre-restore safety copy when there is data, replaces the world, and restarts.

**Logs** — app **Logs** tab for supervisor / Steam / game; **OPEN WEB UI** for status, restore, and downloadable captures.

Player join/leave patterns start as Ingress dry-run candidates. Turn on **Debug mode**, watch highlights against real logs, then promote proven regexes into `games/game.yaml` `log_patterns` (maintainers) so “update only when empty” can wait for an empty server.

---

## Docker / Portainer

```bash
docker compose -f stationeers-dedicated-server/docker-compose.yml up -d --build
```

Set `SERVER_PASSWORD` / `WORLD_NAME` / `WORLD_TYPE` in the compose environment. UDP **27016** + **27015** for players; status UI on **localhost:8099** only (no Ingress auth outside HA — do not expose 8099 publicly). Data: `./data` → `/data`.

---

## Data layout

```text
/data/game/          # Steam install (rocketstation_DedicatedServer.x86_64)
/data/world/         # SavePath (saves/<world_name>/, settings.xml)
/data/logs/          # reserved for file logs if you change -logFile
/data/backups/       # world backups
/data/supervisor/    # status.json, steam gate, log captures
```

---

## Changelog

[CHANGELOG.md](CHANGELOG.md)
