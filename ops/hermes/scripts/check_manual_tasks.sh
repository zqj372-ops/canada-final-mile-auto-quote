#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

echo "== Manual task summary =="
db_query "
select status, count(*) as count
from manual_quote_tasks
group by status
order by status;
"

echo
echo "== Recent manual tasks =="
db_query "
select
  id,
  quote_id,
  status,
  left(reason, 120) as reason,
  assigned_to,
  resolved_price_usd,
  created_at,
  updated_at
from manual_quote_tasks
order by updated_at desc nulls last, id desc
limit 20;
"

echo
echo "== Pending tasks by reason =="
db_query "
select left(reason, 140) as reason, count(*) as count
from manual_quote_tasks
where status = 'pending'
group by left(reason, 140)
order by count desc, reason
limit 20;
"

