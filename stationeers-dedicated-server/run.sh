#!/usr/bin/env bash
# Thin HA entrypoint: point at the Stationeers plugin and start the generic supervisor.
set -euo pipefail

VERSION="${APP_VERSION:-}"
if [[ -z "${VERSION}" || "${VERSION}" == "dev" ]]; then
  if [[ -f /etc/hassio_app_version ]]; then
    VERSION="$(tr -d '[:space:]' </etc/hassio_app_version)"
  fi
fi
VERSION="${VERSION:-unknown}"

echo "============================================================"
echo " Stationeers Dedicated Server"
echo " Home Assistant app version: ${VERSION}"
echo "============================================================"

export APP_VERSION="${VERSION}"
export OPTIONS_FILE="${OPTIONS_FILE:-/data/options.json}"
export GAME_PLUGIN="${GAME_PLUGIN:-/opt/games/game.yaml}"
export PYTHONPATH="${PYTHONPATH:-/opt}"
export INSTALL_DIR="${INSTALL_DIR:-/data/game}"
# HA Ingress default port; override for plain Docker if needed.
export STATUS_HTTP_PORT="${STATUS_HTTP_PORT:-8099}"
# HA Network can remap the *host* ports, but the container side of those
# mappings is fixed in config.yaml. Stationeers must listen on the same
# container ports or joins fail. (We do not use host_network.)
export SERVER_PORT=27016
export UPDATE_PORT=27015

mkdir -p /data/world /data/logs /data/backups /data/supervisor /data/game /data/steam-home
# SteamCMD reads HOME for its log directory; keep it on the persistent volume.
export HOME="${STEAM_HOME:-/data/steam-home}"
export STEAM_HOME="${STEAM_HOME:-/data/steam-home}"

if [ -f "${OPTIONS_FILE}" ]; then
  echo "Using Home Assistant options from ${OPTIONS_FILE}"
else
  echo "No options.json at ${OPTIONS_FILE}; using environment defaults"
fi

# Blank HA server_name → stable "HAOS Stationeers ####" (per-install salt under /data).
RESOLVED_SERVER_NAME="$(python3 /opt/haos_defaults.py)"
export SERVER_NAME="${RESOLVED_SERVER_NAME}"
echo "Server name: ${SERVER_NAME}"

exec python3 -m game_server --plugin "${GAME_PLUGIN}"
