#!/usr/bin/env bash
# Code -> deploy loop: ensure Authentik is up, publish authentik/style.css, then log in.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"${ROOT}/scripts/authentik-up.sh"
python3 "${ROOT}/scripts/authentik_ctl.py" deploy
echo "Theme deploy finished. Reload http://127.0.0.1:9000/if/flow/default-authentication-flow/"
