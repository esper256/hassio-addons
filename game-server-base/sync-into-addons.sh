#!/usr/bin/env bash
# Copy only the generic supervisor package into game-specific HA add-on contexts.
# Game plugins (games/*.yaml) are owned by each add-on and are never overwritten.
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$BASE/.." && pwd)"
SRC="$BASE/game_server"

sync_into() {
  local dst_root="$1"
  local dst="$dst_root/game_server"
  rm -rf "$dst"
  cp -a "$SRC" "$dst"
  echo "Synced game_server -> $dst_root/"
}

sync_into "$ROOT/necesse-dedicated-server"
