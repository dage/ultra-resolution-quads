#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
artifacts_dir="${repo_root}/artifacts/iterate_t2i"

mkdir -p "${artifacts_dir}"

pidfile="${COMFYUI_PIDFILE:-${artifacts_dir}/comfyui_server.pid}"
logfile="${COMFYUI_LOGFILE:-${artifacts_dir}/comfyui_server.log}"

COMFYUI_APP="${COMFYUI_APP:-/Applications/ComfyUI.app}"
COMFYUI_RESOURCES="${COMFYUI_RESOURCES:-${COMFYUI_APP}/Contents/Resources}"
COMFYUI_MAIN_PY="${COMFYUI_MAIN_PY:-${COMFYUI_RESOURCES}/ComfyUI/main.py}"

COMFYUI_BASE_DIR="${COMFYUI_BASE_DIR:-/Volumes/Samsung_T5/comfyui_models}"
COMFYUI_PYTHON="${COMFYUI_PYTHON:-${COMFYUI_BASE_DIR}/.venv/bin/python}"
COMFYUI_USER_DIR="${COMFYUI_USER_DIR:-${COMFYUI_BASE_DIR}/user}"
COMFYUI_INPUT_DIR="${COMFYUI_INPUT_DIR:-${COMFYUI_BASE_DIR}/input}"
COMFYUI_OUTPUT_DIR="${COMFYUI_OUTPUT_DIR:-${COMFYUI_BASE_DIR}/output}"
COMFYUI_FRONTEND_ROOT="${COMFYUI_FRONTEND_ROOT:-${COMFYUI_RESOURCES}/ComfyUI/web_custom_versions/desktop_app}"
COMFYUI_EXTRA_MODELS_CONFIG="${COMFYUI_EXTRA_MODELS_CONFIG:-${HOME}/Library/Application Support/ComfyUI/extra_models_config.yaml}"

COMFYUI_LISTEN="${COMFYUI_LISTEN:-127.0.0.1}"
COMFYUI_PORT="${COMFYUI_PORT:-8000}"

if [[ -f "${pidfile}" ]]; then
  existing_pid="$(cat "${pidfile}" || true)"
  if [[ -n "${existing_pid}" ]] && kill -0 "${existing_pid}" 2>/dev/null; then
    echo "ComfyUI already running (pid=${existing_pid})."
    echo "Log: ${logfile}"
    echo "URL: http://${COMFYUI_LISTEN}:${COMFYUI_PORT}"
    exit 0
  fi
  rm -f "${pidfile}" || true
fi

if [[ ! -x "${COMFYUI_PYTHON}" ]]; then
  echo "ERROR: COMFYUI_PYTHON is not executable: ${COMFYUI_PYTHON}" >&2
  echo "Set COMFYUI_PYTHON to your venv python path." >&2
  exit 1
fi

if [[ ! -f "${COMFYUI_MAIN_PY}" ]]; then
  echo "ERROR: COMFYUI_MAIN_PY not found: ${COMFYUI_MAIN_PY}" >&2
  echo "Set COMFYUI_APP/COMFYUI_RESOURCES/COMFYUI_MAIN_PY to match your install." >&2
  exit 1
fi

mkdir -p "$(dirname -- "${logfile}")"

cmd=(
  "${COMFYUI_PYTHON}"
  "${COMFYUI_MAIN_PY}"
  --user-directory "${COMFYUI_USER_DIR}"
  --input-directory "${COMFYUI_INPUT_DIR}"
  --output-directory "${COMFYUI_OUTPUT_DIR}"
  --front-end-root "${COMFYUI_FRONTEND_ROOT}"
  --base-directory "${COMFYUI_BASE_DIR}"
  --extra-model-paths-config "${COMFYUI_EXTRA_MODELS_CONFIG}"
  --log-stdout
  --listen "${COMFYUI_LISTEN}"
  --port "${COMFYUI_PORT}"
  --enable-manager
)

{
  echo "=== $(date +\"%Y-%m-%dT%H:%M:%S%z\") start_comfyui_server.sh ==="
  echo "cwd=${COMFYUI_BASE_DIR}"
  printf "cmd="; printf "%q " "${cmd[@]}"; echo
} >>"${logfile}"

if command -v setsid >/dev/null 2>&1; then
  setsid "${cmd[@]}" >>"${logfile}" 2>&1 < /dev/null &
else
  nohup "${cmd[@]}" >>"${logfile}" 2>&1 < /dev/null &
fi

pid=$!
echo "${pid}" >"${pidfile}"

echo "Started ComfyUI server (pid=${pid})."
echo "Log: ${logfile}"
echo "URL: http://${COMFYUI_LISTEN}:${COMFYUI_PORT}"

if command -v curl >/dev/null 2>&1; then
  for _ in $(seq 1 50); do
    if curl -fsS --max-time 1 "http://${COMFYUI_LISTEN}:${COMFYUI_PORT}/" >/dev/null 2>&1; then
      echo "Server is responding."
      exit 0
    fi
    sleep 0.2
  done
  echo "Started, but did not confirm HTTP responsiveness within 10s. Check the log if needed."
fi
