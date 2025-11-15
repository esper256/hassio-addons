#!/usr/bin/env bash

set -e  # Exit on error

# Parse HA options.json to env vars using jq
if [ -f /data/options.json ]; then
  # Load and export: Uppercase keys, bools as "true"/"false", numbers/strings as-is
  eval "$(jq -r 'to_entries[] | "export \(.key | ascii_upcase)=\"\(.value | if type == "boolean" then (if . then "true" else "false" end) elif type == "number" then (. | tostring) else tostring end)\"" ' /data/options.json)"
fi

# Defaults (override if not in options; match script's expectations)
export WORLD_NAME="${WORLD_NAME:-MyWorld}"
export SERVER_PASSWORD="${SERVER_PASSWORD:-}"
export SERVER_SLOTS="${SERVER_SLOTS:-10}"
export PAUSE_WHEN_EMPTY="${PAUSE_WHEN_EMPTY:-true}"
export UPDATE_ON_START="${UPDATE_ON_START:-true}"
export AUTO_UPDATE_INTERVAL_MINUTES="${AUTO_UPDATE_INTERVAL_MINUTES:-60}"
export SERVER_LANGUAGE="${SERVER_LANGUAGE:-en}"
export ENABLE_LOGGING="${ENABLE_LOGGING:-true}"
export ZIP_SAVES="${ZIP_SAVES:-true}"
export SERVER_MOTD="${SERVER_MOTD:-Welcome to my Necesse server!}"
export DATA_DIR="${DATA_DIR:-/home/necesse/.config/Necesse}"
export LOGS_DIR="${LOGS_DIR:-/home/necesse/.config/Necesse/logs}"

# Debug: Log key exports (remove in production)
echo "Loaded envs: WORLD_NAME=$WORLD_NAME, SERVER_SLOTS=$SERVER_SLOTS, PAUSE_WHEN_EMPTY=$PAUSE_WHEN_EMPTY, UPDATE_ON_START=$UPDATE_ON_START"

# Chain to original entrypoint—handles everything else (updates, launch, restarts)
exec /app/entrypoint.sh "$@"

# Sleep on errors giving time for console debugging
sleep 600
echo "End of HA entrypoint script."