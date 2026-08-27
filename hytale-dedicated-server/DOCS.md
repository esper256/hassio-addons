# Hytale Dedicated Server

This app installs Hypixel’s official **Linux dedicated server** with the Hytale Downloader CLI (not SteamCMD). You must own Hytale. Running the server does **not** stop you playing on the same account.

Hytale uses **UDP/QUIC** (not TCP). First start needs **two** sign-ins in **Open Web UI** (different Hytale logins: download, then server).

## Configure and start

1. On **Configuration**, set at least:
   - **World name** (default `default`)
   - **Game password** (recommended)
2. Leave **Server name** blank for a stable generated `HAOS Hytale ####`.
3. **Start** the app. Open **Open Web UI**.
4. When the sign-in card appears, **open the link in a new browser tab** (not inside this panel), enter the code, come back. Wait for the several-gigabyte download.
5. A **second** sign-in card appears for the running server. Repeat. After that, tokens stay on disk.
6. Forward **UDP 5520** on your router to this Home Assistant host (TCP is not used).
7. In Hytale → Multiplayer → Direct Connect → your HA host IP (port 5520).

## OPEN WEB UI

With the app **started**, use **OPEN WEB UI** on the Info tab (optional: **Show in sidebar**).

That page shows server status, the sign-in card when needed, world save, backups, restore, and troubleshooting tools. It uses Home Assistant Ingress — no extra host port.

## Settings that matter

| Setting | Notes |
| --- | --- |
| World name / password / slots | What players join |
| Server name | Optional; blank → `HAOS Hytale ####` |
| Java memory | Default `-Xms2G -Xmx4G` (official floor is 4 GB RAM for the host) |
| Release channel | `release` (default) or `pre-release` — clients must match |
| Update on start | Re-run the official downloader before launch (needs the saved download login) |
| Daily update check hour | Default **5** |
| Backup retention | `minimal` / `standard` / `extended` |
| HA notifications | Crash / update failure alerts |
| Network → UDP port | Host port players use (default 5520, QUIC) |

## Backups and restore

Use **OPEN WEB UI** → **World backups** to restore a listed backup, start **NEW WORLD**, or upload a save. Restoring stops the server, makes a world backup, then restores onto the active universe folder. Anyone online is disconnected.

## Logs

- App **Logs** — supervisor, downloader, and game output (device codes are also printed here)
- **OPEN WEB UI** — sign-in card plus troubleshooting
