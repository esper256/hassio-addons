#!/usr/bin/env bash
# Thin HA entrypoint: point at the Hytale plugin and start the generic supervisor.
set -euo pipefail

VERSION="${APP_VERSION:-}"
if [[ -z "${VERSION}" || "${VERSION}" == "dev" ]]; then
  if [[ -f /etc/hassio_app_version ]]; then
    VERSION="$(tr -d '[:space:]' </etc/hassio_app_version)"
  fi
fi
VERSION="${VERSION:-unknown}"

echo "============================================================"
echo " Hytale Dedicated Server"
echo " Home Assistant app version: ${VERSION}"
echo "============================================================"

export APP_VERSION="${VERSION}"
export OPTIONS_FILE="${OPTIONS_FILE:-/data/options.json}"
export GAME_PLUGIN="${GAME_PLUGIN:-/opt/games/game.yaml}"
export PYTHONPATH="${PYTHONPATH:-/opt}"
export INSTALL_DIR="${INSTALL_DIR:-/data/game}"
export DATA_DIR="${DATA_DIR:-/data/world}"
export STATE_DIR="${STATE_DIR:-/data/supervisor}"
export STATUS_HTTP_PORT="${STATUS_HTTP_PORT:-8099}"
# HA Network can remap the *host* port, but the container side of that mapping
# is fixed at 25565 in config.yaml. Hytale must listen on that same container
# port or joins fail. 25565 is the client Direct Connect default (omit-port);
# the dedicated-server binary defaults to 5520 only when --bind is omitted.
# (We do not use host_network.)
export SERVER_PORT=25565
export PATH="/opt/java/bin:${PATH}"

mkdir -p /data/world /data/logs /data/backups /data/supervisor /data/game
export HOME="${STATE_DIR}"

if [ -f "${OPTIONS_FILE}" ]; then
  echo "Using Home Assistant options from ${OPTIONS_FILE}"
else
  echo "No options.json at ${OPTIONS_FILE}; using environment defaults"
fi

RESOLVED_SERVER_NAME="$(python3 /opt/haos_defaults.py print-name)"
export SERVER_NAME="${RESOLVED_SERVER_NAME}"
echo "Server name: ${SERVER_NAME}"

exec python3 -m game_server --plugin "${GAME_PLUGIN}"
