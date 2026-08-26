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
# HA Network can remap the *host* port; the container side is fixed at 7778
# in config.yaml. Passing -port enables Direct Connect (default). Steam Game
# ID join still works. (We do not use host_network.)
export SERVER_PORT="${SERVER_PORT:-7778}"

mkdir -p /data/world /data/logs /data/backups /data/supervisor /data/game /data/steam-home
# SteamCMD reads HOME for its log directory; keep it on the persistent volume.
export HOME="${STEAM_HOME:-/data/steam-home}"
export STEAM_HOME="${STEAM_HOME:-/data/steam-home}"

if [ -f "${OPTIONS_FILE}" ]; then
  echo "Using Home Assistant options from ${OPTIONS_FILE}"
else
  echo "No options.json at ${OPTIONS_FILE}; using environment defaults"
fi

# Blank HA game_id / server_password → stable per-install values (Game ID +
# Direct Connect join password). Passing -port is required for Direct Connect.
RESOLVED_GAME_ID="$(python3 /opt/haos_defaults.py game-id)"
RESOLVED_SERVER_PASSWORD="$(python3 /opt/haos_defaults.py password)"
export GAME_ID="${RESOLVED_GAME_ID}"
export SERVER_PASSWORD="${RESOLVED_SERVER_PASSWORD}"
echo "Game ID: ${GAME_ID}"
echo "Direct Connect: UDP ${SERVER_PORT} (IP:port + join password; Steam Game ID still works)"
echo "Join password: ${SERVER_PASSWORD}"
echo "Players join in Core Keeper → Multiplayer → Join Game (Game ID) or Join Game Via IP."

exec python3 -m game_server --plugin "${GAME_PLUGIN}"
