#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
artifacts_dir="${repo_root}/artifacts/iterate_t2i"

pidfile="${COMFYUI_PIDFILE:-${artifacts_dir}/comfyui_server.pid}"

if [[ ! -f "${pidfile}" ]]; then
  echo "No pidfile found at ${pidfile}. Nothing to stop."
  exit 0
fi

pid="$(cat "${pidfile}" || true)"
if [[ -z "${pid}" ]]; then
  rm -f "${pidfile}" || true
  echo "Empty pidfile. Removed."
  exit 0
fi

if ! kill -0 "${pid}" 2>/dev/null; then
  rm -f "${pidfile}" || true
  echo "ComfyUI server not running (stale pidfile pid=${pid}). Removed."
  exit 0
fi

cmdline="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
if [[ "${cmdline}" != *"ComfyUI/main.py"* ]] && [[ "${COMFYUI_FORCE_KILL:-}" != "1" ]]; then
  echo "Refusing to stop pid=${pid} because it doesn't look like ComfyUI main.py:" >&2
  echo "${cmdline}" >&2
  echo "Set COMFYUI_FORCE_KILL=1 to override." >&2
  exit 1
fi

echo "Stopping ComfyUI server (pid=${pid})..."

for sig in INT TERM KILL; do
  if ! kill -0 "${pid}" 2>/dev/null; then
    break
  fi

  kill "-${sig}" "-${pid}" 2>/dev/null || kill "-${sig}" "${pid}" 2>/dev/null || true

  timeout_s=0
  case "${sig}" in
    INT) timeout_s=15 ;;
    TERM) timeout_s=5 ;;
    KILL) timeout_s=1 ;;
  esac

  for _ in $(seq 1 $((timeout_s * 10))); do
    if ! kill -0 "${pid}" 2>/dev/null; then
      break
    fi
    sleep 0.1
  done
done

if kill -0 "${pid}" 2>/dev/null; then
  echo "Failed to stop ComfyUI server pid=${pid}." >&2
  exit 1
fi

rm -f "${pidfile}" || true
echo "Stopped."

