#!/usr/bin/env bash
set -euo pipefail

# Home Assistant always mounts persistent storage at /data and writes options to
# /data/options.json. Worlds, game binaries, logs, backups all live under /data.
export OPTIONS_FILE="${OPTIONS_FILE:-/data/options.json}"
export GAME_PLUGIN="${GAME_PLUGIN:-/opt/games/necesse.yaml}"
export PYTHONPATH="${PYTHONPATH:-/opt}"
export INSTALL_DIR="${INSTALL_DIR:-/data/game}"

# Migrate legacy layout where the data volume was remapped over /home/necesse.
LEGACY_SAVES="/home/necesse/.config/Necesse"
if [ -d "${LEGACY_SAVES}/saves" ] && [ ! -e /data/world/saves ]; then
  echo "Migrating legacy Necesse saves into /data/world"
  mkdir -p /data/world
  cp -a "${LEGACY_SAVES}/." /data/world/ 2>/dev/null || true
fi

# Migrate game binaries if an older image kept them only under /opt/game.
if [ ! -f /data/game/Server.jar ] && [ -f /opt/game/Server.jar ]; then
  echo "Migrating game install from /opt/game into /data/game"
  mkdir -p /data/game
  cp -a /opt/game/. /data/game/ 2>/dev/null || true
fi

mkdir -p /data/world /data/logs /data/backups /data/supervisor /data/game

if [ -f "${OPTIONS_FILE}" ]; then
  echo "Using Home Assistant options from ${OPTIONS_FILE}"
else
  echo "No options.json at ${OPTIONS_FILE}; using environment defaults"
fi

exec python3 -m game_server --plugin "${GAME_PLUGIN}"
