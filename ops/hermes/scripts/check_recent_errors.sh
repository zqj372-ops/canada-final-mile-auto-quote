#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

LINES="${1:-120}"

echo "== API logs, last ${LINES} lines =="
compose logs --tail "${LINES}" api \
  | sed -E 's/(sk-[A-Za-z0-9_-]{8,})/<redacted>/g; s/(Bearer )[A-Za-z0-9._-]+/\1<redacted>/g'

echo
echo "== Recent manual_required audit samples =="
db_query "
select
  quote_id,
  source_type,
  postal_prefix,
  city,
  province,
  origin,
  zone,
  billing_pallets,
  manual_review_required,
  left(coalesce(result_json->>'matched_rule', ''), 180) as matched_rule,
  created_at
from quote_audit_logs
where manual_review_required is true
order by created_at desc, id desc
limit 20;
"

