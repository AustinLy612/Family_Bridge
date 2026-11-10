#!/bin/bash

# One-click macOS launcher for the local FamilyBridge Lantern Forest demo.
# The project directory is resolved from this file, so the folder can be moved.

set -u

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
STATE_DIR="$PROJECT_DIR/.familybridge-launcher"
PID_FILE="$STATE_DIR/dev.pid"
LOG_FILE="$STATE_DIR/dev.log"
STOP_REQUEST_FILE="$STATE_DIR/stop-requested"

# These ports come from vite.config.ts and server/index.ts.
CLIENT_PORT=5173
BACKEND_PORT=3001
GAME_URL="http://localhost:$CLIENT_PORT"
HEALTH_MARKER='"service":"FamilyBridge Lantern Forest"'
DEV_PID=""

mkdir -p "$STATE_DIR"
cd "$PROJECT_DIR" || exit 1

print_rule() {
  printf '%s\n' "────────────────────────────────────────────────────────"
}

keep_terminal_open() {
  local exit_code="${1:-1}"
  printf '\n'
  print_rule
  printf 'FamilyBridge did not start. The message above explains why.\n'
  printf 'This Terminal window will stay open so you can read it.\n'
  if [[ -t 0 ]]; then
    read -r -p "Press Return to close this window... "
  fi
  exit "$exit_code"
}

familybridge_health_is_ready() {
  local health_url="$1"
  local response
  response="$(curl -fsS --max-time 2 "$health_url" 2>/dev/null || true)"
  printf '%s' "$response" | grep -Fq "$HEALTH_MARKER"
}

find_lsof() {
  if [[ -x /usr/sbin/lsof ]]; then
    printf '%s' /usr/sbin/lsof
  else
    command -v lsof 2>/dev/null || true
  fi
}

port_is_listening() {
  local port="$1"
  local lsof_bin
  lsof_bin="$(find_lsof)"
  [[ -n "$lsof_bin" ]] && "$lsof_bin" -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

open_game() {
  printf 'Opening %s\n' "$GAME_URL"
  if [[ "${FAMILYBRIDGE_SKIP_BROWSER:-0}" != "1" ]]; then
    open "$GAME_URL"
  fi
}

managed_process_is_active() {
  local pid="$1"
  local command_line
  local process_cwd
  local lsof_bin

  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1

  command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  case "$command_line" in
    *pnpm*run*dev*) ;;
    *) return 1 ;;
  esac

  lsof_bin="$(find_lsof)"
  if [[ -n "$lsof_bin" ]]; then
    process_cwd="$("$lsof_bin" -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
    [[ "$process_cwd" == "$PROJECT_DIR" ]] || return 1
  fi

  return 0
}

wait_for_existing_launcher() {
  local pid="$1"
  local attempt

  printf 'A launcher-managed FamilyBridge process is already starting (PID %s).\n' "$pid"
  printf 'Waiting for its verified health check instead of starting a duplicate...\n'
  for ((attempt = 1; attempt <= 60; attempt += 1)); do
    if familybridge_health_is_ready "$GAME_URL/api/health"; then
      printf 'FamilyBridge is ready.\n'
      open_game
      exit 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 1
  done

  printf '\nThe existing launcher process did not become ready.\n'
  [[ -f "$LOG_FILE" ]] && tail -n 60 "$LOG_FILE"
  keep_terminal_open 1
}

cleanup_pid_file() {
  local recorded_pid=""
  if [[ -f "$PID_FILE" ]]; then
    recorded_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -z "$DEV_PID" || "$recorded_pid" == "$DEV_PID" ]]; then
      rm -f "$PID_FILE"
    fi
  fi
}

collect_descendants() {
  local parent_pid="$1"
  local child_pid
  for child_pid in $(pgrep -P "$parent_pid" 2>/dev/null || true); do
    collect_descendants "$child_pid"
  done
  printf '%s\n' "$parent_pid"
}

stop_own_process_tree() {
  local pid_list
  local process_pid
  [[ -n "$DEV_PID" ]] || return 0
  kill -0 "$DEV_PID" 2>/dev/null || return 0
  pid_list="$(collect_descendants "$DEV_PID")"
  for process_pid in $pid_list; do
    kill -TERM "$process_pid" 2>/dev/null || true
  done
}

handle_terminal_close() {
  printf '\nStopping the launcher-managed FamilyBridge session...\n'
  touch "$STOP_REQUEST_FILE"
  stop_own_process_tree
  cleanup_pid_file
  exit 130
}

printf '\n'
print_rule
printf ' GenAI-DBT FamilyBridge · Lantern Forest\n'
printf ' macOS local launcher\n'
print_rule
printf 'Project: %s\n\n' "$PROJECT_DIR"

# nvm is not loaded automatically for Finder-launched .command files.
if [[ -s "$HOME/.nvm/nvm.sh" ]]; then
  printf 'Loading Node.js from nvm...\n'
  set +u
  # shellcheck source=/dev/null
  . "$HOME/.nvm/nvm.sh"
  set -u
fi

# A verified existing FamilyBridge session can be opened without requiring a
# second local Node/pnpm installation.
if familybridge_health_is_ready "$GAME_URL/api/health"; then
  printf 'FamilyBridge is already running and its health check is verified.\n'
  printf 'No duplicate server will be started.\n'
  open_game
  exit 0
fi

# If the launcher was clicked twice during startup, wait for the first launch.
if [[ -f "$PID_FILE" ]]; then
  RECORDED_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if managed_process_is_active "$RECORDED_PID"; then
    wait_for_existing_launcher "$RECORDED_PID"
  else
    printf 'Removing a stale launcher PID record.\n'
    rm -f "$PID_FILE"
  fi
