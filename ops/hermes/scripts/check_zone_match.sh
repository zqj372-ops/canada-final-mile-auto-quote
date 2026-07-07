#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

PREFIX="${1:-}"
CITY="${2:-}"
PROVINCE="${3:-}"

if [[ -z "${PREFIX}" ]]; then
  echo "Usage: $0 <postal_prefix_or_postal_code> [city] [province]" >&2
  exit 2
fi

PREFIX="$(echo "${PREFIX}" | tr '[:lower:]' '[:upper:]' | tr -d ' ')"
FSA="${PREFIX:0:3}"
P2="${PREFIX:0:2}"
P1="${PREFIX:0:1}"
CITY_UPPER="$(echo "${CITY}" | tr '[:lower:]' '[:upper:]')"
PROVINCE_UPPER="$(echo "${PROVINCE}" | tr '[:lower:]' '[:upper:]')"

echo "== Input =="
printf 'prefix=%s fsa=%s city=%s province=%s\n' "${PREFIX}" "${FSA}" "${CITY}" "${PROVINCE}"

echo
echo "== Preferred city lookup =="
db_query "
select postal_code, city, province
from postal_code_city_lookup
where upper(replace(postal_code, ' ', '')) like '${FSA}%'
order by postal_code
limit 20;
"

echo
echo "== Exact FSA zone rules =="
db_query "
select postal_prefix, city, province, origin, zone
from zone_lookup_rules
where upper(postal_prefix) = '${FSA}'
order by origin, zone, city
limit 50;
"

echo
echo "== Same first-two prefix family =="
db_query "
select postal_prefix, city, province, origin, zone
from zone_lookup_rules
where upper(postal_prefix) like '${P2}%'
  and ('${PROVINCE_UPPER}' = '' or upper(province) = '${PROVINCE_UPPER}')
order by postal_prefix, origin, zone, city
limit 80;
"

if [[ -n "${CITY_UPPER}" || -n "${PROVINCE_UPPER}" ]]; then
  echo
  echo "== City/province zone rules =="
  db_query "
  select postal_prefix, city, province, origin, zone
  from zone_lookup_rules
  where ('${CITY_UPPER}' = '' or upper(city) like '%' || '${CITY_UPPER}' || '%')
    and ('${PROVINCE_UPPER}' = '' or upper(province) = '${PROVINCE_UPPER}')
  order by origin, zone, postal_prefix, city
  limit 100;
  "
fi

echo
echo "== Active learned rules for this area =="
db_query "
select id, scope, quote_id, postal_code, postal_prefix, city, province, origin, zone, billing_pallets, total_price_usd, usage_count
from learned_quote_rules
where status = 'active'
  and (
    upper(coalesce(postal_code, '')) like '${FSA}%'
    or upper(coalesce(postal_prefix, '')) = '${FSA}'
    or upper(coalesce(postal_prefix, '')) like '${P2}%'
    or ('${CITY_UPPER}' <> '' and upper(coalesce(city, '')) like '%' || '${CITY_UPPER}' || '%')
  )
order by usage_count desc, updated_at desc nulls last, id desc
limit 50;
"

echo
echo "== Price matrix coverage by origin/zone =="
db_query "
select origin, zone, min(billing_pallets) as min_pallets, max(billing_pallets) as max_pallets, count(*) as rows
from zone_price_matrix
group by origin, zone
order by origin, zone
limit 120;
"

