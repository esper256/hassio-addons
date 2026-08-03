# Necesse Dedicated Server

This is the documentation shown inside Home Assistant for the **Necesse Dedicated Server** add-on.  
For the same guide on GitHub (including Docker/Portainer), see [README.md](README.md).

## Requirements

- Home Assistant OS / Supervised (**Apps** store)
- Host architecture **amd64** (SteamCMD). Not offered on aarch64.

## Quick start

1. Set **World name** and a **Server password** on the Configuration tab.
2. **Start** the app.
3. Forward **UDP 14159** on your router to this Home Assistant host.
4. In Necesse, join `your-ha-ip:14159`.
5. On the Info tab click **OPEN WEB UI** for status, build id, backups, and log tools (optional: **Show in sidebar**).

The first start downloads the dedicated server through Steam and can take several minutes. The **Logs** tab begins with `Home Assistant app version: …`, then `[steamcmd]` / `[game]` output. On a cold Steam cache the supervisor first waits until Steam app info is ready, then runs `app_update`.

### OPEN WEB UI vs the Ingress chip

- **OPEN WEB UI** (top of Info, only while the app is started) → the status page.
- The **Ingress** chip that opens “This app supports ingress for secure access.” → just an explanation, not the UI.

Status is served on internal port **8099** through Home Assistant’s authenticated proxy. No host port is published.

## Settings that matter

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
| Backup retention | `minimal` / `standard` / `extended` |
| HA notifications | Persistent notifications on crash / update failure / version mismatch |

Optional quiet hours: `update_window_start_hour` / `update_window_end_hour`. Leave empty to allow routine updates any time.

## After a Necesse client patch

1. Note the **Build** on Ingress.
2. Let players try to join.
3. With defaults, the add-on picks up a newer Steam build and updates when the server is empty.
4. Confirm Ingress shows a new build and a backup was taken.

## Backups

| Profile | Keeps roughly |
| --- | --- |
| `minimal` | 3 daily → 2 weekly → 3 monthly |
| `standard` (default) | 7 daily → 4 weekly → 12 monthly |
| `extended` | 7 daily → 8 weekly → 24 monthly → 2 yearly |

Empty/tiny worlds are skipped; failures back off; low free disk blocks backup/update work.

## Logs

| Where | What you’ll see |
| --- | --- |
| App **Logs** tab | Version banner, then supervisor / `[game]` / `[game-log]` / `[steamcmd]` |
| **OPEN WEB UI** | Status, pattern hits, raw tail, downloadable captures |

## Where files live

```
/data/game/          # Steam install (Server.jar, …)
/data/world/         # Necesse world / saves / cfg
/data/logs/          # game log files
/data/backups/       # world archives
/data/supervisor/    # status.json, steam_gate.json, log captures
```

## Notifications

With **HA notifications** enabled (default), the add-on creates Home Assistant persistent notifications for version mismatch, crashes, and Steam/update failures (Core API via Supervisor — not MQTT).

It also writes `/data/supervisor/status.json` continuously.

## Advanced notes

**Steam safeguards.** SteamCMD is serialized, spaced (≥90s), and exponentially backed off on failure so the add-on cannot tight-loop against Valve. Rate-limit-like responses cool down for hours. State: `/data/supervisor/steam_gate.json`.

**Log patterns.** Ready, game version, and player join/leave are active (promoted from real Necesse logs). Empty-server update gating uses SteamID64 join/leave tracking. Version-mismatch patterns stay empty until proven; Ingress dry-run highlights still help discover them.

**Docker / Portainer.** See [README.md](README.md#install-with-docker--portainer).

**Changelog.** [CHANGELOG.md](CHANGELOG.md)
