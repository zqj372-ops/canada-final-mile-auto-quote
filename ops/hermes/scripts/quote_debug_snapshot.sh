#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

QUOTE_ID="${1:-}"
if [[ -z "${QUOTE_ID}" ]]; then
  echo "Usage: $0 <quote_id>" >&2
  exit 2
fi

SAFE_QUOTE_ID="${QUOTE_ID//\'/''}"

echo "== Audit log =="
db_query "
select
  id,
  quote_id,
  source_type,
  postal_code,
  postal_prefix,
  city,
  province,
  origin,
  zone,
  billing_pallets,
  base_price_usd,
  total_price_usd,
  manual_review_required,
  risk_tags,
  created_at
from quote_audit_logs
where quote_id = '${SAFE_QUOTE_ID}'
order by id desc;
"

echo
echo "== Manual task =="
db_query "
select
  id,
  quote_id,
  status,
  left(reason, 200) as reason,
  risk_tags,
  assigned_to,
  resolved_price_usd,
  left(coalesce(resolved_note, ''), 200) as resolved_note,
  created_at,
  updated_at
from manual_quote_tasks
where quote_id = '${SAFE_QUOTE_ID}'
order by id desc;
"

echo
echo "== Hermes diagnostic queue =="
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
  created_at,
  updated_at
from hermes_diagnostic_queue
where quote_id = '${SAFE_QUOTE_ID}'
order by id desc;
"

echo
echo "== Hermes diagnostic package, compact =="
db_query "
select
  diagnostic_package_json -> 'address' as address,
  diagnostic_package_json -> 'zone_hit' as zone_hit,
  diagnostic_package_json -> 'price_matrix' as price_matrix,
  diagnostic_package_json -> 'failure' as failure,
  diagnostic_package_json -> 'neighboring_fsa' as neighboring_fsa,
  diagnostic_package_json -> 'historical_manual_confirmations' as manual_history,
  agent_suggestion_json as agent_suggestion,
  agent_error
from hermes_diagnostic_queue
where quote_id = '${SAFE_QUOTE_ID}'
order by id desc
limit 1;
"

echo
echo "== Hermes candidate =="
db_query "
select
  id,
  status,
  source_task_id,
  quote_id,
  postal_code,
  postal_prefix,
  city,
  province,
  origin,
  zone,
  billing_pallets,
  resolved_total_price_usd,
  reviewed_by,
  reviewed_at,
  left(coalesce(review_note, ''), 200) as review_note
from hermes_learning_candidates
where quote_id = '${SAFE_QUOTE_ID}'
order by id desc;
"

echo
echo "== Learned rule =="
db_query "
select
  id,
  status,
  scope,
  quote_id,
  postal_code,
  postal_prefix,
  city,
  province,
  origin,
  zone,
  billing_pallets,
  total_price_usd,
  usage_count,
  last_used_at
from learned_quote_rules
where quote_id = '${SAFE_QUOTE_ID}'
order by id desc;
"

echo
echo "== Request/result JSON, compact =="
db_query "
select
  jsonb_pretty(to_jsonb(request_json)) as request_json,
  jsonb_pretty(to_jsonb(result_json)) as result_json
from quote_audit_logs
where quote_id = '${SAFE_QUOTE_ID}'
order by id desc
limit 1;
"
