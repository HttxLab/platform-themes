#!/usr/bin/env bash
# Open the login flow in headless Chrome and confirm the theme CSS reached the page.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
URL="${AUTHENTIK_PREVIEW_URL:-http://127.0.0.1:9000/if/flow/default-authentication-flow/}"
OUT="${AUTHENTIK_PREVIEW_PNG:-/tmp/authentik-login.png}"
DOM="${AUTHENTIK_PREVIEW_DOM:-/tmp/authentik-login.html}"
PROFILE="${AUTHENTIK_CHROME_PROFILE:-/tmp/chrome-authentik-profile}"
CHROME="${CHROME_BIN:-}"

if [[ -z "${CHROME}" ]]; then
  if command -v google-chrome >/dev/null 2>&1; then
    CHROME="$(command -v google-chrome)"
  elif command -v google-chrome-stable >/dev/null 2>&1; then
    CHROME="$(command -v google-chrome-stable)"
  else
    echo "error: google-chrome is not installed." >&2
    exit 1
  fi
fi

mkdir -p "${PROFILE}"
rm -f "${DOM}" "${OUT}"

echo "Rendering ${URL}"
# Headless Chrome can keep the DevTools port open after the screenshot is written.
export DBUS_SESSION_BUS_ADDRESS=/dev/null
set +e
timeout --signal=KILL 35 "${CHROME}" \
  --headless=new \
  --no-sandbox \
  --disable-gpu \
  --disable-dev-shm-usage \
  --no-first-run \
  --no-default-browser-check \
  --disable-extensions \
  --disable-background-networking \
  --user-data-dir="${PROFILE}" \
  --window-size=1440,900 \
  --virtual-time-budget=15000 \
  --timeout=30000 \
  --screenshot="${OUT}" \
  --dump-dom "${URL}" >"${DOM}" 2>/tmp/chrome-authentik.log
chrome_status=$?
set -e

if [[ ! -s "${OUT}" || ! -s "${DOM}" ]]; then
  echo "error: Chrome did not render the login page (exit ${chrome_status})." >&2
  exit 1
fi

if ! grep -q -- "--abyss-accent" "${DOM}"; then
  echo "error: rendered login page does not include the theme CSS." >&2
  exit 1
fi

echo "Login page includes the theme."
echo "Screenshot: ${OUT}"
echo "DOM: ${DOM}"
