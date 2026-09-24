#!/bin/sh

# Select executable based on architecture
if [ "$TARGETARCH" = "arm64" ] || [ "$TARGETARCH" = "arm" ]; then
  SERVER_BINARY="mono ./TerrariaServer.exe"
else
  SERVER_BINARY="./TerrariaServer"
fi

WORLD_DIR="/terraria/${DEFAULT_TERRARIA_SERVER_PATH}/Worlds"
WORLD_PATH="${WORLD_DIR}/${WORLD_FILENAME}"
CONFIG_FILE="${CONFIG_PATH}/${CONFIG_FILENAME}"

if [ ! -f "$CONFIG_FILE" ]; then
  if cp "${TERRARIA_SERVER_PATH}/${CONFIG_FILENAME}.default" "$CONFIG_FILE" 2>/dev/null; then
    printf "No %s found in %s, seeded the default. Edit it and restart to apply changes.\n" "$CONFIG_FILENAME" "$CONFIG_PATH"
  else
    printf "Warning: no %s in %s and the directory is not writable by uid %s, so the server\n" "$CONFIG_FILENAME" "$CONFIG_PATH" "$(id -u)"
    printf "Warning: runs with built-in defaults. Fix with: chown 999 <host folder>  (or chmod 777).\n"
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
printf "Architecture  : %s\n" "$TARGETARCH"
printf "World file    : %s\n" "$WORLD_PATH"
printf "Log path      : %s\n" "$LOG_PATH"
printf "Config file   : %s\n" "${CONFIG_PATH}/${CONFIG_FILENAME}"
printf "Autocreate    : %s\n" "${AUTOCREATE:-off}"
printf "Wait for world: %s\n" "${WAIT_FOR_WORLD:-false}"

# lives on tmpfs, so the volume never sees the password.
EFFECTIVE_CONFIG="/tmp/serverconfig.effective.txt"
umask 077
{
  grep -vE '^(autocreate|seed|difficulty|worldname|password)=' "$CONFIG_FILE" 2>/dev/null
  [ -n "$AUTOCREATE" ] && printf 'autocreate=%s\n' "$AUTOCREATE"
  [ -n "$SEED" ] && printf 'seed=%s\n' "$SEED"
  [ -n "$DIFFICULTY" ] && printf 'difficulty=%s\n' "$DIFFICULTY"
  printf 'worldname=%s\n' "$WORLD_NAME"
  [ -n "$TERRARIA_PASSWORD" ] && printf 'password=%s\n' "$TERRARIA_PASSWORD"
  true
} > "$EFFECTIVE_CONFIG"
umask 022
if [ -n "$TERRARIA_PASSWORD" ]; then
  printf "Join password : set from TERRARIA_PASSWORD\n"
elif grep -qE '^password=.+' "$CONFIG_FILE" 2>/dev/null; then
  # keep the config file's own password
  grep -E '^password=.+' "$CONFIG_FILE" | tail -1 >> "$EFFECTIVE_CONFIG"
  printf "Join password : set in %s\n" "$(basename "$CONFIG_FILE")"
else
  printf "Join password : none. Anyone who can reach the port can join.\n"
fi

if [ $# -gt 0 ]; then
  printf "Running terraria-server with additional arguments: %s\n" "$*"
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

if [ -f "$WORLD_PATH" ]; then
  # Load existing world
  printf "Loading existing world: %s\n" "$WORLD_PATH"
  exec $SERVER_BINARY -config "$EFFECTIVE_CONFIG" -logpath "$LOG_PATH" -world "$WORLD_PATH" "$@"

elif [ -n "$AUTOCREATE" ]; then
  case "$AUTOCREATE" in
    1|2|3) ;;
    *) printf "Error: AUTOCREATE must be 1 (small), 2 (medium) or 3 (large), got '%s'. Exiting.\n" "$AUTOCREATE"; exit 1 ;;
  esac
  printf "No existing world found. Creating world '%s' (size %s%s%s).\n" "$WORLD_NAME" "$AUTOCREATE" \
    "${SEED:+, seed $SEED}" "${DIFFICULTY:+, difficulty $DIFFICULTY}"
  exec $SERVER_BINARY -config "$EFFECTIVE_CONFIG" -logpath "$LOG_PATH" -world "$WORLD_PATH" \
    -autocreate "$AUTOCREATE" -worldname "$WORLD_NAME" ${SEED:+-seed "$SEED"} ${DIFFICULTY:+-difficulty "$DIFFICULTY"} "$@"

else
  printf "Error: No world file at '%s'.\n" "$WORLD_PATH"
  printf "Either mount a volume containing it, set autocreate=1|2|3 in %s (or AUTOCREATE env),\n" "$CONFIG_FILENAME"
  printf "or set WAIT_FOR_WORLD=true and copy it in while the container waits. Exiting.\n"
  exit 1
fi
