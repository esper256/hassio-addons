# Necesse Dedicated Server (Home Assistant add-on)

SteamCMD-powered Necesse dedicated server for Home Assistant OS.

Thin layer over [`game-server-base`](../game-server-base):

- `games/game.yaml` — all Necesse-specific server identity (Steam app id, args, log patterns, migrations)
- OpenJDK 17 — Necesse runtime dependency
- HA `config.yaml` / translations / UDP 14159

No Necesse logic belongs in the generic supervisor package.

See [DOCS.md](DOCS.md) for configuration details.
