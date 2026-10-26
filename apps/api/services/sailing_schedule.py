"""Read-only public carrier schedules shared by API, CLI and WeCom.

The pinned collector owns official location resolution, source schema checks,
evidence, coverage and transport restrictions. This adapter never books cargo.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[3] / 'packages/schedule_collector'
SOURCES = {'ONE': 'https://ecomm.one-line.com/one-ecom/schedule/point-to-point-schedule',
           'COSCO': 'https://elines.coscoshipping.com/ebusiness/sailingSchedule/searchByCity'}
_SLOTS = threading.BoundedSemaphore(4)


class ScheduleInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    origin: str | None = Field(default=None, min_length=1, max_length=100)
    destination: str | None = Field(default=None, min_length=1, max_length=100)
    origin_country: str | None = Field(default=None, pattern=r'^[A-Z]{2}$')
    destination_country: str | None = Field(default=None, pattern=r'^[A-Z]{2}$')
    departure_from: date | None = None
    departure_until: date | None = None
    carriers: list[Literal['ONE', 'COSCO']] = Field(default_factory=lambda: ['ONE', 'COSCO'], min_length=1, max_length=2)
    routing: Literal['any', 'direct', 'transshipment'] = 'any'
    # IDs are carrier-specific and are checked again against official candidates.
    origin_ids: dict[Literal['ONE', 'COSCO'], str] = Field(default_factory=dict)
    destination_ids: dict[Literal['ONE', 'COSCO'], str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def dates_and_ids(self):
        if len(set(self.carriers)) != len(self.carriers):
            raise ValueError('duplicate carrier')
        if self.departure_until and not self.departure_from:
            raise ValueError('departure_from required with departure_until')
        if self.departure_from and self.departure_until:
            days = (self.departure_until - self.departure_from).days
            if not 0 <= days <= 89:
                raise ValueError('departure window must be 1 to 90 days')
        import re
        for value in [*self.origin_ids.values(), *self.destination_ids.values()]:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}', value):
                raise ValueError('invalid carrier location ID')
        return self


class ScheduleResponse(BaseModel):
    status: Literal['needs_input', 'answered', 'partial', 'no_results', 'unavailable']
    code: str
    reply: str
    query: ScheduleInput
    results: list[dict] = Field(default_factory=list)
    candidates: list[dict] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


def today_local():
    return datetime.now(ZoneInfo('Asia/Shanghai')).date()


def port_names():
    ports = json.loads((ROOT / 'port_names.json').read_text())
    aliases = {'Los Angeles': ['LA'], 'Long Beach': ['LB'], 'Vancouver': ['温港'],
               'Shanghai': ['CNSHA'], 'Prince Rupert': ['王子港']}
    for port in ports:
        port['aliases'] += aliases.get(port['en'], [])
    return ports


def match_ports(text, country=None):
    """Known aliases resolve exactly; approximate matches only suggest choices."""
    normalize = lambda s: re.sub(r'[\s.,，。()（）-]', '', s).casefold()
    query = normalize(text)
    ports = [p for p in port_names() if not country or p['country'] == country]
    exact = [p for p in ports if query in [normalize(v) for v in [p['zh'],p['en'],*p['aliases']]]]
    if exact:
        return 'exact', exact
    ranked = []
    for port in ports:
        score = 0
        for name in [port['zh'],port['en'],*port['aliases']]:
            name = normalize(name)
            if min(len(query),len(name)) < 2:
                continue
            ratio = SequenceMatcher(None,query,name).ratio()
            threshold = .66 if not query.isascii() else .72
            if len(query) >= 3 and (name.startswith(query) or ratio >= threshold):
                score = max(score,ratio)
            elif len(query) == 2 and not query.isascii() and name.startswith(query):
                score = max(score,.8)
            elif len(query) == len(name) == 2 and not query.isascii() and query[0] == name[0]:
                score = max(score,.5)
        if score:
            ranked.append((score,port))
    ranked.sort(key=lambda v:-v[0])
    return 'suggestion', [p for _,p in ranked[:6]]


def _failure(carrier, code):
    return {'carrier': carrier, 'status': 'unavailable', 'data': None, 'blockers': [{'code': code}], 'source_url': SOURCES[carrier]}


def collect_carrier(query: ScheduleInput, carrier: str) -> dict:
    node = shutil.which('node')
    if not node:
        return _failure(carrier, 'runtime_unavailable')
    try:
        manifest = json.loads((ROOT / 'manifest.json').read_text())
        if hashlib.sha256((ROOT / 'collector.mjs').read_bytes()).hexdigest() != manifest['bundle_sha256']:
            return _failure(carrier, 'collector_integrity_failed')
    except (OSError, ValueError, KeyError):
        return _failure(carrier, 'collector_integrity_failed')
    if not _SLOTS.acquire(timeout=1):
        return _failure(carrier, 'collector_busy')
    try:
        work = Path(os.getenv('SCHEDULE_STATE_DIR', 'outputs/schedules')).resolve() / uuid4().hex
        work.mkdir(mode=0o700, parents=True)
        payload = {'carrier': carrier, 'origin': {'text':query.origin, 'country_code':query.origin_country,
                   'carrier_location_id':query.origin_ids.get(carrier)},
                   'destination': {'text':query.destination, 'country_code':query.destination_country,
                   'carrier_location_id':query.destination_ids.get(carrier)},
                   'from':str(query.departure_from), 'until':str(query.departure_until), 'routing':query.routing}
        with tempfile.TemporaryFile() as output:
            subprocess.run([node, '--max-old-space-size=128', str(ROOT / 'collector.mjs')],
                input=json.dumps(payload).encode(), stdout=output, stderr=subprocess.DEVNULL,
                cwd=work, timeout=55, check=False)
            if output.tell() > 8 * 1024 * 1024:
                return _failure(carrier, 'collector_output_too_large')
            output.seek(0)
            result = json.load(output)
        if not isinstance(result, dict) or result.get('status') not in {'success','needs_input','manual_review','blocked','unavailable'}:
            return _failure(carrier, 'collector_response_invalid')
        data = result.get('data') or {}
        if 'records' in data and (data.get('provenance', {}).get('kind') != 'live'
                or not data.get('provenance', {}).get('fetched_at')):
            return _failure(carrier, 'non_live_data_rejected')
        if result['status'] == 'success' and ('records' not in data or data.get('run_status') not in {'ok','no_results'}
                or not data.get('coverage', {}).get('complete') or data.get('coverage', {}).get('truncated')):
            return _failure(carrier, 'collector_coverage_invalid')
        result.update(carrier=carrier, source_url=SOURCES[carrier])
        (work / 'result.json').write_text(json.dumps(result, ensure_ascii=False))
        os.chmod(work / 'result.json', 0o600)
        return result
    except subprocess.TimeoutExpired:
        return _failure(carrier, 'collector_timeout')
    except (OSError, ValueError, KeyError, TypeError):
        return _failure(carrier, 'collector_failed')
    finally:
        _SLOTS.release()


def _event(leg, kind):
    event = next((v for v in leg.get('events', []) if v.get('event_type') == kind), {})
    value = event.get('local_datetime') or event.get('local_date') or event.get('utc_datetime')
    if not value:
        return '来源未提供'
    suffix = ' UTC' if not event.get('local_datetime') and not event.get('local_date') and event.get('utc_datetime') else ''
    return value.replace('T', ' ') + suffix


def record_line(record, carrier=None):
    legs = record.get('legs', [])
    ocean = [leg for leg in legs if leg.get('mode') == 'ocean']
    if not ocean:
        return '缺少海运分段，需人工核对。'
    first, last = ocean[0], ocean[-1]
    route = {'direct':'直达','transshipment':'中转','unknown':'中转情况未确认'}.get(record.get('routing'),'中转情况未确认')
    ships = ' → '.join(f"{leg.get('vessel_name') or '船名未提供'} / {leg.get('voyage') or '航次未提供'}" for leg in ocean)
    # ONE's journey arrival value is berthingDate, not sailInfo.arrivalDate.
    # Keep that distinction visible instead of silently calling it port ETA.
    arrival_label = '预计靠泊' if carrier == 'ONE' else '预计到港'
    text = f"{ships}；{route}\n  预计离港 {_event(first,'departure')}；{arrival_label} {_event(last,'arrival')}"
    if any(leg.get('mode') != 'ocean' for leg in legs):
        text += f"；后续含内陆段，预计到达查询目的地 {_event(legs[-1],'arrival')}"
    return text


def render_results(query, results, *, offset=0, page_size=5):
    lines = [f"{query.origin} → {query.destination}，出发日期 {query.departure_from} 至 {query.departure_until}。",
             '查询船公司：' + '、'.join(query.carriers) + '。']
    rows = []
    for result in results:
        carrier, data = result['carrier'], result.get('data') or {}
        records = data.get('records', [])
        if result['status'] == 'success' and data.get('run_status') == 'no_results':
            lines.append(f'{carrier}：该日期范围内没有匹配航次。')
        elif result['status'] == 'success':
            lines.append(f'{carrier}：取得 {len(records)} 个船期方案。')
        elif result['status'] == 'manual_review' and records:
            lines.append(f'{carrier}：取得 {len(records)} 个候选方案，但覆盖或来源信息有疑点，需要人工核对。')
        elif result['status'] == 'needs_input':
            lines.append(f'{carrier}：港口匹配需要补充或确认，暂未取得船期。')
        else:
            code = next((v.get('code') for v in result.get('blockers', [])), '')
            reason = {'collector_busy':'当前查询较多','collector_timeout':'船公司查询超时',
                      'timeout':'船公司查询超时','access_restricted':'船公司访问受限',
                      'schema_changed':'船公司返回格式发生变化','runtime_unavailable':'查询运行环境未就绪'}.get(code,'船公司查询暂时失败')
            lines.append(f'{carrier}：{reason}，请稍后重试；不能据此判断没有船期。')
        for record in records:
            first = next((v for v in record.get('legs', []) if v.get('mode') == 'ocean'), {})
            rows.append((_event(first, 'departure'), carrier, record, result['status'] != 'success'))
        fetched = data.get('provenance', {}).get('fetched_at')
        if fetched:
            lines.append(f'{carrier} 查询时间：{fetched}。')
    rows.sort(key=lambda row:(row[0], row[1]))
    for i, (_, carrier, record, review) in enumerate(rows[offset:offset+page_size], offset+1):
        lines.append(f"{i}. {carrier}{'（待核对）' if review else ''}：{record_line(record,carrier)}")
    if len(rows) > offset + page_size:
        lines.append(f'当前展示 {offset+1}—{min(offset+page_size,len(rows))} / {len(rows)} 个方案，发送“更多船期”查看后续方案。')
    elif offset and not rows[offset:]:
        lines.append('已经展示完所有方案，可修改日期或发送“刷新船期”。')
    lines.append('来源：' + '；'.join(f'{c} {SOURCES[c]}' for c in query.carriers))
    if rows:
        lines.append('时间保留来源精度；未注明时区时不作换算。ONE 为 CY/CY 普货查询。船期可能调整，查询结果不代表有舱位。')
    return '\n'.join(lines)


def query_schedules(payload: ScheduleInput, *, today=None) -> ScheduleResponse:
    values = payload.model_dump()
    start = payload.departure_from or today or today_local()
    values.update(departure_from=start, departure_until=payload.departure_until or start+timedelta(days=27))
    query = ScheduleInput(**values)
    missing = [field for field in ('origin','destination') if not getattr(query,field)]
    if missing:
        names = {'origin':'起运港','destination':'目的港'}
        return ScheduleResponse(status='needs_input',code='schedule_missing_ports',query=query,missing_fields=missing,
            reply='想查从哪里到哪里？请补充'+'、'.join(names[v] for v in missing)+'，例如“上海到加拿大温哥华，下周”。未指定日期时查未来四周，默认查询 ONE 和 COSCO。')
    # Normalize aliases once for all callers; fuzzy names require confirmation.
    for side in ('origin','destination'):
        text, country = getattr(query,side), getattr(query,side+'_country')
        kind, matches = match_ports(text,country)
        if matches and (kind == 'suggestion' or len(matches) > 1):
            candidates = [{'side':side,'name':p['en'],'country_code':p['country'],'text':p['zh']} for p in matches]
            prefix = f'“{text}”可能是以下港口，请确认：' if kind == 'suggestion' else f'{text}有同名地点，请确认国家：'
            return ScheduleResponse(status='needs_input',code='schedule_port_suggestion' if kind == 'suggestion' else 'schedule_country_ambiguous',query=query,candidates=candidates,
                reply=prefix+'\n'+'\n'.join(f"{i+1}. {p['zh']} / {p['en']}（{p['country']}）" for i,p in enumerate(matches))+'\n可回复序号、完整港口名称，或发送“船期菜单”。')
        if kind == 'exact' and len(matches) == 1:
            values[side],values[side+'_country'] = matches[0]['zh'],matches[0]['country']
            query = ScheduleInput(**values)
    with ThreadPoolExecutor(max_workers=len(query.carriers)) as pool:
        results = list(pool.map(lambda carrier:collect_carrier(query,carrier),query.carriers))
    candidates = []
    for result in results:
        if result['status'] == 'needs_input':
            for candidate in (result.get('data') or {}).get('candidates', []):
                candidates.append({**candidate,'side':result.get('pending_side'),'carrier':result['carrier']})
    successes = sum(r['status']=='success' for r in results)
    if successes == len(results):
        status = 'answered' if any((r.get('data') or {}).get('records') for r in results) else 'no_results'
    elif any((r.get('data') or {}).get('records') for r in results) or successes:
        status = 'partial'
    elif any(r['status']=='needs_input' for r in results):
        status = 'needs_input'
    else:
        status = 'unavailable'
    reply = render_results(query,results)
    if candidates:
        reply += '\n请确认港口（可回复序号）：\n'+'\n'.join(f"{i+1}. {c['carrier']} {c['name']}（{c.get('country_code') or '国家未标注'}；{c.get('type','unknown')}）" for i,c in enumerate(candidates[:12]))
    elif status == 'needs_input':
        reply += '\n请补充更准确的港口名称和国家，例如“目的港加拿大温哥华”。'
    return ScheduleResponse(status=status,code='schedule_'+status,reply=reply,query=query,results=results,candidates=candidates)
