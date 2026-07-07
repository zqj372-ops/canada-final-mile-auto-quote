#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

echo "### Hermes Daily Ops Snapshot"
date
echo

ops/hermes/scripts/check_health.sh
echo
ops/hermes/scripts/check_manual_tasks.sh
echo
ops/hermes/scripts/check_learning_candidates.sh
echo
ops/hermes/scripts/check_recent_errors.sh 80

