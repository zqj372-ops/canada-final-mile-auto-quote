#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

STATUS="${1:-pending}"
LIMIT="${2:-20}"

SAFE_STATUS="${STATUS//\'/''}"
SAFE_LIMIT="${LIMIT//[^0-9]/}"
if [[ -z "${SAFE_LIMIT}" ]]; then
  SAFE_LIMIT="20"
fi

WHERE_CLAUSE=""
if [[ "${SAFE_STATUS}" != "all" ]]; then
  WHERE_CLAUSE="where status = '${SAFE_STATUS}'"
fi

echo "== Hermes diagnostic queue (${SAFE_STATUS}, limit ${SAFE_LIMIT}) =="
db_query "
select
  id,
  quote_id,
  quote_status,
  source_type,
  status,
  suggested_action,
  confidence,
  recommend_manual_review,
  recommend_learning_candidate,
  learning_candidate_id,
  created_at
from hermes_diagnostic_queue
${WHERE_CLAUSE}
order by created_at desc, id desc
limit ${SAFE_LIMIT};
"

echo
echo "== Compact diagnostic packages =="
db_query "
select
  id,
  quote_id,
  diagnostic_package_json -> 'address' as address,
  diagnostic_package_json -> 'zone_hit' as zone_hit,
  diagnostic_package_json -> 'price_matrix' as price_matrix,
  diagnostic_package_json -> 'failure' as failure,
  jsonb_array_length(coalesce(diagnostic_package_json::jsonb -> 'neighboring_fsa', '[]'::jsonb)) as neighboring_fsa_count,
  jsonb_array_length(coalesce(diagnostic_package_json::jsonb -> 'historical_manual_confirmations', '[]'::jsonb)) as manual_history_count
from hermes_diagnostic_queue
${WHERE_CLAUSE}
order by created_at desc, id desc
limit ${SAFE_LIMIT};
"
