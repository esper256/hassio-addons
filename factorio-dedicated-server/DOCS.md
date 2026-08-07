# Factorio Dedicated Server

Documentation shown inside Home Assistant. Full guide (including Docker): [README.md](README.md).

## Requirements

- Home Assistant OS / Supervised (**Apps** store)
- Host architecture **amd64** (Linux headless package). Not offered on aarch64.

## Quick start

1. Set **Save name** and a **Game password** on Configuration (leave **Server name** blank for a generated `HAOS Factorio ####`).
2. Keep **Public server listing** off unless you add Factorio.com username + token.
3. **Start** the app (first headless package download can take several minutes — watch the app **Logs** tab).
4. Forward Network UDP **34197** on your router to this Home Assistant host.
5. In Factorio, Multiplayer → Connect to address → `your-ha-ip:34197` (or LAN browser if LAN visibility is on).
6. Info tab → **OPEN WEB UI** for status, backups, and restore (optional: **Show in sidebar**).

**OPEN WEB UI** (top of Info, while started) is the status page. The **Ingress** chip that only says the app supports ingress is an explanation, not the UI.

## Settings that matter

| Setting | What it does |
| --- | --- |
| Save name | `.zip` under `/data/world/saves/` (created automatically if missing) |
| Server name | Optional; blank → stable `HAOS Factorio ####` for this install |
| Password / slots | Join controls (`0` slots = unlimited) |
| LAN / public visibility | LAN default on; public needs Factorio.com credentials |
| Pause when empty | Pause with nobody online |
| Autosave interval | Minutes between autosaves |
| Update on start | Check/download headless package when the app starts (recommended) |
| Daily update check hour | Once-a-day factorio.com check (default **5**) |
| Update only when empty | Restart for updates only when nobody is online |
| Backup retention | `minimal` / `standard` / `extended` |
| HA notifications | Crash / update / version-mismatch alerts |
| Network → UDP port | Host port players use (default 34197) |

## Backups and restore

Scheduled, pre-update, and pre-restore copies live under `/data/backups`. Factorio worlds are single `.zip` saves and are backed up by copying that file as-is.

In **OPEN WEB UI**: restore a listed backup, choose **NEW WORLD**, or **Restore from upload**. A safety copy is kept first when world data exists. After **NEW WORLD**, the next start runs Factorio `--create` for a fresh map.

## Logs

| Where | Contents |
| --- | --- |
| App **Logs** | Version banner, supervisor, download / install, `[game]` |
| **OPEN WEB UI** → **View recent game output** | Running game process output only (empty until the server is up) |

## Data

```text
/data/game/   /data/world/   /data/logs/   /data/backups/   /data/supervisor/
```

## Changelog

[CHANGELOG.md](CHANGELOG.md)
