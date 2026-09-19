#!/bin/sh

SERVER_BINARY="./TShock.Server"
WORLD_DIR="/terraria/${DEFAULT_TERRARIA_SERVER_PATH}/Worlds"
WORLD_PATH="${WORLD_DIR}/${WORLD_FILENAME}"
TSHOCK_CONFIG_FILE="${CONFIG_PATH}/config.json"
CONFIG_FILE="${CONFIG_PATH}/serverconfig.txt"

if [ ! -f "$CONFIG_FILE" ]; then
  if cp "${TSHOCK_SERVER_PATH}/serverconfig.txt.default" "$CONFIG_FILE" 2>/dev/null; then
    printf "No serverconfig.txt found in %s, seeded the default. Edit it and restart to apply changes.\n" "$CONFIG_PATH"
  else
    printf "Warning: no serverconfig.txt in %s and the directory is not writable by uid %s.\n" "$CONFIG_PATH" "$(id -u)"
    printf "Warning: fix with: chown 999 <host folder>  (or chmod 777).\n"
  fi
fi

cfg() { sed -nE "s/^$1=(.*)$/\\1/p" "$CONFIG_FILE" 2>/dev/null | tail -1; }
AUTOCREATE="${AUTOCREATE:-$(cfg autocreate)}"
SEED="${SEED:-$(cfg seed)}"
DIFFICULTY="${DIFFICULTY:-$(cfg difficulty)}"
WORLD_NAME="${WORLD_NAME:-$(cfg worldname)}"
WORLD_NAME="${WORLD_NAME:-${WORLD_FILENAME%.wld}}"

if [ "$TEST_MODE" = "true" ]; then
  AUTOCREATE=1
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

if [ -f "$TSHOCK_CONFIG_FILE" ] && [ "$(jq -r '.Settings.StorageType' "$TSHOCK_CONFIG_FILE")" = "mysql" ]; then
  DATABASE_HOST=$(jq -r '.Settings.MySqlHost' "$TSHOCK_CONFIG_FILE" | cut -f1 -d':')
  DATABASE_PORT=$(jq -r '.Settings.MySqlHost' "$TSHOCK_CONFIG_FILE" | cut -f2 -d':')
  DATABASE_USER=$(jq -r '.Settings.MySqlUsername' "$TSHOCK_CONFIG_FILE")
  DATABASE_PASSWORD=$(jq -r '.Settings.MySqlPassword' "$TSHOCK_CONFIG_FILE")
  printf "Waiting for database server %s:%s\n" "$DATABASE_HOST" "$DATABASE_PORT"
  until mariadb -h "$DATABASE_HOST" -P "$DATABASE_PORT" -u "$DATABASE_USER" -p"$DATABASE_PASSWORD" -e ";" >/dev/null 2>&1; do
    sleep 1
  done
  printf "Database server is reachable.\n"
fi

if [ -n "$TERRARIA_PASSWORD" ]; then
  [ -f "$TSHOCK_CONFIG_FILE" ] || printf '{"Settings":{}}\n' > "$TSHOCK_CONFIG_FILE"
  tmp_config="$(mktemp)"
  jq --arg pw "$TERRARIA_PASSWORD" '.Settings.ServerPassword = $pw' "$TSHOCK_CONFIG_FILE" > "$tmp_config" \
    && cat "$tmp_config" > "$TSHOCK_CONFIG_FILE"
  rm -f "$tmp_config"
  printf "Join password : set from TERRARIA_PASSWORD (written to config.json ServerPassword)\n"
elif [ -f "$TSHOCK_CONFIG_FILE" ] && [ -n "$(jq -r '.Settings.ServerPassword // empty' "$TSHOCK_CONFIG_FILE")" ]; then
  printf "Join password : set in config.json (ServerPassword)\n"
else
  printf "Join password : none. Anyone who can reach the port can join.\n"
fi

if [ $# -gt 0 ]; then
  printf "Running TShock server with additional arguments: %s\n" "$*"
fi

mkdir -p "$WORLD_DIR" 2>/dev/null || true

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

if [ ! -f /tmp/GeoIP.dat ]; then
  cp "${TSHOCK_SERVER_PATH}/GeoIP.dat.orig" /tmp/GeoIP.dat && chmod 600 /tmp/GeoIP.dat
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
  printf "Either mount a volume containing it, set autocreate=1|2|3 in serverconfig.txt (or AUTOCREATE env),\n"
  printf "or set WAIT_FOR_WORLD=true and copy it in while the container waits. Exiting.\n"
  exit 1
fi
