#!/bin/bash
#!/usr/bin/env bash

# Parse HA options.json to env vars (Python fallback for jq)
if command -v python3 &> /dev/null && [ -f /data/options.json ]; then
  python3 -c "
import json
with open('/data/options.json', 'r') as f:
    opts = json.load(f)
for k, v in opts.items():
    upper_k = k.upper()
    if isinstance(v, bool):
        val = '1' if v else '0'
    elif isinstance(v, (int, float)):
        val = str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)
    else:
        val = str(v).replace('\"', '\\\\\"')  # Escape quotes if needed
    print(f'export {upper_k}=\"{val}\"')
" | source /dev/stdin  # Source the exports into this shell
fi

# Load options as env vars (HA mounts /data/options.json)
#if [ -f /data/options.json ]; then
#  eval $(jq -r '@sh "export \(. | to_entries[] | "\(.key | ascii_upcase)=\(.value // empty)")"' /data/options.json)
#fi

# Uppercase keys for env (e.g., world_name -> WORLD_NAME)
export WORLD_NAME="${WORLD_NAME:-MyWorld}"
export SERVER_PASSWORD="${SERVER_PASSWORD:-}"
export SERVER_SLOTS="${SERVER_SLOTS:-10}"
export PAUSE_WHEN_EMPTY="${PAUSE_WHEN_EMPTY:-1}"
export UPDATE_ON_START="${UPDATE_ON_START:-true}"
export AUTO_UPDATE_INTERVAL_MINUTES="${AUTO_UPDATE_INTERVAL_MINUTES:-60}"

echo "Pausing for debugging... Container will sleep for 5 minutes. Use Portainer to inspect now."
sleep 600  # Adjust as needed (e.g., 600 for 10 min)

# Run original entrypoint
exec /entrypoint.sh "$@"