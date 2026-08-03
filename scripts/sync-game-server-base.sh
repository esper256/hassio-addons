#!/usr/bin/env bash
# Copy the canonical game-server-base package into the HA add-on build context.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/game-server-base"
DST="$ROOT/necesse-dedicated-server"

rm -rf "$DST/game_server" "$DST/games"
mkdir -p "$DST/games"
cp -a "$SRC/game_server" "$DST/game_server"
cp -a "$SRC/games/." "$DST/games/"
echo "Synced game-server-base -> necesse-dedicated-server/"
