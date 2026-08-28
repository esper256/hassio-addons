#!/usr/bin/env bash
# Hytale launch wrapper (game layer, not game-server-base).
# Merges config.json, persists machine-id, starts Java 25 with official
# --assets / --bind, and only injects `/auth login device` when Java says
# tokens are missing. After login, switches persistence to Encrypted.
set -euo pipefail
export PATH="/opt/java/bin:${PATH}"
exec python3 /opt/haos_defaults.py run "$@"
