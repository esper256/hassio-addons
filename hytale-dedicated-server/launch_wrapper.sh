#!/usr/bin/env bash
# Hytale launch wrapper (game layer, not game-server-base).
# Merges config.json, starts Java 25 with official --assets / --bind, and
# injects `/auth login device` on first boot so Ingress can show the code.
set -euo pipefail
export PATH="/opt/java/bin:${PATH}"
exec python3 /opt/haos_defaults.py run "$@"
