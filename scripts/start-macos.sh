#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${MANHUA_PORT:-${PORT:-8002}}"

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "MANHUA_PORT/PORT must be an integer between 1 and 65535." >&2
  exit 2
fi

if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

".venv/bin/python" -m pip install -r requirements.txt

URL="http://localhost:${PORT}"
HEALTH_URL="${URL}/api/health"

open_when_ready() {
  for _ in $(seq 1 60); do
    if command -v curl >/dev/null 2>&1; then
      if curl -fsS --max-time 1 "$HEALTH_URL" >/dev/null 2>&1; then
        open_app_url
        return
      fi
    elif ".venv/bin/python" - "$HEALTH_URL" >/dev/null 2>&1 <<'PY'
import sys
import urllib.request

try:
    with urllib.request.urlopen(sys.argv[1], timeout=1) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
    then
      open_app_url
      return
    fi
    sleep 1
  done
}

open_app_url() {
  if command -v open >/dev/null 2>&1; then
    open "$URL" >/dev/null 2>&1
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1
  fi
}

open_when_ready &

MANHUA_PORT="$PORT" ".venv/bin/python" main.py
