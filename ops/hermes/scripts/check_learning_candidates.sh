#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

echo "== Hermes learning candidate summary =="
db_query "
select status, count(*) as count
from hermes_learning_candidates
group by status
order by status;
"

echo
echo "== Recent learning candidates =="
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
  billing_pallets,
  confirmed_total_price_usd,
  updated_at
from hermes_learning_candidates
order by updated_at desc nulls last, id desc
limit 20;
"

echo
echo "== Active learned rules =="
db_query "
select
  id,
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
where status = 'active'
order by usage_count desc, updated_at desc nulls last, id desc
limit 20;
"

