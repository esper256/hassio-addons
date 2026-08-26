# Core Keeper Dedicated Server

## Configure and start

1. On **Configuration**, set at least:
   - **World name** (default `FamilyCore`)
   - Leave **Game ID** blank unless you want to pin a specific join code
   - Leave **World slot** at `0` unless you already keep several caverns
2. Do **not** look for a “list on server browser” toggle — this app has none. The default is **private / invite-only** (Game ID join, no public listing, no game UDP port).
3. **Start** the app. First Steam download can take several minutes (~650 MB) — watch **Logs**.
4. Copy the **Game ID** from **Logs** (line `Game ID: …`, or the `----- GameInfo.txt -----` block after Unity boots). Treat it like a password; anyone with the code can join.
5. In Core Keeper → **Multiplayer** → **Join Game**, paste that Game ID.

Friends do **not** connect by IP:port, and you do **not** need to forward a game UDP port. Steam Datagram Relay is Pugstorm’s default; it can add latency versus a port-forwarded Direct Connect session (this app does not enable Direct Connect).

## OPEN WEB UI

With the app **started**, use **OPEN WEB UI** on the Info tab (optional: **Show in sidebar**).

That page shows server status, players, game version / updates, world save, backups, restore, and troubleshooting tools. It uses Home Assistant Ingress — no extra host port.

The Info **Ingress** chip that only explains ingress is not the UI.

## Settings that matter

| Setting | Notes |
| --- | --- |
| World name / slots | Name connecting clients see; max players (default 8) |
| World slot | Which save to host (`0` → `0.world.gzip`, … `29`). Switching slot does not delete the other files |
| World mode / seed | Only for a **new** slot (`0` Normal, `1` Hard, `2` Creative, `4` Casual) |
| Game ID | Invite code; blank → stable generated ID for this install. Invalid values are ignored |
| Steam branch | `public` (default) or `beta` — clients must match |
| Update on start | SteamCMD before launch (recommended) |
| Daily Steam check hour | Default **5** |
| Update only when empty | Wait for nobody online before restarting |
| Backup retention | `minimal` / `standard` / `extended` |
| HA notifications | Crash / update failure / version mismatch |

The world file is often missing until Unity creates the cavern (first player join, or a graceful stop after a new world has started). Backups skip an empty slot until then. Open Web UI backs up the **active** slot only.

## Backups and restore

Use **OPEN WEB UI** → **World backups** to restore a listed backup, start **NEW WORLD**, or upload a save. Restoring stops the server, makes a world backup, then restores the selected backup. Anyone online is disconnected. Upload a `.world.gzip` for this game (single-file save).

## Logs

- App **Logs** — supervisor, SteamCMD, and game output (includes **Game ID:**)
- **OPEN WEB UI** → **Troubleshooting** — captures and status tools
