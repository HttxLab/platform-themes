#!/usr/bin/env bash
# Print akadmin's current 6-digit TOTP code. Does not print the secret.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
code="$(python3 "${ROOT}/.scripts/authentik/api.py" totp)"
echo "Current TOTP code for akadmin: ${code}"
