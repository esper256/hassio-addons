#!/usr/bin/env bash
# Thin HA entrypoint: point at the Core Keeper plugin and start the generic supervisor.
set -euo pipefail

VERSION="${APP_VERSION:-}"
if [[ -z "${VERSION}" || "${VERSION}" == "dev" ]]; then
  if [[ -f /etc/hassio_app_version ]]; then
    VERSION="$(tr -d '[:space:]' </etc/hassio_app_version)"
  fi
fi
VERSION="${VERSION:-unknown}"

echo "============================================================"
echo " Core Keeper Dedicated Server"
echo " Home Assistant app version: ${VERSION}"
echo "============================================================"

export APP_VERSION="${VERSION}"
export OPTIONS_FILE="${OPTIONS_FILE:-/data/options.json}"
export GAME_PLUGIN="${GAME_PLUGIN:-/opt/games/game.yaml}"
export PYTHONPATH="${PYTHONPATH:-/opt}"
export INSTALL_DIR="${INSTALL_DIR:-/data/game}"
export DATA_DIR="${DATA_DIR:-/data/world}"
# HA Ingress default port; override for plain Docker if needed.
export STATUS_HTTP_PORT="${STATUS_HTTP_PORT:-8099}"

mkdir -p /data/world /data/logs /data/backups /data/supervisor /data/game /data/steam-home
# SteamCMD reads HOME for its log directory; keep it on the persistent volume.
export HOME="${STEAM_HOME:-/data/steam-home}"
export STEAM_HOME="${STEAM_HOME:-/data/steam-home}"

if [ -f "${OPTIONS_FILE}" ]; then
  echo "Using Home Assistant options from ${OPTIONS_FILE}"
else
  echo "No options.json at ${OPTIONS_FILE}; using environment defaults"
fi

# Blank HA game_id → stable per-install Game ID (Steam Datagram Relay join code).
# Do not export SERVER_PORT: setting -port switches Core Keeper into Direct
# Connect and requires forwarded UDP ports. Default is Game ID join.
RESOLVED_GAME_ID="$(python3 /opt/haos_defaults.py)"
export GAME_ID="${RESOLVED_GAME_ID}"
echo "Game ID: ${GAME_ID}"
echo "Players join in Core Keeper → Multiplayer → Join Game (not via IP:port)."

exec python3 -m game_server --plugin "${GAME_PLUGIN}"
