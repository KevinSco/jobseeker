#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
COMPOSE_FILE="docker/kasm-local/docker-compose.yml"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Install Docker Engine (or Docker Desktop) first."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker engine is not running."
  echo "Start it (e.g. sudo systemctl start docker) and re-run this script."
  exit 1
fi

port_ok() {
  local url="$1"
  local insecure="${2:-}"
  if [[ "$insecure" == "insecure" ]]; then
    curl -sk --max-time 4 -o /dev/null "$url"
  else
    curl -sf --max-time 4 -o /dev/null "$url"
  fi
}

bridge_has_gateway() {
  # When the compose bridge loses its gateway IP, published ports accept TCP
  # but never respond (Watch + CDP hang). Detect and recreate.
  local net_id bridge
  net_id="$(docker network inspect kasm-local_default -f '{{.Id}}' 2>/dev/null || true)"
  [[ -n "$net_id" ]] || return 1
  bridge="br-${net_id:0:12}"
  ip -4 addr show "$bridge" 2>/dev/null | grep -q 'inet '
}

echo "Pulling / starting Chrome-only containers (not a full desktop)..."
if ! docker compose -f "$COMPOSE_FILE" up -d; then
  echo "Failed to start Chrome containers."
  exit 1
fi

echo
echo "Waiting for CDP / Watch ports..."
ready=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if port_ok "http://127.0.0.1:9333/json/version" && port_ok "https://127.0.0.1:6911/" insecure; then
    ready=1
    break
  fi
  sleep 2
done

if [[ "$ready" -ne 1 ]] || ! bridge_has_gateway; then
  echo "Kasm ports did not respond (or Docker bridge gateway IP is missing)."
  echo "Recreating the compose network and containers..."
  docker compose -f "$COMPOSE_FILE" down
  docker network rm kasm-local_default 2>/dev/null || true
  docker compose -f "$COMPOSE_FILE" up -d
  ready=0
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    if port_ok "http://127.0.0.1:9333/json/version" && port_ok "https://127.0.0.1:6911/" insecure; then
      ready=1
      break
    fi
    sleep 2
  done
fi

if [[ "$ready" -ne 1 ]]; then
  echo "ERROR: Kasm Chrome is still unreachable on :6911 / :9333."
  echo "Try: docker compose -f $COMPOSE_FILE down && docker network prune -f && $0"
  exit 1
fi

echo
echo "Local Chrome browser is up (flexible resize):"
echo "  Watch:  https://127.0.0.1:6911/?resize=remote  (no Kasm password — gate via JobSeek sign-in)"
echo "  CDP:    http://127.0.0.1:9333"
echo
echo "Open Watch from JobSeek (sign in required). Resize the browser window — the desktop follows."
echo "Accept the self-signed cert once if prompted."
echo "Then set KASM_ENABLED=true in .env and restart the JobSeek dashboard."
exit 0
