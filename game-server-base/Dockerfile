# Generic SteamCMD dedicated-server supervisor.
# Contains no game-specific plugins, ports, or runtimes (no Java/Mono/etc).
#
# Build from repo root:
#   docker build -f game-server-base/Dockerfile -t game-server-base .
#
# Run with a game plugin mounted in:
#   docker run --rm \
#     -e GAME_PLUGIN=/opt/games/game.yaml \
#     -v $PWD/my-game/game.yaml:/opt/games/game.yaml:ro \
#     -v $PWD/data:/data \
#     -p 8080:8080 \
#     game-server-base
#
# Game-specific images should FROM this layer (or copy game_server/) and add
# their runtime packages + plugin YAML.

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt

RUN dpkg --add-architecture i386 \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      lib32gcc-s1 \
      python3 \
      python3-yaml \
      procps \
      xz-utils \
 && rm -rf /var/lib/apt/lists/*

# SteamCMD bootstrap only (self-updates on use).
RUN mkdir -p /opt/steamcmd \
 && curl -fsSL https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz \
    | tar -xz -C /opt/steamcmd \
 && /opt/steamcmd/steamcmd.sh +quit || true

RUN useradd -m -u 1000 -s /bin/bash gameserver \
 && mkdir -p /data/game /data/world /data/logs /data/backups /data/supervisor /opt/games \
 && chown -R gameserver:gameserver /opt/steamcmd /data /home/gameserver \
 && rm -f /etc/machine-id /var/lib/dbus/machine-id

COPY game-server-base/game_server /opt/game_server

WORKDIR /data/game
EXPOSE 8080

VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1

# GAME_PLUGIN must point at a mounted/copied plugin YAML/JSON.
ENTRYPOINT ["python3", "-m", "game_server"]
