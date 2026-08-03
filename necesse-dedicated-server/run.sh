#!/usr/bin/env bash
# Thin HA entrypoint: point at the Necesse plugin and start the generic supervisor.
set -euo pipefail

export OPTIONS_FILE="${OPTIONS_FILE:-/data/options.json}"
export GAME_PLUGIN="${GAME_PLUGIN:-/opt/games/game.yaml}"
export PYTHONPATH="${PYTHONPATH:-/opt}"
export INSTALL_DIR="${INSTALL_DIR:-/data/game}"

mkdir -p /data/world /data/logs /data/backups /data/supervisor /data/game

if [ -f "${OPTIONS_FILE}" ]; then
  echo "Using Home Assistant options from ${OPTIONS_FILE}"
else
  echo "No options.json at ${OPTIONS_FILE}; using environment defaults"
fi

exec python3 -m game_server --plugin "${GAME_PLUGIN}"
