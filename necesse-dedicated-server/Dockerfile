FROM andreasgl4ser/necesse-server:latest

# Install jq for JSON parsing (minimal addition)
RUN apt-get update && \
    apt-get install -y jq && \
    rm -rf /var/lib/apt/lists/*

COPY haentrypoint.sh /haentrypoint.sh
RUN chmod +x /haentrypoint.sh
ENTRYPOINT ["/haentrypoint.sh"]