fi

# Do not mistake an unrelated website on the configured port for FamilyBridge.
if port_is_listening "$CLIENT_PORT"; then
  printf 'ERROR: Port %s is already in use, but its health check does not identify FamilyBridge.\n' "$CLIENT_PORT"
  printf 'Close the other application using port %s, then double-click this launcher again.\n' "$CLIENT_PORT"
  keep_terminal_open 1
fi

if port_is_listening "$BACKEND_PORT"; then
  if familybridge_health_is_ready "http://localhost:$BACKEND_PORT/api/health"; then
    printf 'ERROR: A FamilyBridge backend is running on port %s without the verified web client.\n' "$BACKEND_PORT"
    printf 'Stop that earlier session first, then double-click this launcher again.\n'
  else
    printf 'ERROR: Port %s is being used by another application.\n' "$BACKEND_PORT"
    printf 'FamilyBridge needs that port for Express and Socket.IO. Close the other application first.\n'
  fi
  keep_terminal_open 1
fi

if ! command -v node >/dev/null 2>&1; then
  printf 'ERROR: Node.js is not installed or is not available to Finder-launched Terminal windows.\n'
  printf 'Install Node.js 20 or newer from https://nodejs.org, or install it with nvm.\n'
  printf 'If you use nvm, confirm that $HOME/.nvm/nvm.sh exists.\n'
  keep_terminal_open 1
fi

NODE_MAJOR="$(node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || true)"
if [[ ! "$NODE_MAJOR" =~ ^[0-9]+$ ]] || (( NODE_MAJOR < 20 )); then
  printf 'ERROR: FamilyBridge requires Node.js 20 or newer. Found: %s\n' "$(node --version 2>/dev/null || printf 'unknown')"
  printf 'Install or select a newer Node.js version, then run the launcher again.\n'
  keep_terminal_open 1
fi

if ! command -v pnpm >/dev/null 2>&1; then
  printf 'ERROR: pnpm is not installed or is not on PATH.\n'
  printf 'After installing Node.js, install pnpm with one of these commands:\n'
  printf '  corepack enable\n'
  printf '  corepack prepare pnpm@latest --activate\n'
  printf 'Or: npm install --global pnpm\n'
  keep_terminal_open 1
fi

if [[ ! -f "$PROJECT_DIR/package.json" ]]; then
  printf 'ERROR: package.json is missing from:\n  %s\n' "$PROJECT_DIR"
  printf 'Keep this launcher in the FamilyBridge project root directory.\n'
  keep_terminal_open 1
fi

if [[ ! -x "$PROJECT_DIR/node_modules/.bin/vite" || ! -x "$PROJECT_DIR/node_modules/.bin/tsx" || ! -x "$PROJECT_DIR/node_modules/.bin/concurrently" ]]; then
  printf 'ERROR: Project dependencies are missing or incomplete.\n'
  printf 'Open Terminal, run the following commands once, then double-click the launcher again:\n\n'
  printf '  cd %q\n' "$PROJECT_DIR"
  printf '  pnpm install\n'
  keep_terminal_open 1
fi

printf 'Node.js: %s\n' "$(node --version)"
printf 'pnpm:   %s\n' "$(pnpm --version)"
printf 'Starting the existing project command: pnpm run dev\n'
printf 'Logs: %s\n\n' "$LOG_FILE"

rm -f "$STOP_REQUEST_FILE"
: > "$LOG_FILE"

trap handle_terminal_close INT TERM HUP

# Process substitution keeps the real pnpm PID available for the safe Stop
# launcher while also displaying and saving all development logs.
pnpm run dev > >(tee -a "$LOG_FILE") 2>&1 &
DEV_PID=$!
printf '%s\n' "$DEV_PID" > "$PID_FILE"

READY=0
for ((ATTEMPT = 1; ATTEMPT <= 90; ATTEMPT += 1)); do
  if familybridge_health_is_ready "$GAME_URL/api/health"; then
    READY=1
    break
  fi
  if ! kill -0 "$DEV_PID" 2>/dev/null; then
    break
  fi
  sleep 1
done

if [[ "$READY" -ne 1 ]]; then
  printf '\nERROR: FamilyBridge did not pass its verified health check within 90 seconds.\n'
  stop_own_process_tree
  wait "$DEV_PID" 2>/dev/null || true
  cleanup_pid_file
  printf '\nRecent launcher log:\n'
  tail -n 80 "$LOG_FILE" 2>/dev/null || true
  keep_terminal_open 1
fi

printf '\nFamilyBridge is ready. Both the web client and backend health check responded correctly.\n'
open_game
printf '\nKeep this Terminal window open while using the game.\n'
printf 'To stop safely, double-click “Stop FamilyBridge.command” or press Control-C here.\n\n'

wait "$DEV_PID"
DEV_STATUS=$?
cleanup_pid_file

if [[ -f "$STOP_REQUEST_FILE" ]]; then
  rm -f "$STOP_REQUEST_FILE"
  printf '\nFamilyBridge stopped safely.\n'
  exit 0
fi

if [[ "$DEV_STATUS" -ne 0 ]]; then
  printf '\nERROR: The FamilyBridge development process exited with status %s.\n' "$DEV_STATUS"
  printf 'Recent launcher log:\n'
  tail -n 80 "$LOG_FILE" 2>/dev/null || true
  keep_terminal_open "$DEV_STATUS"
fi

printf '\nFamilyBridge stopped.\n'

