# Factorio Dedicated Server

Run a **Factorio** dedicated multiplayer server on Home Assistant OS (or Docker).  
The app downloads Wube’s **free Linux headless package**, backs up the world, and **OPEN WEB UI** shows status, restore, and logs.

Other games / packaging your own: [repository README](../README.md) · [game-server-base](../game-server-base/README.md)

---

## Install method (not Steam)

This is **not** a SteamCMD game. Wube publishes a free headless Linux build; anonymous Steam for app `427520` returns “No subscription”.

| | |
| --- | --- |
| **What the app downloads** | Headless archive from `factorio.com` into `/data/game` |
| **Channel** | **Stable** (default) or **Experimental** — clients must match |
| **Steam on the host** | Not used — no Steam ownership or Steam login on the server |
| **Factorio.com login to install** | Not required |
| **Players** | Still need a normal owned Factorio client to join |

Updates check the factorio.com release API for the selected channel and replace the headless package when a newer build exists.

A log line `Got EOF on stdin; closing` (Factorio “Error”) after `Hosting game` / `InGame` is harmless noise when stdin is closed; current builds keep stdin open so you should not see it.

---

## Factorio.com authentication (public listing only)

Leave **Factorio.com username** / **token** empty for the default setup: LAN visibility and/or direct IP connect. That does **not** need a Factorio.com account on the server.

Turn on **Public server listing** only if you want the server in Factorio’s public browser. Then you must set:

1. Your **Factorio.com username** (not Steam, not email)
2. Your **authentication token** from [factorio.com/profile](https://www.factorio.com/profile) (Reveal token) — prefer the token over your account password

This is Wube’s multiplayer matching auth, not game install auth. Keep the token secret; regenerate it on the profile page if it leaks.

---

## Get running (Home Assistant)

Needs an **amd64** HAOS host. On aarch64 the App store will not offer this app.

1. **Settings → Apps → App store → ⋮ → Repositories** → add `https://github.com/esper256/hassio-addons`
2. Install **Factorio Dedicated Server**
3. **Configuration** — set at least:
   - **Save name** (default `FamilyFactory` — no spaces)
   - **Game password** (recommended)
   - Leave **Server name** blank for a stable generated `HAOS Factorio ####`
   - Leave **Space Age DLC** off unless every player owns Space Age (set this before first start)
   - Leave **Public server listing** off and Factorio.com username/token empty unless you want the public browser
4. **Start** the app (first run downloads the free headless package — no login; watch the app **Logs** tab)
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
| LAN visibility | On by default (Play on LAN) |
| Public server listing | Off by default; needs Factorio.com username + token (see above) |
| Factorio.com username / token | Only for public listing — not used to download the server |
| Space Age DLC | Default **off**. Headless is always the Space Age–capable binary; this only toggles DLC mods in `mod-list.json`. Off = base-game mode (plain clients OK). On = every player needs Space Age. Set before first world create; turning off later usually needs NEW WORLD |
| Release channel | `stable` (default) or `experimental` headless package |
| Pause when empty | Pause simulation with nobody online |
| Autosave interval | Minutes between Factorio autosaves (default 10) |
| Update on start | Check/download a newer headless package before launch (recommended) |
| Daily update check hour | Default **5** (5:00am local); clear to use the interval instead |
| Update only when empty | Wait for nobody online before restarting (needs **active** join/leave patterns — promote from Debug mode dry-run hits first) |
| Debug mode | Show Ingress log-watch table (broad dry_run regex rows + hits) |
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

**Logs** — app **Logs** tab for supervisor / download / game. **OPEN WEB UI** → **View recent game output** is only the running game’s output (empty until the server process is up).

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
