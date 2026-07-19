#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Keep Playwright browsers in the project so sandbox paths can't break launches.
export PLAYWRIGHT_BROWSERS_PATH="${ROOT}/.playwright-browsers"

if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PYTHON="${ROOT}/.venv/bin/python"
else
  echo "Virtual environment not found. Creating .venv ..."
  if ! python3 -m venv .venv; then
    echo "Failed to create .venv. Is python3-venv installed?"
    exit 1
  fi
  PYTHON="${ROOT}/.venv/bin/python"
  echo "Installing Python packages ..."
  if ! "$PYTHON" -m pip install -e . -q; then
    echo "Failed to install project dependencies."
    exit 1
  fi
fi

# Ensure Playwright Chromium is installed (needed for Find Jobs / portal search).
if ! "$PYTHON" -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True); b.close(); p.stop()" >/dev/null 2>&1; then
  echo "Playwright browser not found. Installing Chromium now..."
  echo "This can take a few minutes the first time."
  echo
  if ! "$PYTHON" -m playwright install chromium; then
    echo "Failed to install Playwright Chromium."
    exit 1
  fi
  echo "Playwright Chromium installed."
  echo
fi

echo "Starting JobSeek dashboard at http://127.0.0.1:8000"
echo "Press Ctrl+C to stop."
echo

if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://127.0.0.1:8000" >/dev/null 2>&1 || true
elif command -v sensible-browser >/dev/null 2>&1; then
  sensible-browser "http://127.0.0.1:8000" >/dev/null 2>&1 || true
fi

exec "$PYTHON" -m job_automation.main dashboard --host 127.0.0.1 --port 8000
