# Hytale Dedicated Server

This app installs Hypixel’s official **Linux dedicated server** with the Hytale Downloader CLI (not SteamCMD). You must own Hytale. Running the server does **not** stop you playing on the same account.

Hytale uses **UDP/QUIC** (not TCP). First start needs **two** sign-ins in **Open Web UI** (different Hytale logins: download, then server).

## Configure and start

1. On **Configuration**, set at least:
   - **World name** (default `default`)
   - **Game password** (recommended)
2. Leave **Server name** blank for a stable generated `HAOS Hytale ####`.
3. **Start** the app. Open **Open Web UI**. If Home Assistant restarts the app during the first sign-in, press **Start** again. A new device code is issued; you do not need to uninstall.
4. Sign in from **Open Web UI** or from the **Logs** tab (same URL and device code). Open the URL that includes `user_code=` in a new browser tab. Hytale emails a login code for your account — that is **not** the device code. After you are signed in, open the URL again so you reach **Authorize a device**, then paste the device code only if that page asks. The official downloader waits **10 minutes**. First download is several gigabytes.
5. A **second** sign-in card appears for the running server (a different Hytale login) only if Java has no tokens. Repeat. After that, tokens are stored in `auth.enc` (Encrypted, keyed from a machine-id we keep under `/data/supervisor`).
6. Forward **UDP 5520** on your router to this Home Assistant host (TCP is not used). That is the official dedicated-server port.
7. In Hytale → Multiplayer → Direct Connect → your HA host IP **and port `:5520`**. Leaving the port off uses the client hint `:25565`, which will not match this server.

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
| Network → UDP port | Host port players use (default **5520**, QUIC). Direct Connect must include `:5520`. |

## Backups and restore

Use **OPEN WEB UI** → **World backups** to restore a listed backup, start **NEW WORLD**, or upload a save. Restoring stops the server, makes a world backup, then restores onto the active universe folder. Anyone online is disconnected.

## Logs

- App **Logs** — enough to finish both sign-ins without Open Web UI. Look for `Sign-in from HA Logs`, the URL with `user_code=`, and `Device code` / `Authorization code`. Prefer the URL that already includes the code.
- **OPEN WEB UI** — sign-in card plus troubleshooting
