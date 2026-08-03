# game-server-base

Generic supervisor for SteamCMD dedicated game servers. **Contains no game-specific identity.**

Each game supplies only:

1. a plugin YAML/JSON (`GAME_PLUGIN`)
2. any runtime packages its binary needs (Java, etc.) in its own image/add-on
3. HA/Portainer metadata (ports, options schema, docs)

## What lives here

| Piece | Role |
| --- | --- |
| `game_server/` | Shared Python supervisor |
| `Dockerfile` | SteamCMD + Python base image (no game runtimes, ports, or plugins) |
| `tests/` | Uses a synthetic `example.game.yaml` fixture |

## What does **not** live here

- Game names, Steam app IDs, log regexes, stop commands
- Game UDP/TCP ports
- Game runtimes (OpenJDK, etc.)
- HA add-on `config.yaml` / translations

Those belong in each game’s thin add-on/image directory.

## Plugin contract

Point `GAME_PLUGIN` at a YAML/JSON file. Minimum fields:

- `name`, `steam_app_id`, `executable`, `install_marker`
- optional: `arg_map`, `log_patterns`, `stop_stdin_commands`, `path_migrations`, backup paths, etc.

See `tests/fixtures/example.game.yaml` for the shape.

## Run

```bash
# build generic base
docker build -f game-server-base/Dockerfile -t game-server-base .

# run with a game plugin mounted in
# (the image must also contain that game's runtime, or use the game-specific Dockerfile)
docker run --rm \
  -e GAME_PLUGIN=/opt/games/game.yaml \
  -v /path/to/game.yaml:/opt/games/game.yaml:ro \
  -v $PWD/data:/data \
  -p 8080:8080 \
  game-server-base
```

## Sync into HA add-ons

```bash
./scripts/sync-game-server-base.sh
```

Copies **only** `game_server/` into each add-on build context. Plugin YAML in each add-on is never overwritten.
