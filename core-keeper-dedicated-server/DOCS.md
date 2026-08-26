# Core Keeper Dedicated Server

## Configure and start

1. On **Configuration**, set at least:
   - **World name** (default `FamilyCore`)
   - Leave **Game ID** blank unless you want to pin a specific join code
2. **Start** the app. First Steam download can take several minutes — watch **Logs**.
3. Copy the **Game ID** from **Logs** (line `Game ID: …`) or **OPEN WEB UI** once the server is up.
4. In Core Keeper → **Multiplayer** → **Join Game**, paste that Game ID.

This server uses Steam Datagram Relay. Friends do **not** connect by IP:port, and you do **not** need to forward a game UDP port on your router.

## OPEN WEB UI

With the app **started**, use **OPEN WEB UI** on the Info tab (optional: **Show in sidebar**).

That page shows server status, players, game version / updates, world save, backups, restore, and troubleshooting tools. It uses Home Assistant Ingress — no extra host port.

The Info **Ingress** chip that only explains ingress is not the UI.

## Settings that matter

| Setting | Notes |
| --- | --- |
| World name / slots | What this cavern is called; max players (default 8) |
| World slot | Save index (default `0` → `0.world.gzip`) |
| World mode / seed | Only for a **new** slot (`0` Normal, `1` Hard, `2` Creative, `4` Casual) |
| Game ID | Join code; blank → stable generated ID for this install |
| Steam branch | `public` (default) or `beta` — clients must match |
| Update on start | SteamCMD before launch (recommended) |
| Daily Steam check hour | Default **5** |
| Update only when empty | Wait for nobody online before restarting |
| Backup retention | `minimal` / `standard` / `extended` |
| HA notifications | Crash / update failure / version mismatch |

The world file is often created only after the first player joins (~30s). Backups skip an empty slot until then.

## Backups and restore

Use **OPEN WEB UI** → **World backups** to restore a listed backup, start **NEW WORLD**, or upload a save. Restoring stops the server, makes a world backup, then restores the selected backup. Anyone online is disconnected. Upload a `.world.gzip` for this game (single-file save).

## Logs

- App **Logs** — supervisor, SteamCMD, and game output (includes **Game ID:**)
- **OPEN WEB UI** → **Troubleshooting** — captures and status tools
