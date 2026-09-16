ARG TSHOCK_VERSION="v6.1.0"
ARG TSHOCK_SERVER_PATH="/tshock-server"
ARG CONFIG_PATH="/terraria/config"
ARG LOG_PATH="/terraria/logs"
ARG PLUGIN_PATH="/terraria/plugins"
ARG DOTNET_RUNTIME_VERSION="9.0"

FROM alpine:3.22 AS base

# Set values as args so the second stage may inherit
ARG TARGETARCH
ARG TSHOCK_VERSION
ARG TSHOCK_SERVER_PATH

# Required to download and unpack the TShock release
RUN apk add --no-cache curl unzip

# Download and unpack TShock for the target architecture.
# Release assets are named e.g. TShock-6.1.0-for-Terraria-1.4.5.6-linux-x64-Release.zip
# and contain a single tar with the server files.
RUN set -eux; \
    case "${TARGETARCH}" in \
      amd64) arch_suffix="x64" ;; \
      arm64) arch_suffix="arm64" ;; \
      arm)   arch_suffix="arm" ;; \
      *) echo >&2 "error: unsupported architecture '${TARGETARCH}'"; exit 1 ;; \
    esac; \
    if [ "${TSHOCK_VERSION}" = "latest" ]; then \
      release_url="https://api.github.com/repos/Pryaxis/TShock/releases/latest"; \
    else \
      release_url="https://api.github.com/repos/Pryaxis/TShock/releases/tags/${TSHOCK_VERSION}"; \
    fi; \
    zip_url=$(curl -fsSL "${release_url}" | grep browser_download_url | grep "linux-${arch_suffix}-Release.zip" | cut -d '"' -f 4); \
    [ -n "${zip_url}" ] || { echo >&2 "error: no linux-${arch_suffix} asset found for ${TSHOCK_VERSION}"; exit 1; }; \
    echo "Downloading ${zip_url}"; \
    curl -fsSL -o /tshock.zip "${zip_url}"; \
    mkdir -p /tmp/tshock "${TSHOCK_SERVER_PATH}"; \
    unzip -q /tshock.zip -d /tmp/tshock; \
    tar -xf /tmp/tshock/*.tar -C "${TSHOCK_SERVER_PATH}"; \
    chmod +x "${TSHOCK_SERVER_PATH}/TShock.Server"; \
    rm -rf /tshock.zip /tmp/tshock

FROM mcr.microsoft.com/dotnet/runtime:${DOTNET_RUNTIME_VERSION}

# Inherited arguments
ARG TARGETARCH
ARG TSHOCK_VERSION
ARG TSHOCK_SERVER_PATH
ARG CONFIG_PATH
ARG LOG_PATH
ARG PLUGIN_PATH

# Container labels
LABEL org.opencontainers.image.authors="Rudy van Sloten"
LABEL org.opencontainers.image.url="https://hub.docker.com/r/rdvansloten/terraria-server"
LABEL org.opencontainers.image.documentation="Container image for TShock Terraria Server."
LABEL org.opencontainers.image.source="https://github.com/rdvansloten/terraria-server/blob/main/images/tshock/Dockerfile"
LABEL org.opencontainers.image.version="$TSHOCK_VERSION"

# Environment variables
ENV TSHOCK_SERVER_PATH="$TSHOCK_SERVER_PATH"
ENV TSHOCK_VERSION="$TSHOCK_VERSION"
ENV CONFIG_PATH="$CONFIG_PATH"
ENV LOG_PATH="$LOG_PATH"
ENV PLUGIN_PATH="$PLUGIN_PATH"
ENV DEFAULT_TERRARIA_SERVER_PATH=".local/share/Terraria"
ENV WORLD_FILENAME="Terraria.wld"
ENV TARGETARCH="${TARGETARCH}"
ENV ENTRYPOINT="entrypoint.sh"
# .NET single-file bundles extract native libraries here; keep it inside the writable home
ENV DOTNET_BUNDLE_EXTRACT_BASE_DIR="/terraria/.net"

# jq: read StorageType/MySql settings from TShock config.json
# mariadb-client: wait for the database before starting when using MySQL storage
RUN apt-get update && DEBIAN_FRONTEND="noninteractive" apt-get install -y --no-install-recommends \
        jq \
        mariadb-client \
    && rm -rf /var/lib/apt/lists/*

# Add terraria user and group to prevent needing to run the server as root (dangerous)
RUN groupadd -r terraria \
    && useradd -u 999 -r -g terraria -d "/terraria" -s /bin/sh terraria \
    && mkdir -p "$TSHOCK_SERVER_PATH" "/terraria/${DEFAULT_TERRARIA_SERVER_PATH}/Worlds" "$CONFIG_PATH" "$LOG_PATH" "$PLUGIN_PATH"

# Copy files from previous stage and repository
# TShock opens some of its own files (e.g. GeoIP.dat) read-write, so the server tree must be owner-writable
COPY --from=base --chown=terraria:terraria --chmod=0750 "${TSHOCK_SERVER_PATH}/" "${TSHOCK_SERVER_PATH}/"
COPY --chown=terraria:terraria --chmod=0550 "$ENTRYPOINT" "${TSHOCK_SERVER_PATH}/${ENTRYPOINT}"

# Make terraria user owner over relevant paths.
# TShock writes config.json, sscconfig.json and tshock.sqlite into CONFIG_PATH, so it must be writable.
RUN chown -R terraria:terraria "/terraria" "$TSHOCK_SERVER_PATH" \
    && chmod -R 770 "$LOG_PATH" "$CONFIG_PATH" "$PLUGIN_PATH" "/terraria/${DEFAULT_TERRARIA_SERVER_PATH}"

# Set working directory to server
WORKDIR "/tshock-server"

# Switch to terraria user
USER terraria

# Document default Terraria server port and TShock REST API port
EXPOSE 7777 7878

ENTRYPOINT [ "/bin/sh", "entrypoint.sh" ]
