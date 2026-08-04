# Necesse Dedicated Server

Run a **Necesse** dedicated multiplayer server on Home Assistant OS (or Docker/Portainer).  
SteamCMD keeps the server build current, worlds are backed up on a simple retention schedule, and the add-on can notify Home Assistant if something goes wrong.

If you are here for a different game, go back to the [repository README](../README.md).  
If you want to package your own Steam game on this platform, see [game-server-base](../game-server-base/README.md).

---

## Install on Home Assistant OS

Requires an **amd64** Home Assistant OS host (SteamCMD). On aarch64 machines the App store will not offer this app.

1. In Home Assistant: **Settings → Apps → App store** (older UI: Add-ons).
2. Open the menu (⋮) → **Repositories** → add:

   `https://github.com/esper256/hassio-addons`

3. Refresh / check for updates, find **Necesse Dedicated Server**, and install it.
4. Open the add-on’s **Configuration** tab and set at least:
   - **World name** — the save players will join (default `FamilyWorld`)
   - **Server password** — recommended for a house server
5. Start the add-on.
6. On your router, forward the Network UDP port (default **14159**) to your Home Assistant host.
7. In Necesse, connect to your HA host IP on that same port (with the password if you set one).

The first start downloads the dedicated server through Steam. That can take several minutes. Watch the app **Logs** tab — the very first lines print `Home Assistant app version: …` so you can confirm the install. On a cold Steam cache the supervisor waits for app info readiness before installing.

### Status page (OPEN WEB UI)

1. Start the app (it must be running).
2. On the Info tab, click **OPEN WEB UI** (top of the page — not the “Ingress” info chip).
3. Optional: enable **Show in sidebar** for a permanent Necesse entry.

That UI is served through Home Assistant Ingress on internal port **8099**. No host port is published, so nothing clashes with other `:8080` services.

The Info-tab **Ingress** chip that only says “This app supports ingress…” is an explanation dialog, not the status page.

---

## Settings that matter

You do not need every advanced knob. These are the ones families usually touch:

| Setting | What it does |
| --- | --- |
| World name | Which world file to load/create |
| Server password | Join password |
| Server slots | Max players |
| Server MOTD | Message shown on join |
| Pause when empty | Pause the world with nobody online |
| Java options | Memory etc. (default `-Xms512M -Xmx2G`) |
| Update on start | Run SteamCMD when the add-on starts (recommended) |
| Daily Steam check hour | Local hour to ask Steam once a day for a newer build (default **5** = 5:00am) |
| Auto-update interval | Only used if the daily hour is cleared (`0` = off; values under 15 become 15) |
| Update only when empty | Wait until nobody is online before restarting (needs working join/leave detection) |
| Backup retention | `minimal` / `standard` / `extended` — scheduled history + pre-restore keep window |
| HA notifications | Persistent notifications on crash / update failure / version mismatch |
| Network → UDP port | Port players type to join on this HA machine (default 14159; change only if already taken) |

Optional quiet hours (`update_window_start_hour` / `end`) further limit when a pending update may restart the server. Leave them empty to allow the restart any time once the server is empty.

---

## Day-to-day use

### Is the server up?

- Add-on shows **running**
- Ingress shows a build id and healthy status
- Players can join on UDP `14159`

### After a Necesse client patch

1. Note the **Build** on Ingress.
2. Let kids try to join. If the server is behind, they may fail to connect.
3. With defaults, the add-on notices a newer Steam build (or a version-mismatch log line once patterns are promoted) and updates when the server is empty.
4. Confirm a new backup appeared under the backup store and that Ingress shows a new build.

### Backups

Three archive kinds live under `/data/backups`:

1. **Scheduled** (`backup-*.tar.gz`) — daily creates; thinned by the retention profile
2. **Pre-update** (`pre-update-*.tar.gz`) — one snapshot from the latest game-code update (only the newest is kept)
3. **Pre-restore** (`pre-restore-*.tar.gz`) — safety copies before restore / new world; age window from the same profile

| Profile | Scheduled history | Pre-restore keep |
| --- | --- | --- |
| `minimal` | 3 daily → 2 weekly → 3 monthly | 1 day |
| `standard` (default) | 7 daily → 4 weekly → 12 monthly | 7 days |
| `extended` | 7 daily → 8 weekly → 24 monthly → 2 yearly | 30 days |

Backups refuse empty/tiny worlds, back off after failures, and won’t run if free disk is too low. Backup failures create a Home Assistant notification.

**Restore from Ingress:** pick a backup (or **NEW WORLD** at the bottom of the list) → **Restore selected backup** → confirm. Or use **Restore from upload** to push a world save file. The server stops; if any world data exists it is saved as a pre-restore safety copy first; then the world is replaced and the server restarts. Upload apply mode follows how the game stores its world (single file vs folder), from the same `world_save` paths used by the World save card — not from guessing the upload alone. Archives are only deleted by their family’s retention rule.

### Logs

- **Home Assistant → app Logs tab** — starts with a version banner, then supervisor + game + SteamCMD (`[game]`, `[game-log]`, `[steamcmd]`)
- **OPEN WEB UI** — status (world save size with download link, backups, free disk), pattern hits, world restore, raw tail, downloadable log captures (no SSH / no host port)

---

## Install with Docker / Portainer

From this repository:

```bash
docker compose -f necesse-dedicated-server/docker-compose.yml up -d --build
```

Or in Portainer: deploy that compose file, then set `SERVER_PASSWORD` / `WORLD_NAME` in the environment block.

- Game port: **UDP 14159**
- Status UI: **HTTP 8099** (`/healthz`, `/api/status`, log tools) — mapped only for plain Docker; HAOS uses Ingress instead
- Persistent data: bind-mount `./data` → `/data` (already in the sample compose)

Home Assistant notifications are off in the sample compose (`HA_NOTIFICATIONS=false`) because there is no Supervisor API outside HAOS.

---

## Where files live

Everything important is under `/data` (the add-on data volume, or your Docker bind mount):

```
/data/game/          # Steam install (Server.jar, …)
/data/world/         # Necesse world / saves / cfg
/data/logs/          # game log files
/data/backups/       # world archives
/data/supervisor/    # status.json, steam_gate.json, log captures
```

---

## Optional: Home Assistant sensors

Prefer OPEN WEB UI / sidebar for day-to-day checks. For sensors, use Ingress or a future Core API push — avoid publishing a host status port.

---

## Under the hood (only if you need it)

### Why this isn’t a thin wrapper anymore

Older versions wrapped a third-party image and bridged HA options with fragile shell/`jq`. This add-on vendors a shared Steam supervisor and a small Necesse plugin (`games/game.yaml` + OpenJDK + HA metadata).

### Steam is rate-limited on purpose

SteamCMD calls are serialized, spaced, and backed off on failure so a bad Steam day cannot spin a tight retry loop against Valve. Rate-limit-like output cools down for hours; state is kept in `/data/supervisor/steam_gate.json`.

### Player / version log patterns

Necesse now ships proven active patterns in `games/game.yaml` for ready, game version, and player join/leave (SteamID64). That lets updates wait until nobody is online before restarting.

Version-mismatch auto-update stays off until a mismatch line is seen in Ingress and promoted. Generic dry-run candidates still highlight other likely lines.

To promote more (or for a new game on this architecture): play / attempt a bad join → Ingress **Log pattern hits** → craft a tight regex from the real line → put it in `log_patterns` → rebuild/restart.

### Changelog

See [CHANGELOG.md](CHANGELOG.md).
