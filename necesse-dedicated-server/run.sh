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

# Resolve the UDP port Necesse should listen on.
# On Home Assistant we use host networking, so this is the same number players
# type in the client (the Network tab value for 14159/udp). Plain Docker can
# set SERVER_PORT in the environment; default remains 14159.
DEFAULT_GAME_PORT=14159
if [[ -z "${SERVER_PORT:-}" && -n "${SUPERVISOR_TOKEN:-}" ]]; then
  RESOLVED_PORT="$(
    python3 - <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

token = os.environ.get("SUPERVISOR_TOKEN", "")
if not token:
    sys.exit(0)
try:
    req = urllib.request.Request(
        "http://supervisor/addons/self/info",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
        payload = json.load(resp)
except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
    print(f"warning: could not read Network UDP port from Supervisor: {exc}", file=sys.stderr)
    sys.exit(0)

data = payload.get("data", payload)
network = data.get("network") or {}
for key in ("14159/udp", "14159/UDP"):
    value = network.get(key)
    if value in (None, "", "null"):
        continue
    try:
        port = int(value)
    except (TypeError, ValueError):
        continue
    if 1 <= port <= 65535:
        print(port)
        break
PY
  )" || RESOLVED_PORT=""
  if [[ -n "${RESOLVED_PORT}" ]]; then
    SERVER_PORT="${RESOLVED_PORT}"
  fi
fi
export SERVER_PORT="${SERVER_PORT:-$DEFAULT_GAME_PORT}"
echo "Necesse game UDP port: ${SERVER_PORT}"

# With host_network, do not bind the passwordless status UI on all interfaces.
# Supervisor / Ingress reach host-network apps via the hassio gateway.
if [[ -n "${SUPERVISOR_TOKEN:-}" ]]; then
  export STATUS_HTTP_HOST="${STATUS_HTTP_HOST:-172.30.32.1}"
fi

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
