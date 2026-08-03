# Generic SteamCMD game-server supervisor base.
# Build from repo root:
#   docker build -f game-server-base/Dockerfile -t game-server-base .
#
# Run Necesse example:
#   docker run --rm -p 14159:14159/udp -p 8080:8080 \
#     -v $PWD/data:/data \
#     -e WORLD_NAME=MyWorld \
#     -e UPDATE_ON_START=true \
#     -e AUTO_UPDATE_INTERVAL_MINUTES=30 \
#     game-server-base

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    GAME_PLUGIN=/opt/games/necesse.yaml \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt

RUN dpkg --add-architecture i386 \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      ca-certificates-java \
      curl \
      lib32gcc-s1 \
      openjdk-17-jre-headless \
      python3 \
      python3-yaml \
      procps \
      xz-utils \
 && rm -rf /var/lib/apt/lists/*

# SteamCMD
RUN mkdir -p /opt/steamcmd \
 && curl -fsSL https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz \
    | tar -xz -C /opt/steamcmd \
 && /opt/steamcmd/steamcmd.sh +quit || true

# Non-root user for the game process / files
RUN useradd -m -u 1000 -s /bin/bash gameserver \
 && mkdir -p /data/game /data/world /data/logs /data/backups /data/supervisor /opt/games \
 && chown -R gameserver:gameserver /opt/steamcmd /data /home/gameserver

COPY game-server-base/game_server /opt/game_server
COPY game-server-base/games /opt/games

WORKDIR /data/game
EXPOSE 14159/udp 8080

# Supervisor starts as root to fix volume ownership, then runs the game as gameserver.
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1

ENTRYPOINT ["python3", "-m", "game_server"]
