# Factorio Dedicated Server

Documentation shown inside Home Assistant. Full guide (including Docker): [README.md](README.md).

## Requirements

- Home Assistant OS / Supervised (**Apps** store)
- Host architecture **amd64** (Linux headless package). Not offered on aarch64.

## How the game is installed

This add-on does **not** use SteamCMD. On start it downloads Wube’s **free Linux headless package** from factorio.com into `/data/game` (no Steam ownership and no Factorio.com login for install). Players still need an owned Factorio client to join.

**Space Age DLC** (Configuration): default **off** = base-game content only.

How this maps to downloads/clients:

- **Players:** owning Space Age means a Space Age–capable client binary that can load the DLC mods. A plain (non–Space Age) client **cannot** load those mods.
- **This server:** factorio.com publishes **one** free Linux headless package, and it is already the Space Age–capable binary (it ships the DLC content). There is no separate “base-only headless” download.
- **Our toggle:** does **not** swap binaries. It enables/disables the official DLC mods (`elevated-rails`, `quality`, `space-age`, and on newer builds `recycler`) in `mods/mod-list.json` before world create / launch. Off = that Space Age–capable headless runs in base-game mode (plain clients can join). On = DLC mods loaded (every player needs Space Age).

Changing this after a world exists usually requires OPEN WEB UI → **NEW WORLD**.

**Release channel** (Configuration): **stable** (default) or **experimental**. Clients must match the channel you install. Changing channel pulls that build on the next update check / restart with update-on-start. Prefer **stable** unless you intentionally want experimental clients.

If the app crash-loops after switching from 2.0.x to 2.1.x with an error in `quality/.../recycling.lua`, that was a bad overlay install (old files left behind). Current builds clean-replace `/data/game` on package update; restart once after updating the add-on so it re-extracts.

Anonymous Steam for app `427520` fails with “No subscription” — that path is intentionally unused here.

After a good start you should see `Hosting game` and `InGame`. A Factorio `Got EOF on stdin` Error line alone is not a failure (older builds logged it when stdin was closed).

## Factorio.com username and token

These settings are **not** for installing or updating the server.

| Goal | What you need |
| --- | --- |
| LAN / direct IP connect (default) | Leave **Public server listing** off; leave username and token empty |
| Appear in the public Factorio browser | Turn **Public server listing** on, then set Factorio.com **username** + **token** |

Get the token from [factorio.com/profile](https://www.factorio.com/profile) (Reveal). Use the token, not your account password. This is matching-server auth only — keep the token secret.

## Quick start

1. Set **Save name** and a **Game password** on Configuration (leave **Server name** blank for a generated `HAOS Factorio ####`).
2. Leave **Space Age DLC** off unless all players own Space Age (decide before first start).
3. Leave **Public server listing** off and Factorio.com username/token empty unless you want the public browser (see above).
4. **Start** the app (first headless package download can take several minutes — watch the app **Logs** tab; no login required).
5. Forward Network UDP **34197** on your router to this Home Assistant host.
6. In Factorio, Multiplayer → Connect to address → `your-ha-ip:34197` (or LAN browser if LAN visibility is on).
7. Info tab → **OPEN WEB UI** for status, backups, and restore (optional: **Show in sidebar**).

**OPEN WEB UI** (top of Info, while started) is the status page. The **Ingress** chip that only says the app supports ingress is an explanation, not the UI.

## Settings that matter

| Setting | What it does |
| --- | --- |
| Save name | `.zip` under `/data/world/saves/` (created automatically if missing) |
| Server name | Optional; blank → stable `HAOS Factorio ####` for this install |
| Password / slots | Join controls (`0` slots = unlimited) |
| LAN visibility | Default on (Play on LAN) |
| Public server listing | Off by default; needs Factorio.com username + token |
| Factorio.com username / token | Public listing only — not used for package download |
| Space Age DLC | Default off (base game); on = DLC mods enabled |
| Release channel | `stable` (default) or `experimental` |
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
