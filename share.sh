#!/usr/bin/env bash
# Put the local app on a public HTTPS URL so you can use it from your phone.
#
# Requests to YouTube still leave from this machine's connection, which is why
# this works where a cloud deployment does not.
#
#   ./share.sh                                  random trycloudflare.com address
#   TUNNEL_HOSTNAME=study.example.com ./share.sh    your own domain, fixed
#
# For the second form, see "Using your own domain" in the README — it needs a
# one-time `cloudflared tunnel login` and a DNS route.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
TUNNEL_NAME="${TUNNEL_NAME:-transcript-study}"
TUNNEL_HOSTNAME="${TUNNEL_HOSTNAME:-}"

[ -d .venv ] || { echo "Run ./setup.sh first."; exit 1; }
command -v cloudflared >/dev/null || {
  echo "cloudflared is missing. Install it with:  brew install cloudflared"
  exit 1
}

SERVER_PID=""
cleanup() {
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if curl -fsS "http://127.0.0.1:$PORT/api/capabilities" >/dev/null 2>&1; then
  echo "Using the server already on port $PORT."
else
  echo "Starting the server on port $PORT…"
  # TRUST_PROXY makes the rate limiter read the real client address from the
  # tunnel's forwarded header rather than seeing every request as localhost.
  TRUST_PROXY=1 .venv/bin/uvicorn app:app --app-dir backend \
    --host 127.0.0.1 --port "$PORT" >/dev/null 2>&1 &
  SERVER_PID=$!
  for _ in $(seq 1 30); do
    curl -fsS "http://127.0.0.1:$PORT/api/capabilities" >/dev/null 2>&1 && break
    sleep 0.5
  done
fi

echo

if [ -n "$TUNNEL_HOSTNAME" ]; then
  if ! cloudflared tunnel info "$TUNNEL_NAME" >/dev/null 2>&1; then
    echo "No tunnel named '$TUNNEL_NAME' yet. One-time setup:"
    echo
    echo "  cloudflared tunnel login"
    echo "  cloudflared tunnel create $TUNNEL_NAME"
    echo "  cloudflared tunnel route dns $TUNNEL_NAME $TUNNEL_HOSTNAME"
    echo
    exit 1
  fi
  echo "Serving on https://$TUNNEL_HOSTNAME — this address is yours and does"
  echo "not change. Ctrl-C to stop sharing."
  echo
  exec cloudflared tunnel run --url "http://127.0.0.1:$PORT" "$TUNNEL_NAME"
fi

echo "Opening a tunnel. The https://… trycloudflare.com address below is your"
echo "phone URL. It is public to anyone who has it, and changes each run."
echo "Set TUNNEL_HOSTNAME to use your own domain instead."
echo "Press Ctrl-C to close the tunnel and stop sharing."
echo

exec cloudflared tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate
