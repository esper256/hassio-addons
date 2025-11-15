#!/usr/bin/env bash

set -e  # Exit on error

# Parse HA options.json to env vars using jq
if [ -f /data/options.json ]; then
  # Load and export: Uppercase keys, bools as "true"/"false", numbers/strings as-is
  eval "$(jq -r 'to_entries[] | "export \(.key | ascii_upcase)=\"\(.value | if type == "boolean" then (if . then "true" else "false" end) elif type == "number" then (. | tostring) else tostring end)\"" ' /data/options.json)"
fi

# Pure Bash JSON parser for simple flat options.json (no nesting, handles strings/bools/ints)
# Assumes JSON like: {"key1":"value1","key2":true,"key3":42,"key4":null}
parse_options() {
  local json_file="$1"
  local json_content key value upper_key

  # Read and normalize: remove newlines/tabs, trim whitespace
  json_content=$(tr -d '\n\r\t' < "$json_file" 2>/dev/null || cat "$json_file")
  # Pure Bash trim leading/trailing whitespace
  json_content="${json_content#"${json_content%%[![:space:]]*}"}"
  json_content="${json_content%"${json_content##*[![:space:]]}"}"
  # Remove outer { and } if present
  if [[ ${json_content:0:1} == '{' ]]; then
    json_content="${json_content:1}"
  fi
  if [[ ${json_content: -1} == '}' ]]; then
    json_content="${json_content::-1}"
  fi
  # Trim again in case of spaces around
  json_content="${json_content#"${json_content%%[![:space:]]*}"}"
  json_content="${json_content%"${json_content##*[![:space:]]}"}"

  # Loop to extract key-value pairs
  while [[ -n "$json_content" ]]; do
    # Extract first key-value pair (up to next unquoted comma)
    if [[ $json_content =~ ^[[:space:]]*"([^"]+)"[[:space:]]*\:[[:space:]]*(\"[^\"]*\"|true|false|[0-9]+|null)[[:space:]]*,?(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"
      value="${BASH_REMATCH[2]}"
      local rest="${BASH_REMATCH[3]}"

      # Clean value: Remove outer quotes if string
      if [[ $value =~ ^\" && $value =~ \"$ ]]; then
        value="${value#\"}"
        value="${value%\"}"
        # Basic unescape (e.g., \" -> ")
        value="${value//\\\\\"/\"}"
      fi

      # Handle null
      if [[ $value == "null" ]]; then
        value=""
      fi
      # true/false/numbers/strings are already good as strings

      # Uppercase key and export (e.g., world_name -> WORLD_NAME="$value")
      upper_key="${key^^}"
      export "${upper_key}=\"${value}\""

      # Advance to next pair (trim leading spaces from rest)
      json_content="${rest#${rest%%[![:space:]]*}}"
      json_content="${json_content%"${json_content##*[![:space:]]}"}"
    else
      # No more pairs or malformed—exit loop
      break
    fi
  done
}

# Usage: Parse if file exists
if [ -f /data/options.json ]; then
  #parse_options /data/options.json
  #echo "Parsed options.json with pure Bash (keys exported as env vars)"
else
  echo "No /data/options.json found—using defaults"
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
sleep 30
echo "End of HA entrypoint script."