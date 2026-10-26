#!/usr/bin/env bash
# Start local Authentik and wait until the default brand exists.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ROOT}/authentik/.env"
COMPOSE=(
  docker compose
  --project-directory "${ROOT}/authentik"
  --env-file "${ENV_FILE}"
  -f "${ROOT}/authentik/compose.yml"
)

generate_env() {
  # Hex only, so Compose does not treat a character in the secret as interpolation.
  umask 077
  cat >"${ENV_FILE}" <<EOF
PG_PASS=$(openssl rand -hex 24)
PG_DB=authentik
PG_USER=authentik
AUTHENTIK_SECRET_KEY=$(openssl rand -hex 48)
AUTHENTIK_BOOTSTRAP_PASSWORD=$(openssl rand -hex 18)
AUTHENTIK_BOOTSTRAP_TOKEN=$(openssl rand -hex 32)
AUTHENTIK_BOOTSTRAP_EMAIL=akadmin@example.com
AUTHENTIK_TAG=2026.8.5
AUTHENTIK_ERROR_REPORTING__ENABLED=false
COMPOSE_PORT_HTTP=9000
COMPOSE_PORT_HTTPS=9443
EOF
  chmod 600 "${ENV_FILE}"
  echo "Generated ${ENV_FILE}. The akadmin password and API token are in that file."
}

if ! docker info >/dev/null 2>&1; then
  echo "error: Docker is not running. Start Docker, then run this again." >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  generate_env
fi

mkdir -p "${ROOT}/authentik/data" "${ROOT}/authentik/certs" "${ROOT}/authentik/custom-templates"

echo "Starting Authentik (postgres, server, worker)..."
"${COMPOSE[@]}" up -d --remove-orphans --quiet-pull
python3 "${ROOT}/.scripts/authentik/api.py" wait --timeout 240
echo "Authentik UI: http://127.0.0.1:9000/if/flow/default-authentication-flow/"
echo "Admin user: akadmin. Password: authentik/.env key AUTHENTIK_BOOTSTRAP_PASSWORD."
