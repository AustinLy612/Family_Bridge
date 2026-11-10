#!/bin/bash

# Stops only the process tree recorded by Start FamilyBridge.command.

set -u

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
STATE_DIR="$PROJECT_DIR/.familybridge-launcher"
PID_FILE="$STATE_DIR/dev.pid"
STOP_REQUEST_FILE="$STATE_DIR/stop-requested"

print_rule() {
  printf '%s\n' "────────────────────────────────────────────────────────"
}

finish() {
  local exit_code="${1:-0}"
  if [[ -t 0 ]]; then
    printf '\n'
    read -r -p "Press Return to close this window... "
  fi
  exit "$exit_code"
}

find_lsof() {
  if [[ -x /usr/sbin/lsof ]]; then
    printf '%s' /usr/sbin/lsof
  else
    command -v lsof 2>/dev/null || true
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

printf '\n'
print_rule
printf ' Stop GenAI-DBT FamilyBridge · Lantern Forest\n'
print_rule

if [[ ! -f "$PID_FILE" ]]; then
  printf '\nNo launcher-managed FamilyBridge session is recorded.\n'
  printf 'Nothing was stopped. If you started the game manually, use Control-C in that Terminal window.\n'
  finish 0
fi

ROOT_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ ! "$ROOT_PID" =~ ^[0-9]+$ ]] || ! kill -0 "$ROOT_PID" 2>/dev/null; then
  printf '\nThe launcher record is stale; its process is no longer running.\n'
  rm -f "$PID_FILE" "$STOP_REQUEST_FILE"
  finish 0
fi

COMMAND_LINE="$(ps -p "$ROOT_PID" -o command= 2>/dev/null || true)"
case "$COMMAND_LINE" in
  *pnpm*run*dev*) ;;
  *)
    printf '\nSAFETY STOP: PID %s is not a “pnpm run dev” process.\n' "$ROOT_PID"
    printf 'No process was stopped. Remove %s manually if it is obsolete.\n' "$PID_FILE"
    finish 1
    ;;
esac

LSOF_BIN="$(find_lsof)"
if [[ -n "$LSOF_BIN" ]]; then
  PROCESS_CWD="$("$LSOF_BIN" -a -p "$ROOT_PID" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
  if [[ "$PROCESS_CWD" != "$PROJECT_DIR" ]]; then
    printf '\nSAFETY STOP: The recorded process is not running from this project directory.\n'
    printf 'Recorded PID: %s\nProcess directory: %s\nExpected directory: %s\n' "$ROOT_PID" "${PROCESS_CWD:-unknown}" "$PROJECT_DIR"
    printf 'No process was stopped.\n'
    finish 1
  fi
fi

PID_LIST="$(collect_descendants "$ROOT_PID")"
touch "$STOP_REQUEST_FILE"

printf '\nStopping launcher-managed process tree rooted at PID %s...\n' "$ROOT_PID"
for PROCESS_PID in $PID_LIST; do
  kill -TERM "$PROCESS_PID" 2>/dev/null || true
done

for ((ATTEMPT = 1; ATTEMPT <= 10; ATTEMPT += 1)); do
  if ! kill -0 "$ROOT_PID" 2>/dev/null; then
    break
  fi
  sleep 1
done

if kill -0 "$ROOT_PID" 2>/dev/null; then
  printf 'The process did not exit after 10 seconds; ending only the previously recorded process tree.\n'
  for PROCESS_PID in $PID_LIST; do
    kill -KILL "$PROCESS_PID" 2>/dev/null || true
  done
fi

rm -f "$PID_FILE"
printf 'FamilyBridge launcher processes stopped. Unrelated Node.js applications were not targeted.\n'
finish 0

