ARG TSHOCK_VERSION="v6.1.0"
ARG TSHOCK_SERVER_PATH="/tshock-server"
ARG CONFIG_PATH="/terraria/config"
ARG LOG_PATH="/terraria/logs"
ARG PLUGIN_PATH="/terraria/plugins"

FROM alpine:3.22@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce AS base

# Set values as args so the second stage may inherit
ARG TARGETARCH
ARG TSHOCK_VERSION
ARG TSHOCK_SERVER_PATH

# Required to download and unpack the TShock release
RUN apk add --no-cache curl unzip

# Download and unpack TShock for the target architecture.
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

FROM mcr.microsoft.com/dotnet/runtime:9.0@sha256:647b8b6d4f4570270c763a200514241ca54f8d70dc314000412fbd8ec594724b

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
# the entrypoint places on tmpfs.
ENV DOTNET_BUNDLE_EXTRACT_BASE_DIR="${TSHOCK_SERVER_PATH}/.net"
ENV DOTNET_EnableDiagnostics="0"

RUN apt-get update && DEBIAN_FRONTEND="noninteractive" apt-get install -y --no-install-recommends \
        jq \
        mariadb-client \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r terraria \
    && useradd -u 999 -r -g terraria -d "/terraria" -s /bin/sh terraria \
    && mkdir -p "$TSHOCK_SERVER_PATH" "/terraria/${DEFAULT_TERRARIA_SERVER_PATH}/Worlds" "$CONFIG_PATH" "$LOG_PATH" "$PLUGIN_PATH"

# Copy files from previous stage and repository
COPY --from=base --chown=terraria:terraria --chmod=0550 "${TSHOCK_SERVER_PATH}/" "${TSHOCK_SERVER_PATH}/"
COPY --chown=terraria:terraria --chmod=0550 "$ENTRYPOINT" "${TSHOCK_SERVER_PATH}/${ENTRYPOINT}"
COPY --chown=terraria:terraria --chmod=0440 config/serverconfig.txt "${TSHOCK_SERVER_PATH}/serverconfig.txt.default"

# Make terraria user owner over relevant paths.
RUN mv "${TSHOCK_SERVER_PATH}/GeoIP.dat" "${TSHOCK_SERVER_PATH}/GeoIP.dat.orig" \
    && ln -s /tmp/GeoIP.dat "${TSHOCK_SERVER_PATH}/GeoIP.dat" \
    && ln -s "${LOG_PATH}/ServerLog.txt" "${TSHOCK_SERVER_PATH}/ServerLog.txt" \
    && chown -R terraria:terraria "/terraria" "$TSHOCK_SERVER_PATH" \
    && chmod -R 770 "$LOG_PATH" "$CONFIG_PATH" "$PLUGIN_PATH" "/terraria/${DEFAULT_TERRARIA_SERVER_PATH}"

RUN cd "$TSHOCK_SERVER_PATH" \
    && (timeout 120 ./TShock.Server -world /nonexistent/none.wld -configpath /tmp/extract -logpath /tmp/extract >/dev/null 2>&1 || true) \
    && test -n "$(ls -A "${TSHOCK_SERVER_PATH}/.net/TShock.Server" 2>/dev/null)" \
    && chown -R terraria:terraria "${TSHOCK_SERVER_PATH}/.net" \
    && chmod -R u=rX,g=rX,o= "${TSHOCK_SERVER_PATH}/.net" \
    && rm -rf /tmp/extract /tmp/GeoIP.dat "${LOG_PATH:?}"/* "${CONFIG_PATH:?}"/* /terraria/.local/share/Terraria/* \
    && mkdir -p "/terraria/${DEFAULT_TERRARIA_SERVER_PATH}/Worlds" \
    && chown -R terraria:terraria "/terraria/${DEFAULT_TERRARIA_SERVER_PATH}" \
    && chmod -R 770 "/terraria/${DEFAULT_TERRARIA_SERVER_PATH}" \
    && test -z "$(find /terraria -not -user terraria)"

# Set working directory to server
WORKDIR "/tshock-server"

# Switch to terraria user
USER terraria

EXPOSE 7777 7878

ENTRYPOINT [ "/bin/sh", "entrypoint.sh" ]
