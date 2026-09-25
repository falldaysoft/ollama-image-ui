#!/bin/bash
# Start the web UI: set up and activate .venv if needed, then run the server.
set -e
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  echo "Creating virtual environment in .venv..."
  python3 -m venv .venv
fi
source .venv/bin/activate

# Install dependencies on first run and whenever requirements.txt changes
STAMP=.venv/.requirements-installed
if [[ ! -f $STAMP || requirements.txt -nt $STAMP ]]; then
  echo "Installing dependencies..."
  pip install -q -r requirements.txt
  touch "$STAMP"
fi

PORT=$(python3 -c "from app.config import PORT; print(PORT)")
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || true)

if lsof -ti :"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already in use; the server may already be running at http://localhost:$PORT" >&2
  exit 1
fi

# Print the URL once the server answers, after its startup logs
(
  until curl -s -o /dev/null "http://localhost:$PORT/api/queue"; do sleep 0.5; done
  echo
  echo "  Image Generator: http://localhost:$PORT"
  [[ -n $LAN_IP ]] && echo "  On your network: http://$LAN_IP:$PORT"
  echo
) &

exec python3 run.py
