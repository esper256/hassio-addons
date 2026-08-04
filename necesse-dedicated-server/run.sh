#!/usr/bin/env bash
# Thin HA entrypoint: point at the Necesse plugin and start the generic supervisor.
set -euo pipefail

VERSION="${APP_VERSION:-}"
if [[ -z "${VERSION}" || "${VERSION}" == "dev" ]]; then
  if [[ -f /etc/hassio_app_version ]]; then
    VERSION="$(tr -d '[:space:]' </etc/hassio_app_version)"
  fi
fi
VERSION="${VERSION:-unknown}"

echo "============================================================"
echo " Necesse Dedicated Server"
echo " Home Assistant app version: ${VERSION}"
echo "============================================================"

export APP_VERSION="${VERSION}"
export OPTIONS_FILE="${OPTIONS_FILE:-/data/options.json}"
export GAME_PLUGIN="${GAME_PLUGIN:-/opt/games/game.yaml}"
export PYTHONPATH="${PYTHONPATH:-/opt}"
export INSTALL_DIR="${INSTALL_DIR:-/data/game}"
# HA Ingress default port; override for plain Docker if needed.
export STATUS_HTTP_PORT="${STATUS_HTTP_PORT:-8099}"
# Necesse always listens on 14159 inside the container so it matches the
# published UDP mapping (Network tab remaps the *host* port only).
export SERVER_PORT=14159

mkdir -p /data/world /data/logs /data/backups /data/supervisor /data/game /data/steam-home
# SteamCMD reads HOME for its log directory; keep it on the persistent volume.
export HOME="${STEAM_HOME:-/data/steam-home}"
export STEAM_HOME="${STEAM_HOME:-/data/steam-home}"

if [ -f "${OPTIONS_FILE}" ]; then
  echo "Using Home Assistant options from ${OPTIONS_FILE}"
else
  echo "No options.json at ${OPTIONS_FILE}; using environment defaults"
fi

exec python3 -m game_server --plugin "${GAME_PLUGIN}"
