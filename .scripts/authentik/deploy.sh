#!/usr/bin/env bash
# Start Authentik if needed, publish authentik/style.css, then sign in.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
"${ROOT}/.scripts/authentik/up.sh"
python3 "${ROOT}/.scripts/authentik/api.py" deploy
echo "Theme deploy finished. Reload http://127.0.0.1:9000/if/flow/default-authentication-flow/"
