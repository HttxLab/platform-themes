#!/usr/bin/env bash
# Sign in as akadmin through the default authentication flow.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "${ROOT}/.scripts/authentik/api.py" login
