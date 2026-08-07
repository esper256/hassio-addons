# Factorio Dedicated Server

Run a **Factorio** dedicated multiplayer server on Home Assistant OS (or Docker).  
The app downloads Wube’s **free Linux headless package** (no Steam ownership on the server), backs up the world, and **OPEN WEB UI** shows status, restore, and logs.

Other games / packaging your own: [repository README](../README.md) · [game-server-base](../game-server-base/README.md)

---

## Get running (Home Assistant)

Needs an **amd64** HAOS host. On aarch64 the App store will not offer this app.

1. **Settings → Apps → App store → ⋮ → Repositories** → add `https://github.com/esper256/hassio-addons`
2. Install **Factorio Dedicated Server**
3. **Configuration** — set at least:
   - **Save name** (default `FamilyFactory` — no spaces)
   - **Game password** (recommended)
   - Leave **Server name** blank for a stable generated `HAOS Factorio ####`
   - Keep **Public server listing** off unless you add Factorio.com credentials
4. **Start** the app (first run downloads the headless package from factorio.com — watch **Logs** or OPEN WEB UI → **View recent game output**)
5. Forward **UDP 34197** on your router to the Home Assistant host
6. In Factorio → Multiplayer → Connect to address → your HA host IP (port 34197)

### OPEN WEB UI

With the app **started**, open the Info tab → **OPEN WEB UI** (optional: **Show in sidebar**).

That is the status page (build, players when known, world save, backups, restore, logs). It uses Home Assistant Ingress — no host port to publish. The Info “Ingress” chip that only explains ingress is not the UI.

---

## Settings worth knowing

| Setting | Notes |
| --- | --- |
| Save name / password / slots | What players join (save is `/data/world/saves/<name>.zip`) |
| Server name | Optional; blank → stable `HAOS Factorio ####` |
| LAN / public visibility | LAN on by default; public needs Factorio.com username + token |
| Pause when empty | Pause simulation with nobody online |
| Autosave interval | Minutes between Factorio autosaves (default 10) |
| Update on start | Check/download a newer headless package before launch (recommended) |
| Daily update check hour | Default **5** (5:00am local); clear to use the interval instead |
| Update only when empty | Wait for nobody online before restarting (uses `[JOIN]` / `[LEAVE]` logs) |
| Backup retention | `minimal` / `standard` / `extended` |
| HA notifications | Crash / update failure / version mismatch |
| Network → UDP port | Host port players use (default 34197) |

Optional quiet hours (`update_window_start_hour` / `end`) further limit when a pending update may restart. Leave empty to allow any time once the server is empty.

Factorio **requires a save before hosting**. On first boot (and after **NEW WORLD**), the supervisor runs `--create` automatically, then `--start-server`.

---

## Day to day

**After a Factorio client patch** — with defaults, the app notices a newer headless package on factorio.com and updates when empty. Confirm **OPEN WEB UI** shows a new version.

**Backups** under `/data/backups`:

| Kind | Role |
| --- | --- |
| `backup-*` | Daily history; thinned by retention |
| `pre-update-*` | One snapshot from the latest package update |
| `pre-restore-*` | Safety copies before restore / new world (kept 1 / 7 / 30 days by profile) |

Factorio worlds are single `.zip` saves; backups **copy that file as-is**. Older `*.tar.gz` datadir snapshots can still be restored.

**Restore (OPEN WEB UI)** — pick a backup or **NEW WORLD** → confirm, or **Restore from upload**. The server stops, keeps a pre-restore safety copy when there is data, replaces the world, and restarts (creating a fresh save after NEW WORLD).

**Logs** — app **Logs** tab for supervisor / download / game; **OPEN WEB UI** → **View recent game output** for the live buffer (and an empty-state hint while idle).

---

## Docker / Portainer

```bash
docker compose -f factorio-dedicated-server/docker-compose.yml up -d --build
```

Set `SERVER_PASSWORD` / `WORLD_NAME` in the compose environment. UDP **34197** for players; status UI on **localhost:8099** only (no Ingress auth outside HA — do not expose 8099 publicly). Data: `./data` → `/data`.

---

## Data layout

```text
/data/game/          # Headless install (bin/x64/factorio)
/data/world/         # write-data (saves/, server-settings.json, config.ini, mods/)
/data/logs/          # reserved
/data/backups/       # world backups
/data/supervisor/    # status.json, log captures
```

---

## Changelog

[CHANGELOG.md](CHANGELOG.md)
