#!/usr/bin/env bash
# Publish the local backend so Vapi's servers can reach our tools, then point the
# assistant at it. Quick tunnels get a new hostname every run, so re-pointing the
# assistant is the whole reason this is a script and not a note in the README.
#
#   make tunnel
#
# Ctrl-C takes the tunnel down with it.
set -euo pipefail

cd "$(dirname "$0")/.."
LOG=$(mktemp -t setu-tunnel)

command -v cloudflared >/dev/null || {
  echo "cloudflared is not installed:  brew install cloudflared" >&2
  exit 1
}

curl -sf -o /dev/null http://localhost:8000/api/v1/health || {
  echo "nothing is answering on :8000 — start the backend first (make dev, or see" >&2
  echo "infra/demo-script.md for the dev-local command)" >&2
  exit 1
}

# The endpoint 503s without this, so wiring an assistant at it would just produce a
# voice agent that fails mid-sentence. Settings are the authority, not this shell.
backend/.venv/bin/python - <<'PY' || exit 1
import sys

sys.path.insert(0, "backend")
from app.config import get_settings

if not get_settings().vapi_tool_secret:
    print("VAPI_TOOL_SECRET is not set in .env — the tool endpoint is closed", file=sys.stderr)
    print("Pick any long random string, put it in .env, restart the backend.", file=sys.stderr)
    sys.exit(1)
PY

echo "opening a quick tunnel to localhost:8000 …"
cloudflared tunnel --url http://localhost:8000 >"$LOG" 2>&1 &
TUNNEL_PID=$!
trap 'kill $TUNNEL_PID 2>/dev/null || true; rm -f "$LOG"' EXIT

URL=""
for _ in $(seq 1 30); do
  # cloudflared announces the hostname on stderr, a second or two in
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)
  [ -n "$URL" ] && break
  sleep 1
done

[ -n "$URL" ] || {
  echo "cloudflared never printed a URL. Its output:" >&2
  tail -20 "$LOG" >&2
  exit 1
}

echo
echo "  public base url : $URL"
echo "  vapi tools      : $URL/api/v1/channels/vapi/tools"
echo
echo "  ⚠ this publishes the WHOLE backend, staff login included. It is a demo-time"
echo "    tunnel: take it down when you are done, and never point it at real data."
echo

(cd backend && PUBLIC_BASE_URL="$URL" .venv/bin/python ../infra/vapi_setup.py)

echo
echo "tunnel is up. Ctrl-C to close it."
wait $TUNNEL_PID
