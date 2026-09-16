#!/bin/sh

SERVER_BINARY="./TShock.Server"
WORLD_PATH="/terraria/${DEFAULT_TERRARIA_SERVER_PATH}/Worlds/${WORLD_FILENAME}"
CONFIG_FILE="${CONFIG_PATH}/config.json"

# Print server information
printf "Server binary : %s\n" "$SERVER_BINARY"
printf "TShock version: %s\n" "$TSHOCK_VERSION"
printf "Architecture  : %s\n" "$TARGETARCH"
printf "World file    : %s\n" "$WORLD_PATH"
printf "Log path      : %s\n" "$LOG_PATH"
printf "Config path   : %s\n" "$CONFIG_PATH"
printf "Plugin path   : %s\n" "$PLUGIN_PATH"

# When TShock is configured for MySQL storage, wait for the database before starting
if [ -f "$CONFIG_FILE" ] && [ "$(jq -r '.Settings.StorageType' "$CONFIG_FILE")" = "mysql" ]; then
  DATABASE_HOST=$(jq -r '.Settings.MySqlHost' "$CONFIG_FILE" | cut -f1 -d':')
  DATABASE_PORT=$(jq -r '.Settings.MySqlHost' "$CONFIG_FILE" | cut -f2 -d':')
  DATABASE_USER=$(jq -r '.Settings.MySqlUsername' "$CONFIG_FILE")
  DATABASE_PASSWORD=$(jq -r '.Settings.MySqlPassword' "$CONFIG_FILE")
  printf "Waiting for database server %s:%s\n" "$DATABASE_HOST" "$DATABASE_PORT"
  until mariadb -h "$DATABASE_HOST" -P "$DATABASE_PORT" -u "$DATABASE_USER" -p"$DATABASE_PASSWORD" -e ";" >/dev/null 2>&1; do
    sleep 1
  done
  printf "Database server is reachable.\n"
fi

if [ $# -gt 0 ]; then
  printf "Running TShock server with additional arguments: %s\n" "$*"
fi

# Arguments common to every launch
set -- -configpath "$CONFIG_PATH" -logpath "$LOG_PATH" -crashdir "${LOG_PATH}/crashes" -additionalplugins "$PLUGIN_PATH" "$@"

if [ -f "$WORLD_PATH" ]; then
  # Load existing world
  printf "Loading existing world: %s\n" "$WORLD_PATH"
  exec $SERVER_BINARY -world "$WORLD_PATH" "$@"

elif [ "$TEST_MODE" = "true" ]; then

  RANDOM_SEED=$(od -A n -t d -N 3 /dev/urandom | tr -d ' ')
  printf "No existing world file specified.\n"
  printf "Creating new world with default name and seed %s.\n" "$RANDOM_SEED"
  exec $SERVER_BINARY -world "$WORLD_PATH" -autocreate 1 -worldname "Terraria" -seed "$RANDOM_SEED" "$@"

else
  printf "Error: A volume with a World file must be mounted to '%s' to persist your progress. Exiting.\n" "$WORLD_PATH"
  exit 1
fi
