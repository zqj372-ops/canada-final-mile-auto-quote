#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

HERMES_PUBLIC_URL="${HERMES_PUBLIC_URL:-https://quote.freightclaw.net}"
HERMES_COMPOSE_PROJECT="${HERMES_COMPOSE_PROJECT:-canada_quote_oracle}"
HERMES_COMPOSE_FILE="${HERMES_COMPOSE_FILE:-infra/docker-compose.prod.yml}"
HERMES_ENV_FILE="${HERMES_ENV_FILE:-.env.prod}"

cd "${HERMES_ROOT}"

docker_cmd() {
  if docker ps >/dev/null 2>&1; then
    docker "$@"
    return
  fi
  if sudo -n docker ps >/dev/null 2>&1; then
    sudo -n docker "$@"
    return
  fi
  echo "Docker is not accessible. Add this user to the docker group or allow passwordless sudo for docker." >&2
  return 1
}

compose() {
  docker_cmd compose \
    -p "${HERMES_COMPOSE_PROJECT}" \
    --env-file "${HERMES_ENV_FILE}" \
    -f "${HERMES_COMPOSE_FILE}" \
    "$@"
}

db_query() {
  local sql="$1"
  shift
  {
    printf 'begin read only;\n'
    printf '%s\n' "${sql}"
    printf 'rollback;\n'
  } | compose exec -T postgres sh -c \
    'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' \
    sh "$@"
}
