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
6. On your router, forward **UDP 14159** to your Home Assistant host.
7. In Necesse, connect to your HA host IP on port `14159` (with the password if you set one).

The first start downloads the dedicated server through Steam. That can take several minutes. Watch the add-on **Logs** tab for `[steamcmd]` progress, then `[game]` / startup lines.

Open the add-on **Ingress** UI (or the “Open Web UI” style entry) for status, build id, backups, and log tools.

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
| Auto-update interval | How often to ask Steam for a newer build (`0` = off; values under 15 become 15) |
| Update only when empty | Wait until nobody is online before restarting for an update |
| Backup retention | `minimal` / `standard` / `extended` — how much history to keep |
| HA notifications | Persistent notifications on crash / update failure / version mismatch |

Quiet-hour window options (`update_window_start_hour` / `end`) are optional. Leave them empty to allow routine updates any time.

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

Retention is one dropdown:

| Profile | Keeps roughly |
| --- | --- |
| `minimal` | 3 daily → 2 weekly → 3 monthly |
| `standard` (default) | 7 daily → 4 weekly → 12 monthly |
| `extended` | 7 daily → 8 weekly → 24 monthly → 2 yearly |

Backups refuse empty/tiny worlds, back off after failures, and won’t run if free disk is too low.

### Logs

- **Home Assistant → add-on Logs tab** — live supervisor + game + SteamCMD output (`[game]`, `[game-log]`, `[steamcmd]`)
- **Ingress** — status, pattern hits, raw tail, downloadable log captures (no SSH needed)

---

## Install with Docker / Portainer

From this repository:

```bash
docker compose -f necesse-dedicated-server/docker-compose.yml up -d --build
```

Or in Portainer: deploy that compose file, then set `SERVER_PASSWORD` / `WORLD_NAME` in the environment block.

- Game port: **UDP 14159**
- Status UI: **HTTP 8080** (`/healthz`, `/api/status`, log tools)
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

If you expose port `8080` (or call the same APIs through Ingress tooling):

```yaml
rest:
  - resource: http://homeassistant.local:8080/api/status
    sensor:
      - name: Necesse Players
        value_template: "{{ value_json.monitor.player_count }}"
      - name: Necesse Update Pending
        value_template: "{{ value_json.update_pending }}"
      - name: Necesse Build
        value_template: "{{ value_json.local_build_id }}"
```

---

## Under the hood (only if you need it)

### Why this isn’t a thin wrapper anymore

Older versions wrapped a third-party image and bridged HA options with fragile shell/`jq`. This add-on vendors a shared Steam supervisor and a small Necesse plugin (`games/game.yaml` + OpenJDK + HA metadata).

### Steam is rate-limited on purpose

SteamCMD calls are serialized, spaced, and backed off on failure so a bad Steam day cannot spin a tight retry loop against Valve. Rate-limit-like output cools down for hours; state is kept in `/data/supervisor/steam_gate.json`.

### Player / version log patterns (alpha-safe)

Active regexes ship **empty**. Generic candidates only *highlight* likely join/leave/version lines in Ingress until you promote proven ones into `games/game.yaml`. Until then:

- Steam `buildid` auto-updates still work
- “Update only when empty” cannot see players yet (it won’t block forever)
- Version-mismatch auto-update stays off until you promote a pattern

To promote: play / attempt a bad join → Ingress **Log pattern hits** → copy a clean dry-run regex into `log_patterns` → rebuild/restart.

### Changelog

See [CHANGELOG.md](CHANGELOG.md).
