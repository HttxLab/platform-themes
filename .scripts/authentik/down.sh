#!/usr/bin/env bash
# Stop Authentik. Pass --volumes to delete the database so the next start bootstraps again.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ROOT}/authentik/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Authentik .env is absent; nothing to stop."
  exit 0
fi

args=(down --remove-orphans)
if [[ "${1:-}" == "--volumes" ]]; then
  args+=(--volumes)
fi

docker compose \
  --project-directory "${ROOT}/authentik" \
  --env-file "${ENV_FILE}" \
  -f "${ROOT}/authentik/compose.yml" \
  "${args[@]}"

if [[ "${1:-}" == "--volumes" ]]; then
  rm -rf "${ROOT}/authentik/data" "${ROOT}/authentik/certs" "${ROOT}/authentik/custom-templates"
  echo "Removed Authentik containers and database volume. authentik/.env was kept."
else
  echo "Stopped Authentik. The database volume is still present."
fi
