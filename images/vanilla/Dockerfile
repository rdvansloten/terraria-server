ARG TERRARIA_SERVER_VERSION="1458"
ARG TERRARIA_SERVER_PATH="/terraria-server"
ARG CONFIG_PATH="/terraria/config"
ARG CONFIG_FILENAME="serverconfig.txt"
ARG LOG_PATH="/terraria/logs"
ARG ADDITIONAL_ARGS

FROM debian:trixie-slim AS base

ARG TERRARIA_SERVER_VERSION
ARG TERRARIA_SERVER_FILENAME="terraria-server-${TERRARIA_SERVER_VERSION}.zip"
ARG TERRARIA_SERVER_URL="https://terraria.org/api/download/pc-dedicated-server/${TERRARIA_SERVER_FILENAME}"
ARG TERRARIA_SERVER_PATH
ARG CONFIG_PATH
ARG CONFIG_FILENAME
ARG LOG_PATH

# Required to unzip terraria-server binaries
RUN apt-get update && DEBIAN_FRONTEND="noninteractive" apt-get install -y unzip

# Add server files from internet source
ADD "$TERRARIA_SERVER_URL" "/${TERRARIA_SERVER_FILENAME}"

RUN mkdir -p "$CONFIG_PATH" "$LOG_PATH" "$TERRARIA_SERVER_PATH"

RUN unzip "/$TERRARIA_SERVER_FILENAME" -d "/tmp/terraria/" \
    && mv "/tmp/terraria/${TERRARIA_SERVER_VERSION}/Linux/"* "$TERRARIA_SERVER_PATH"

# Copy serverconfig from repository config folder
COPY config/${CONFIG_FILENAME} ${CONFIG_PATH}/${CONFIG_FILENAME}

FROM debian:trixie-slim

# Inherited arguments
ARG TARGETARCH
ARG TERRARIA_SERVER_VERSION
ARG TERRARIA_SERVER_PATH
ARG CONFIG_PATH
ARG CONFIG_FILENAME
ARG LOG_PATH
ARG ADDITIONAL_ARGS

LABEL org.opencontainers.image.version="$TERRARIA_SERVER_VERSION"
LABEL org.opencontainers.image.authors="R.D. van Sloten <rdvansloten@outlook.com>"
LABEL org.opencontainers.image.documentation="Container image for Terraria Server."
LABEL org.opencontainers.image.url="https://hub.docker.com/r/rdvansloten/terraria-server"
LABEL org.opencontainers.image.source="https://github.com/rdvansloten/terraria-server/blob/main/images/vanilla/Dockerfile"


# Environment variables
ENV TERRARIA_SERVER_PATH="$TERRARIA_SERVER_PATH"
ENV CONFIG_PATH="$CONFIG_PATH"
ENV CONFIG_FILENAME="$CONFIG_FILENAME"
ENV LOG_PATH="$LOG_PATH"
ENV DEFAULT_TERRARIA_SERVER_PATH=".local/share/Terraria"
ENV WORLD_FILENAME="Terraria.wld"
ENV TARGETARCH="${TARGETARCH}"
ENV ENTRYPOINT="entrypoint.sh"
ENV ADDITIONAL_ARGS="$ADDITIONAL_ARGS"

# Add terraria user and group to prevent needing to run the server as root (dangerous)
RUN groupadd -r terraria \
    && useradd -u 999 -r -g terraria -d "/terraria" -s /bin/sh terraria \
    && mkdir -p "$TERRARIA_SERVER_PATH" "/terraria/${DEFAULT_TERRARIA_SERVER_PATH}/Worlds" "$CONFIG_PATH" "$LOG_PATH"

# Copy files from previous stage and repository. The default serverconfig.txt is also kept
# next to the server binaries so the entrypoint can seed it into CONFIG_PATH when a volume
# mounted there is empty.
COPY --from=base --chown=terraria:terraria --chmod=0550 "${TERRARIA_SERVER_PATH}/" "${TERRARIA_SERVER_PATH}/"
COPY --from=base --chown=terraria:terraria --chmod=0550 "${CONFIG_PATH}/" "${CONFIG_PATH}/"
COPY --from=base --chown=terraria:terraria --chmod=0440 "${CONFIG_PATH}/${CONFIG_FILENAME}" "${TERRARIA_SERVER_PATH}/${CONFIG_FILENAME}.default"
COPY --chown=terraria:terraria --chmod=0550 "$ENTRYPOINT" "${TERRARIA_SERVER_PATH}/${ENTRYPOINT}"

# Make terraria user owner over relevant paths
RUN chown -R terraria:terraria "/terraria" "$TERRARIA_SERVER_PATH" \
    && chmod -R 770 "$LOG_PATH" "/terraria/${DEFAULT_TERRARIA_SERVER_PATH}" \
    && chmod -R 770 "$CONFIG_PATH"

# Only install mono libraries output by `monodis --assemblyref TerrariaServer.exe`
# Reduces size by 40% compared to installing package 'mono-runtime'
RUN if [ "${TARGETARCH}" = "arm64" ] || [ "${TARGETARCH}" = "arm" ]; then \
        apt-get update && DEBIAN_FRONTEND="noninteractive" apt-get install -y --no-install-recommends \
        ca-certificates \
        mono-runtime-common \
        libmono-corlib4.5-cil \
        libmono-system4.0-cil \
        libmono-system-core4.0-cil \
        libmono-system-drawing4.0-cil \
        libmono-system-windows-forms4.0-cil \
        libmono-system-runtime-serialization4.0-cil \
        libmono-windowsbase4.0-cil \
        && rm -rf "/var/lib/apt/lists/"* \
        && mv /terraria-server/System.dll /usr/lib/mono/4.5/System.dll; \
    fi

# Set working directory to server
WORKDIR "/terraria-server"

# Switch to terraria user
USER terraria

# Document default Terraria server port
EXPOSE 7777

ENTRYPOINT [ "/bin/sh", "entrypoint.sh" ]
