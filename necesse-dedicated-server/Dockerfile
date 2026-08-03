# Home Assistant add-on: Necesse dedicated server
# Uses the shared game-server-base supervisor (vendored into this directory).

FROM debian:bookworm-slim

ARG BUILD_VERSION=dev
ARG BUILD_ARCH=amd64

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    GAME_PLUGIN=/opt/games/necesse.yaml \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt \
    INSTALL_DIR=/data/game

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

RUN mkdir -p /opt/steamcmd \
 && curl -fsSL https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz \
    | tar -xz -C /opt/steamcmd \
 && /opt/steamcmd/steamcmd.sh +quit || true

RUN useradd -m -u 1000 -s /bin/bash gameserver \
 && mkdir -p /data/game /data/world /data/logs /data/backups /data/supervisor /opt/games \
 && chown -R gameserver:gameserver /opt/steamcmd /data /home/gameserver

COPY game_server /opt/game_server
COPY games /opt/games
COPY run.sh /run.sh
RUN chmod +x /run.sh

WORKDIR /data/game

LABEL \
  io.hass.name="Necesse Dedicated Server" \
  io.hass.description="Necesse dedicated server with SteamCMD auto-updates, smart restarts, backups, and status page" \
  io.hass.type="addon" \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.source="https://github.com/esper256/hassio-addons"

ENTRYPOINT ["/run.sh"]
