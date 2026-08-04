# Necesse Dedicated Server

Run a **Necesse** dedicated multiplayer server on Home Assistant OS (or Docker).  
SteamCMD keeps the build current, the world is backed up automatically, and **OPEN WEB UI** shows status, restore, and logs.

Other games / packaging your own: [repository README](../README.md) · [game-server-base](../game-server-base/README.md)

---

## Get running (Home Assistant)

Needs an **amd64** HAOS host (SteamCMD). On aarch64 the App store will not offer this app.

1. **Settings → Apps → App store → ⋮ → Repositories** → add `https://github.com/esper256/hassio-addons`
2. Install **Necesse Dedicated Server**
3. **Configuration** — set at least:
   - **World name** (default `FamilyWorld`)
   - **Server password** (recommended)
4. **Start** the app (first run downloads the server from Steam; can take several minutes — watch **Logs**)
5. Forward **UDP 14159** on your router to the Home Assistant host (change the Network port in HA only if 14159 is already taken)
6. In Necesse, join your HA host IP on that port

### OPEN WEB UI

With the app **started**, open the Info tab → **OPEN WEB UI** (optional: **Show in sidebar**).

That is the status page (build, players when known, world save, backups, restore, logs). It uses Home Assistant Ingress — no host port to publish. The Info “Ingress” chip that only explains ingress is not the UI.

---

## Settings worth knowing

| Setting | Notes |
| --- | --- |
| World name / password / slots / MOTD | What players join |
| Pause when empty | Pause simulation with nobody online |
| Java options | Default `-Xms512M -Xmx2G` |
| Update on start | SteamCMD before launch (recommended) |
| Daily Steam check hour | Default **5** (5:00am local); clear to use the interval instead |
| Update only when empty | Wait for nobody online before restarting (needs join/leave detection) |
| Backup retention | `minimal` / `standard` / `extended` |
| HA notifications | Crash / update failure / version mismatch |
| Network → UDP port | Host port players use (default 14159) |

Optional quiet hours (`update_window_start_hour` / `end`) further limit when a pending update may restart. Leave empty to allow any time once the server is empty.

---

## Day to day

**After a Necesse client patch** — with defaults, the app notices a newer Steam build (or a version-mismatch once that pattern is active) and updates when empty. Confirm **OPEN WEB UI** shows a new build.

**Backups** under `/data/backups`:

| Kind | Role |
| --- | --- |
| `backup-*` | Daily history; thinned by retention |
| `pre-update-*` | One snapshot from the latest game update |
| `pre-restore-*` | Safety copies before restore / new world (kept 1 / 7 / 30 days by profile) |

Necesse worlds are single `.zip` files; backups **copy that file as-is** (no double compression). Older `*.tar.gz` datadir snapshots can still be restored.

**Restore (OPEN WEB UI)** — pick a backup or **NEW WORLD** → confirm, or **Restore from upload**. The server stops, keeps a pre-restore safety copy when there is data, replaces the world, and restarts.

**Logs** — app **Logs** tab for supervisor / Steam / game; **OPEN WEB UI** for status, restore, and downloadable captures.

---

## Docker / Portainer

```bash
docker compose -f necesse-dedicated-server/docker-compose.yml up -d --build
```

Set `SERVER_PASSWORD` / `WORLD_NAME` in the compose environment. UDP **14159** for players; status UI on **localhost:8099** only (no Ingress auth outside HA — do not expose 8099 publicly). Data: `./data` → `/data`.

---

## Data layout

```text
/data/game/          # Steam install
/data/world/         # Necesse data (saves under saves/worlds/)
/data/logs/          # game logs
/data/backups/       # world backups
/data/supervisor/    # status.json, steam gate, log captures
```

---

## Changelog

[CHANGELOG.md](CHANGELOG.md)
