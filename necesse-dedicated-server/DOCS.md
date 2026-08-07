# Necesse Dedicated Server

Documentation shown inside Home Assistant. Full guide (including Docker): [README.md](README.md).

## Requirements

- Home Assistant OS / Supervised (**Apps** store)
- Host architecture **amd64** (SteamCMD). Not offered on aarch64.

## Quick start

1. Set **World name** and a **Server password** on Configuration.
2. **Start** the app (first Steam download can take several minutes — watch **Logs**).
3. Forward Network UDP **14159** on your router to this Home Assistant host.
4. In Necesse, join `your-ha-ip` on that port.
5. Info tab → **OPEN WEB UI** for status, backups, and restore (optional: **Show in sidebar**).

**OPEN WEB UI** (top of Info, while started) is the status page. The **Ingress** chip that only says the app supports ingress is an explanation, not the UI.

## Settings that matter

| Setting | What it does |
| --- | --- |
| World name | Save/world players join |
| Server password | Join password |
| Server slots / MOTD | Capacity and welcome text |
| Pause when empty | Pause with nobody online |
| Java options | Memory etc. (default `-Xms512M -Xmx2G`) |
| Steam branch | `public` (default) or `experimental` — clients must match |
| Update on start | SteamCMD when the app starts (recommended) |
| Daily Steam check hour | Once-a-day Steam check (default **5**) |
| Update only when empty | Restart for updates only when nobody is online |
| Backup retention | `minimal` / `standard` / `extended` |
| HA notifications | Crash / update / version-mismatch alerts |
| Network → UDP port | Host port players use (default 14159) |

## Backups and restore

Scheduled, pre-update, and pre-restore copies live under `/data/backups`. Necesse worlds are `.zip` files and are backed up as a direct copy of that save.

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
