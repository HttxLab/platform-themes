#!/usr/bin/env bash
# Enable Remember me, Turnstile, a security key, and akadmin's TOTP device.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "${ROOT}/.scripts/authentik/api.py" configure
