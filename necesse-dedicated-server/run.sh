#!/usr/bin/env bash
set -euo pipefail

# Home Assistant always mounts persistent storage at /data and writes options to
# /data/options.json. Keep game world/logs/backups under /data as well.
export OPTIONS_FILE="${OPTIONS_FILE:-/data/options.json}"
export GAME_PLUGIN="${GAME_PLUGIN:-/opt/games/necesse.yaml}"
export PYTHONPATH="${PYTHONPATH:-/opt}"

# Migrate legacy layout where the data volume was remapped over /home/necesse.
LEGACY_SAVES="/home/necesse/.config/Necesse"
if [ -d "${LEGACY_SAVES}/saves" ] && [ ! -e /data/world/saves ]; then
  echo "Migrating legacy Necesse saves into /data/world"
  mkdir -p /data/world
  cp -a "${LEGACY_SAVES}/." /data/world/ 2>/dev/null || true
fi

mkdir -p /data/world /data/logs /data/backups /data/supervisor /opt/game

# Ensure SteamCMD / game dirs remain writable on odd volume permissions.
chmod -R a+rwX /data /opt/game /opt/steamcmd 2>/dev/null || true

if [ -f "${OPTIONS_FILE}" ]; then
  echo "Using Home Assistant options from ${OPTIONS_FILE}"
else
  echo "No options.json at ${OPTIONS_FILE}; using environment defaults"
fi

exec python3 -m game_server --plugin "${GAME_PLUGIN}"
