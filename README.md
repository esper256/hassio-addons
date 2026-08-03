# esper256 Home Assistant add-ons

Custom Home Assistant OS add-ons.

## Add-ons

| Add-on | Description |
| --- | --- |
| [necesse-dedicated-server](necesse-dedicated-server/) | Necesse dedicated server with SteamCMD auto-updates |

## Shared platform

[`game-server-base`](game-server-base/) is a reusable SteamCMD dedicated-server supervisor used by the Necesse add-on (and intended for Terraria / Factorio / Stationeers later). It handles:

1. HA `options.json` / env configuration
2. SteamCMD install + retries
3. Log/build monitoring for empty-server and version-mismatch updates
4. Crash restarts
5. Optional status HTTP dashboard
6. World backups

### Portainer / Docker quickstart

```bash
docker compose -f game-server-base/docker-compose.yml up -d --build
```

### Home Assistant

Add this repository URL in **Settings → Add-ons → Add-on store → Repositories**, then install **Necesse Dedicated Server**.

After changing files under `game-server-base/`, sync them into the add-on build context:

```bash
./scripts/sync-game-server-base.sh
```
