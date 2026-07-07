#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

echo "== API health =="
curl -fsS "${HERMES_PUBLIC_URL%/}/api/health"
echo

echo "== Docker services =="
compose ps

echo
echo "== DB table counts =="
db_query "
select 'postal_code_city_lookup' as table_name, count(*) from postal_code_city_lookup
union all select 'zone_lookup_rules', count(*) from zone_lookup_rules
union all select 'zone_price_matrix', count(*) from zone_price_matrix
union all select 'quote_audit_logs', count(*) from quote_audit_logs
union all select 'manual_quote_tasks', count(*) from manual_quote_tasks
union all select 'learned_quote_rules', count(*) from learned_quote_rules
union all select 'hermes_learning_candidates', count(*) from hermes_learning_candidates;
"

