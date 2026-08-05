# Stationeers Dedicated Server

Documentation shown inside Home Assistant. Full guide (including Docker): [README.md](README.md).

## Requirements

- Home Assistant OS / Supervised (**Apps** store)
- Host architecture **amd64** (SteamCMD). Not offered on aarch64.
- Recent glibc on the container side (this image uses Debian Trixie)

## Quick start

1. Set **Save name** and a **Server password** on Configuration (world defaults to **Mars2**; leave **Server name** blank for a generated `HAOS Stationeers ####`).
2. Keep **List on server browser** off unless you want a public listing.
3. **Start** the app (first Steam download can take several minutes — watch **Logs**).
4. Forward Network UDP **27016** (game) and **27015** (Steam query) on your router to this Home Assistant host.
5. In Stationeers, join via direct connect to `your-ha-ip:27016` (or the server list if you enabled public listing).
6. Info tab → **OPEN WEB UI** for status, backups, and restore (optional: **Show in sidebar**).

**OPEN WEB UI** (top of Info, while started) is the status page. The **Ingress** chip that only says the app supports ingress is an explanation, not the UI.

## Settings that matter

| Setting | What it does |
| --- | --- |
| Save name | Folder under `/data/world/saves/` |
| World / map | Map for a **new** save (default `Mars2`; also `Lunar`, `Europa3`, …) |
| Server name | Optional; blank → stable `HAOS Stationeers ####` for this install |
| Password / slots | Join controls |
| List on server browser | Public master-server listing (default **off**) |
| Start condition | New worlds only — e.g. `DefaultStart`, `Brutal`, `BrutalCommunity` |
| Pause when empty | Pause with nobody online |
| Autosave / interval | World persistence |
| Update on start | SteamCMD when the app starts (recommended) |
| Daily Steam check hour | Once-a-day Steam check (default **5**) |
| Update only when empty | Restart for updates only when nobody is online |
| Backup retention | `minimal` / `standard` / `extended` |
| HA notifications | Crash / update / version-mismatch alerts |
| Network → UDP ports | Host ports players use (defaults 27016 + 27015) |

## Backups and restore

Scheduled, pre-update, and pre-restore copies live under `/data/backups`. Stationeers worlds are save **folders** and are backed up as zip archives of that folder.

In **OPEN WEB UI**: restore a listed backup, choose **NEW WORLD**, or **Restore from upload**. A safety copy is kept first when world data exists.

## Logs

| Where | Contents |
| --- | --- |
| App **Logs** | Version banner, supervisor, `[game]`, `[steamcmd]` |
| **OPEN WEB UI** | Status, restore, raw tail, log captures |

## Data

```text
/data/game/   /data/world/   /data/logs/   /data/backups/   /data/supervisor/
```

## Changelog

[CHANGELOG.md](CHANGELOG.md)
