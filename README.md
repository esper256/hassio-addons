# esper256 Home Assistant add-ons

Custom Home Assistant OS add-ons.

## Add-ons

| Add-on | Description |
| --- | --- |
| [necesse-dedicated-server](necesse-dedicated-server/) | Necesse dedicated server with SteamCMD auto-updates |

## Shared platform

[`game-server-base`](game-server-base/) is a **game-agnostic** SteamCMD supervisor. It must not contain game names, ports, or runtimes.

Each game add-on is a thin layer:

- vendored `game_server/` package (via sync script)
- one plugin YAML (`games/game.yaml`)
- runtime packages the game needs (e.g. OpenJDK for Necesse)
- HA `config.yaml` / docs / ports

### Portainer / Docker (Necesse)

```bash
docker compose -f necesse-dedicated-server/docker-compose.yml up -d --build
```

### Home Assistant

Add this repository URL in **Settings → Add-ons → Add-on store → Repositories**, then install **Necesse Dedicated Server**.

After changing the generic supervisor:

```bash
./scripts/sync-game-server-base.sh
```
