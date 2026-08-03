# No plugins here

Game plugins intentionally do **not** live in `game-server-base`.

Put each game’s YAML in that game’s add-on/image directory as `games/game.yaml`.

The base image exposes `/opt/games` as a mount point and requires `GAME_PLUGIN`.
