#!/usr/bin/env bash
# Core Keeper launch wrapper (game layer, not game-server-base).
#
# The dedicated server is a Unity binary that needs a virtual display on
# Linux, a 64-bit steamclient.so, and a Game ID printed somewhere operators
# can actually see it. Keep that here so the shared supervisor stays generic.
set -euo pipefail

ckpid=""
xvfbpid=""
watcher_pid=""

cleanup() {
  trap - EXIT TERM INT
  if [[ -n "${watcher_pid}" ]] && kill -0 "${watcher_pid}" 2>/dev/null; then
    kill "${watcher_pid}" 2>/dev/null || true
  fi
  if [[ -n "${ckpid}" ]] && kill -0 "${ckpid}" 2>/dev/null; then
    kill -TERM "${ckpid}" 2>/dev/null || true
    wait "${ckpid}" 2>/dev/null || true
  fi
  if [[ -n "${xvfbpid}" ]] && kill -0 "${xvfbpid}" 2>/dev/null; then
    kill -TERM "${xvfbpid}" 2>/dev/null || true
    wait "${xvfbpid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT TERM INT

steamcmd_linux64="${STEAMCMD_LINUX64:-/opt/steamcmd/linux64}"
export LD_LIBRARY_PATH="${steamcmd_linux64}:${LD_LIBRARY_PATH:-}"

home_dir="${HOME:-/data/steam-home}"
mkdir -p "${home_dir}/.steam/sdk64"
if [[ -f "${steamcmd_linux64}/steamclient.so" ]]; then
  ln -sfn "${steamcmd_linux64}/steamclient.so" \
    "${home_dir}/.steam/sdk64/steamclient.so"
fi

bin=""
for candidate in ./CoreKeeperServer ./CoreKeeperServer.x86_64; do
  if [[ -x "${candidate}" ]]; then
    bin="${candidate}"
    break
  fi
done
if [[ -z "${bin}" ]]; then
  echo "Core Keeper dedicated server binary not found in $(pwd)" >&2
  echo "Looked for ./CoreKeeperServer and ./CoreKeeperServer.x86_64" >&2
  exit 1
fi

mkdir -p /tmp/.X11-unix
display_num=""
for d in $(seq 99 119); do
  if [[ ! -e "/tmp/.X${d}-lock" && ! -S "/tmp/.X11-unix/X${d}" ]]; then
    display_num="${d}"
    break
  fi
done
if [[ -z "${display_num}" ]]; then
  echo "No free Xvfb display in :99–:119" >&2
  exit 1
fi

Xvfb ":${display_num}" -screen 0 640x480x24 -nolisten tcp -nolisten unix &
xvfbpid=$!
export DISPLAY=":${display_num}"

# Wait briefly so Unity does not race a missing display.
for _ in $(seq 1 20); do
  if [[ -S "/tmp/.X11-unix/X${display_num}" || -e "/tmp/.X${display_num}-lock" ]]; then
    break
  fi
  if ! kill -0 "${xvfbpid}" 2>/dev/null; then
    echo "Xvfb failed to start on display :${display_num}" >&2
    exit 1
  fi
  sleep 0.1
done

# Print Game ID to stdout (HA Logs) once the server writes it. Do not delete
# GameID.txt — wiping it can mint a new join code on the next boot.
(
  for _ in $(seq 1 120); do
    if [[ -s GameID.txt ]]; then
      gid="$(tr -d '[:space:]' < GameID.txt || true)"
      if [[ -n "${gid}" ]]; then
        echo "Game ID: ${gid}"
        echo "Players join in Core Keeper → Multiplayer → Join Game with this Game ID (Steam Datagram Relay; no IP:port)."
        exit 0
      fi
    fi
    sleep 1
  done
) &
watcher_pid=$!

echo "Starting ${bin} on DISPLAY=${DISPLAY} (cwd=$(pwd))"
"${bin}" "$@" &
ckpid=$!
set +e
wait "${ckpid}"
rc=$?
set -e
ckpid=""
exit "${rc}"
