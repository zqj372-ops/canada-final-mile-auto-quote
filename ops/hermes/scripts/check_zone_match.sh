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
if [[ ! "${PREFIX}" =~ ^[A-Z][0-9][A-Z]([0-9][A-Z][0-9])?$ ]]; then
  echo "Postal prefix must be a 3-character FSA or a 6-character Canadian postal code." >&2
  exit 2
fi

FSA="${PREFIX:0:3}"
P2="${PREFIX:0:2}"
CITY_UPPER="$(echo "${CITY}" | tr '[:lower:]' '[:upper:]')"
PROVINCE_UPPER="$(echo "${PROVINCE}" | tr '[:lower:]' '[:upper:]')"

if (( ${#CITY_UPPER} > 100 )); then
  echo "City must be at most 100 characters." >&2
  exit 2
fi
if [[ -n "${PROVINCE_UPPER}" && ! "${PROVINCE_UPPER}" =~ ^[A-Z]{2}$ ]]; then
  echo "Province must be a 2-letter code." >&2
  exit 2
fi

echo "== Input =="
printf 'prefix=%s fsa=%s city=%s province=%s\n' "${PREFIX}" "${FSA}" "${CITY}" "${PROVINCE}"

echo
echo "== Preferred city lookup =="
db_query "
select postal_code, preferred_city, province
from postal_code_city_lookup
where upper(replace(postal_code, ' ', '')) like :'fsa' || '%'
order by postal_code
limit 20;
" -v "fsa=${FSA}"

echo
echo "== Exact FSA zone rules =="
db_query "
select postal_prefix, city, province, origin, zone
from zone_lookup_rules
where upper(postal_prefix) = :'fsa'
order by origin, zone, city
limit 50;
" -v "fsa=${FSA}"

echo
echo "== Same first-two prefix family =="
db_query "
select postal_prefix, city, province, origin, zone
from zone_lookup_rules
where upper(postal_prefix) like :'p2' || '%'
  and (:'province' = '' or upper(province) = :'province')
order by postal_prefix, origin, zone, city
limit 80;
" -v "p2=${P2}" -v "province=${PROVINCE_UPPER}"

if [[ -n "${CITY_UPPER}" || -n "${PROVINCE_UPPER}" ]]; then
  echo
  echo "== City/province zone rules =="
  db_query "
  select postal_prefix, city, province, origin, zone
  from zone_lookup_rules
  where (:'city' = '' or upper(city) like '%' || :'city' || '%')
    and (:'province' = '' or upper(province) = :'province')
  order by origin, zone, postal_prefix, city
  limit 100;
  " -v "city=${CITY_UPPER}" -v "province=${PROVINCE_UPPER}"
fi

echo
echo "== Active learned rules for this area =="
db_query "
select id, scope, quote_id, postal_code, postal_prefix, city, province, origin, zone, billing_pallets, total_price_usd, usage_count
from learned_quote_rules
where status = 'active'
  and (
    upper(coalesce(postal_code, '')) like :'fsa' || '%'
    or upper(coalesce(postal_prefix, '')) = :'fsa'
    or upper(coalesce(postal_prefix, '')) like :'p2' || '%'
    or (:'city' <> '' and upper(coalesce(city, '')) like '%' || :'city' || '%')
  )
order by usage_count desc, updated_at desc nulls last, id desc
limit 50;
" -v "fsa=${FSA}" -v "p2=${P2}" -v "city=${CITY_UPPER}"

echo
echo "== Price matrix coverage by origin/zone =="
db_query "
select origin, zone, min(billing_pallets) as min_pallets, max(billing_pallets) as max_pallets, count(*) as rows
from zone_price_matrix
group by origin, zone
order by origin, zone
limit 120;
"
