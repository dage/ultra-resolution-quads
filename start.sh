#!/usr/bin/env bash
set -euo pipefail

# Ports
BACKEND_PORT="${BACKEND_PORT:-8002}"
FRONTEND_PORT="${FRONTEND_PORT:-8001}"

RED=""
GREEN=""
BLUE=""
YELLOW=""
RESET=""
if command -v tput >/dev/null 2>&1; then
    if tput colors >/dev/null 2>&1; then
        RED=$(tput setaf 1)
        GREEN=$(tput setaf 2)
        BLUE=$(tput setaf 4)
        YELLOW=$(tput setaf 3)
        RESET=$(tput sgr0)
    fi
fi

# Ensure Python output is unbuffered so logs stream immediately
export PYTHONUNBUFFERED=1
export BACKEND_PORT

kill_on_port() {
    local port="$1"
    local pids
    pids=$(lsof -t -i :"${port}" 2>/dev/null || true)
    if [[ -n "${pids}" ]]; then
        echo "Stopping processes on port ${port}: ${pids}"
        kill ${pids} 2>/dev/null || true
        sleep 0.5
        # Force kill if still alive
        pids=$(lsof -t -i :"${port}" 2>/dev/null || true)
        [[ -n "${pids}" ]] && kill -9 ${pids} 2>/dev/null || true
    fi
}

prefix_stream() {
    local label="$1"
    local color="$2"
    shift 2
    { "$@" 2>&1 | while IFS= read -r line; do
        local line_color="${color}"
        if [[ "${line}" =~ (ERROR|Error|CRITICAL|Traceback) ]]; then
            line_color="${RED}"
        elif [[ "${line}" =~ (WARN|Warning) ]]; then
            line_color="${YELLOW}"
        fi
        printf "%b[%s]%b %s\n" "${line_color}" "${label}" "${RESET}" "${line}"
    done; }
}

kill_on_port "${BACKEND_PORT}"
kill_on_port "${FRONTEND_PORT}"

pids=()

echo "Starting backend live renderer on port ${BACKEND_PORT}..."
prefix_stream "backend" "${GREEN}" python backend/live_server.py &
pid_backend=$!
pids+=("${pid_backend}")

echo "Starting frontend static server on port ${FRONTEND_PORT}..."
prefix_stream "frontend" "${BLUE}" python -m http.server "${FRONTEND_PORT}" &
pid_frontend=$!
pids+=("${pid_frontend}")

cleanup() {
    echo "Shutting down..."
    for pid in "${pids[@]}"; do
        kill "${pid}" 2>/dev/null || true
    done
}

trap cleanup INT TERM EXIT

echo
echo "Frontend:  http://localhost:${FRONTEND_PORT}/frontend/index.html"
echo "Backend:   http://localhost:${BACKEND_PORT}/live/<dataset>/<level>/<x>/<y>.webp"
echo "Press Ctrl+C to stop."
echo

wait "${pids[@]}"
