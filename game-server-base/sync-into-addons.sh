#!/usr/bin/env bash
# Maintainer sync: vendor game-server-base/game_server into each game add-on.
#
# Why: HA / Docker builds for a game add-on only see that add-on's tree. They do
# not mount ../game-server-base at build or runtime. Each installable add-on
# therefore keeps a copy of the generic supervisor under <addon>/game_server/.
# After you edit game-server-base/, run this so those copies match before you
# bump the add-on version and rebuild.
#
# Not a Docker/build step. Run by hand (or from CI) on the repo checkout. The
# Dockerfile only COPY's the already-vendored <addon>/game_server/ tree.
# CI enforces sync via check-addon-sync.sh.
#
# Targets: sibling directories that look like installable game add-ons
# (config.yaml + games/). Never overwrites games/*.yaml or other add-on files.
set -euo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$BASE/.." && pwd)"
SRC="$BASE/game_server"

sync_into() {
  local dst_root="$1"
  local dst="$dst_root/game_server"
  rm -rf "$dst"
  mkdir -p "$dst"
  # Do not vendor bytecode; running unit tests would otherwise dirty the tree
  # and make check-addon-sync.sh fail.
  tar -C "$SRC" --exclude='__pycache__' --exclude='*.pyc' -cf - . \
    | tar -C "$dst" -xf -
  echo "Synced game_server -> ${dst_root}/"
}

found=0
for dest in "$ROOT"/*/; do
  # Skip the source package itself.
  if [[ "$(cd "$dest" && pwd)" == "$BASE" ]]; then
    continue
  fi
  if [[ -f "${dest}config.yaml" && -d "${dest}games" ]]; then
    sync_into "$(cd "$dest" && pwd)"
    found=$((found + 1))
  fi
done

if [[ "$found" -eq 0 ]]; then
  echo "No game add-ons found under ${ROOT} (expected */config.yaml + */games/)" >&2
  exit 1
fi
