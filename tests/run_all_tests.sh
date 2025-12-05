#!/usr/bin/env bash
# run_all_tests.sh — compact runner for Python + Node tests in the repo.
# Prints ✅/❌ per step and exits non-zero on failure.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

status=0

run_test() {
  local label="$1"; shift
  local logfile; logfile="$(mktemp)"
  printf "• %s... " "$label"
  if "$@" >"$logfile" 2>&1; then
    echo "✅"
  else
    echo "❌"
    status=1
    cat "$logfile"
  fi
  rm -f "$logfile"
}

run_test "Python unit tests" python -m unittest tests.test_camera_parity
run_test "Frontend logic tests (Node)" node tests/test_frontend.js
run_test "Precision tests (Decimal.js)" node tests/test_precision.js
run_test "Audit path tiles (Python)" python tests/audit_path_tiles.py

if [[ $status -eq 0 ]]; then
  echo "All tests passed ✅"
else
  echo "Some tests failed ❌"
fi
exit $status
