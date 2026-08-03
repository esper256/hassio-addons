# Necesse Dedicated Server (Home Assistant add-on)

SteamCMD-powered Necesse dedicated server for Home Assistant OS.

Built on the shared [`game-server-base`](../game-server-base) supervisor:

- HA options → server settings
- Persistent Steam install under `/data/game`
- Update when empty / on version-mismatch signals
- Crash restarts + HA notifications (no MQTT)
- Generational world backups
- Ingress status page + log capture/suggest toolkit (no SSH)

See [DOCS.md](DOCS.md) for configuration details.
