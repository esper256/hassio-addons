#!/bin/bash
#!/usr/bin/env bash

# Load options as env vars (HA mounts /data/options.json)
if [ -f /data/options.json ]; then
  eval $(jq -r '@sh "export \(. | to_entries[] | "\(.key | ascii_upcase)=\(.value // empty)")"' /data/options.json)
fi

# Uppercase keys for env (e.g., world_name -> WORLD_NAME)
export WORLD_NAME="${WORLD_NAME:-MyWorld}"
export SERVER_PASSWORD="${SERVER_PASSWORD:-}"
export SERVER_SLOTS="${SERVER_SLOTS:-10}"
export PAUSE_WHEN_EMPTY="${PAUSE_WHEN_EMPTY:-1}"
export UPDATE_ON_START="${UPDATE_ON_START:-true}"
export AUTO_UPDATE_INTERVAL_MINUTES="${AUTO_UPDATE_INTERVAL_MINUTES:-60}"

# Run original entrypoint
exec /original_entrypoint_or_java_command "$@"