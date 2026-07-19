#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

docker compose -f docker/kasm-local/docker-compose.yml down
echo "Stopped local Kasm Chrome containers."
exit 0
