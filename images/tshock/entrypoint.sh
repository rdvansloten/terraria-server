#!/bin/sh

SERVER_BINARY="./TShock.Server"
WORLD_DIR="/terraria/${DEFAULT_TERRARIA_SERVER_PATH}/Worlds"
WORLD_PATH="${WORLD_DIR}/${WORLD_FILENAME}"
WORLD_NAME="${WORLD_FILENAME%.wld}"
CONFIG_FILE="${CONFIG_PATH}/config.json"

# TEST_MODE: create a small world with a random seed when none exists
if [ "$TEST_MODE" = "true" ]; then
  : "${AUTOCREATE:=1}"
  : "${SEED:=$(od -A n -t d -N 3 /dev/urandom | tr -d ' ')}"
fi

# Print server information
printf "Server binary : %s\n" "$SERVER_BINARY"
printf "TShock version: %s\n" "$TSHOCK_VERSION"
printf "Architecture  : %s\n" "$TARGETARCH"
printf "World file    : %s\n" "$WORLD_PATH"
printf "Log path      : %s\n" "$LOG_PATH"
printf "Config path   : %s\n" "$CONFIG_PATH"
printf "Plugin path   : %s\n" "$PLUGIN_PATH"
printf "Autocreate    : %s\n" "${AUTOCREATE:-off}"
printf "Wait for world: %s\n" "${WAIT_FOR_WORLD:-false}"

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

# Wait for a world file to be copied in (e.g. kubectl cp / docker cp). Only start once the
# file has stopped growing so a half-copied world is never opened.
if [ ! -f "$WORLD_PATH" ] && [ "$WAIT_FOR_WORLD" = "true" ]; then
  printf "Waiting for world file: %s\n" "$WORLD_PATH"
  printf "Import an existing world with, for example:\n"
  printf "  kubectl cp ./MyWorld.wld <namespace>/<pod>:%s\n" "$WORLD_PATH"
  printf "  docker exec -i <container> sh -c 'cat > %s' < ./MyWorld.wld\n" "$WORLD_PATH"
  previous_size=-1
  while :; do
    if [ -f "$WORLD_PATH" ]; then
      size=$(wc -c < "$WORLD_PATH")
      if [ "$size" -gt 0 ] && [ "$size" = "$previous_size" ]; then
        break
      fi
      previous_size=$size
    fi
    sleep 3
  done
  printf "World file received (%s bytes).\n" "$size"
fi

# Arguments common to every launch
set -- -configpath "$CONFIG_PATH" -logpath "$LOG_PATH" -crashdir "${LOG_PATH}/crashes" -additionalplugins "$PLUGIN_PATH" "$@"

if [ -f "$WORLD_PATH" ]; then
  # Load existing world
  printf "Loading existing world: %s\n" "$WORLD_PATH"
  exec $SERVER_BINARY -world "$WORLD_PATH" "$@"

elif [ -n "$AUTOCREATE" ]; then
  case "$AUTOCREATE" in
    1|2|3) ;;
    *) printf "Error: AUTOCREATE must be 1 (small), 2 (medium) or 3 (large), got '%s'. Exiting.\n" "$AUTOCREATE"; exit 1 ;;
  esac
  printf "No existing world found. Creating world '%s' (size %s%s%s).\n" "$WORLD_NAME" "$AUTOCREATE" \
    "${SEED:+, seed $SEED}" "${DIFFICULTY:+, difficulty $DIFFICULTY}"
  exec $SERVER_BINARY -world "$WORLD_PATH" -autocreate "$AUTOCREATE" -worldname "$WORLD_NAME" ${SEED:+-seed "$SEED"} ${DIFFICULTY:+-difficulty "$DIFFICULTY"} "$@"

else
  printf "Error: No world file at '%s'.\n" "$WORLD_PATH"
  printf "Either mount a volume containing it, set AUTOCREATE=1|2|3 to generate one,\n"
  printf "or set WAIT_FOR_WORLD=true and copy it in while the container waits. Exiting.\n"
  exit 1
fi
