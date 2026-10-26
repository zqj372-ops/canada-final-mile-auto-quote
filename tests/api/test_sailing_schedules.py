import asyncio
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from apps.api.services import sailing_schedule as ss, schedule_dialogue as dialog
from apps.api.services.wecom_quote_worker import QuoteWorker, State, digest
from packages.ai_assistant.quote_extractor import AIExtractedQuoteDraft
from test_quote_workbench import context, counts
from test_wecom_quote_worker import FakeClient, frame


def fixture_result(carrier, status='success', records=1):
    # Disposable mocked source output; tests never query a carrier.
    record = {'record_id':'fixture','routing':'direct','legs':[{'mode':'ocean','vessel_name':'FIXTURE VESSEL',
        'voyage':'001E','events':[{'event_type':'departure','local_date':'2026-10-20'},
                                {'event_type':'arrival','local_date':'2026-11-10'}]}]}
    return {'carrier':carrier,'status':status,'source_url':ss.SOURCES[carrier],
            'data':{'run_status':'ok' if records else 'no_results','records':[deepcopy(record) for _ in range(records)],
            'coverage':{'complete':status=='success','truncated':False},
            'provenance':{'kind':'live','fetched_at':'2026-10-14T11:00:00Z'}},'blockers':[]}


@pytest.fixture
def collector(monkeypatch):
    calls=[]
    def collect(query,carrier):
        calls.append((query.model_dump(mode='json'),carrier))
        return fixture_result(carrier)
    monkeypatch.setattr(ss,'collect_carrier',collect)
    return calls


@pytest.mark.parametrize('fields',[
    {'departure_until':'2026-11-01'},
    {'departure_from':'2026-11-02','departure_until':'2026-11-01'},
    {'departure_from':'2026-10-01','departure_until':'2027-01-01'},
    {'departure_from':'2026-02-30'}, {'carriers':['ONE','ONE']}, {'carriers':['MSC']},
    {'source_url':'https://invalid.example'}, {'mode':'synthetic'}, {'origin_ids':{'ONE':'x; command'}},
])
def test_closed_contract_and_invalid_dates(fields):
    with pytest.raises(ValidationError): ss.ScheduleInput(**fields)


def test_missing_ports_defaults_and_ambiguous_country_no_network(collector):
    missing=ss.query_schedules(ss.ScheduleInput(),today=date(2026,10,14))
    assert missing.status=='needs_input' and missing.missing_fields==['origin','destination']
    assert missing.query.departure_until==date(2026,11,10)
    ambiguous=ss.query_schedules(ss.ScheduleInput(origin='上海',destination='温哥华'),today=date(2026,10,14))
    assert ambiguous.code=='schedule_country_ambiguous'
    assert {c['country_code'] for c in ambiguous.candidates}=={'CA','US'}
    assert collector==[]


@pytest.mark.parametrize('text,origin,destination,country',[
    ('上海到加拿大温哥华，下周船期','上海','温哥华','CA'),
    ('查船期，从宁波到洛杉矶下周','宁波','洛杉矶','US'),
    ('ONE Shanghai to Vancouver (CA) 下周船期','上海','温哥华','CA'),
    ('盐田至新西兰奥克兰，下周船期','盐田','奥克兰','NZ'),
])
def test_natural_route_week_and_carrier(text,origin,destination,country,collector):
    assert dialog.is_schedule_intent(text)
    reply,state=dialog.schedule_turn(text,today=date(2026,10,14))
    q=state['input']
    assert (q['origin'],q['destination'],q['destination_country'])==(origin,destination,country)
    assert q['departure_from']=='2026-10-19' and q['departure_until']=='2026-10-25'
    assert 'FIXTURE VESSEL' in reply and '舱位' in reply
    assert len(collector)==(1 if text.startswith('ONE') else 2)


def test_incremental_ports_country_selection_dates_carriers_and_resume(collector):
    _,state=dialog.schedule_turn('新船期查询',today=date(2026,10,14))
    _,state=dialog.schedule_turn('上海',state,today=date(2026,10,14))
    _,state=dialog.schedule_turn('温哥华',state,today=date(2026,10,14))
    assert state['candidates'] and collector==[]
    _,state=dialog.schedule_turn('加拿大',state,today=date(2026,10,14))
    assert state['input']['destination_country']=='CA' and len(collector)==2
    _,state=dialog.schedule_turn('下周呢',state,today=date(2026,10,14))
    assert state['input']['departure_from']=='2026-10-19'
    _,state=dialog.schedule_turn('只看ONE直达',state,today=date(2026,10,14))
    assert state['input']['carriers']==['ONE'] and state['input']['routing']=='direct'
    before=len(collector)
    reply,state2=dialog.schedule_turn('查船期',state,today=date(2026,10,14))
    assert reply==state['last_reply'] and state2==state and len(collector)==before
    _,state=dialog.schedule_turn('宁波出发',state,today=date(2026,10,14))
    assert state['input']['origin']=='宁波' and state['input']['destination']=='温哥华'
    reply,unchanged=dialog.schedule_turn('2月30日',state,today=date(2026,10,14))
    assert '无法识别' in reply and unchanged==state


@pytest.mark.parametrize('text,start,end',[
    ('10月20日至30日','2026-10-20','2026-10-30'),
    ('2026-10-20 至 2026-11-02','2026-10-20','2026-11-02'),
    ('下个月','2026-11-01','2026-11-30'),('10月','2026-10-01','2026-10-31'),
    ('下周五','2026-10-23','2026-10-23'),('下下周','2026-10-26','2026-11-01'),
    ('后天','2026-10-16','2026-10-16'),('next week','2026-10-19','2026-10-25'),
])
def test_date_windows(text,start,end):
    assert tuple(map(str,dialog._dates(text,date(2026,10,14))))==(start,end)


def test_unsupported_carrier_does_not_fall_back_or_call_source(collector):
    reply,_=dialog.schedule_turn('上海到加拿大温哥华的马士基船期')
    assert '尚未接入' in reply and not collector


@pytest.mark.parametrize('one,cosco,expected',[
    (('success',0),('success',0),'no_results'),
    (('success',1),('unavailable',0),'partial'),
    (('unavailable',0),('unavailable',0),'unavailable'),
    (('manual_review',1),('success',0),'partial'),
])
def test_source_failure_never_becomes_no_results(monkeypatch,one,cosco,expected):
    monkeypatch.setattr(ss,'collect_carrier',lambda q,c:fixture_result(c,*(one if c=='ONE' else cosco)))
    result=ss.query_schedules(ss.ScheduleInput(origin='上海',destination='洛杉矶'))
    assert result.status==expected
    if expected=='unavailable': assert '不能据此判断没有船期' in result.reply
    if one[0]=='manual_review': assert '待核对' in result.reply


def test_official_candidate_selection_is_carrier_specific(monkeypatch):
    seen=[]
    def collect(q,c):
        seen.append(q)
        if q.origin_ids.get('ONE')=='CNSHA01': return fixture_result(c)
        return {'carrier':c,'status':'needs_input','pending_side':'origin','data':{'candidates':[
            {'name':'SHANGHAI','country_code':'CN','type':'port','carrier_location_id':'CNSHA01'},
            {'name':'SHANGHAI TERMINAL','country_code':'CN','type':'terminal','carrier_location_id':'CNSHA02'}]}}
    monkeypatch.setattr(ss,'collect_carrier',collect)
    _,state=dialog.schedule_turn('ONE上海到洛杉矶下周船期',today=date(2026,10,14))
    assert state['candidates'] and len(seen)==1
    reply,state=dialog.schedule_turn('9',state)
    assert '序号' in reply and len(seen)==1
    reply,state=dialog.schedule_turn('1',state)
    assert 'FIXTURE VESSEL' in reply and seen[-1].origin_ids=={'ONE':'CNSHA01'}


def test_more_pages_reuses_result_without_carrier_request(monkeypatch):
    calls=[]
    def collect(q,c): calls.append(c);return fixture_result(c,records=7)
    monkeypatch.setattr(ss,'collect_carrier',collect)
    reply,state=dialog.schedule_turn('ONE上海到洛杉矶下周船期')
    assert '1—5 / 7' in reply
    reply,state=dialog.schedule_turn('更多船期',state)
    assert '6.' in reply and '7.' in reply and len(calls)==1


def test_worker_durable_isolation_dedup_and_other_drafts_preserved(tmp_path,collector):
    state=State(tmp_path/'worker');owner=digest('bot','owner')
    draft=AIExtractedQuoteDraft(piece_count=2,cbm=2).model_dump(mode='json')
    customs={'version':1,'active':True,'input':{'query':'杯子'},'pending':'material'}
    state.begin('seed',owner);state.finish('seed','seed',owner,'2箱2CBM',draft,customs=customs);state.sent('seed')
    def worker(): return QuoteWorker(bot_id='bot',allowed_users={'owner','second'},state=state,client=FakeClient(),quote=lambda *_:pytest.fail('schedule reached quote'))
    w=worker();event=frame('schedule','上海到加拿大温哥华下周船期')
    asyncio.run(w.process(event));count=len(collector)
    assert state.draft(owner)==draft and state.customs(owner)==customs
    assert state.schedule(owner) and state.schedule(digest('bot','second')) is None
    asyncio.run(w.process(event));assert len(collector)==count
    state.close();state=State(tmp_path/'worker');w=worker()
    try:
        asyncio.run(w.process(frame('date','10月20日至30日')))
        assert state.schedule(owner)['input']['departure_until']=='2026-10-30'
        asyncio.run(w.process(frame('kb','DDP和DAP有什么区别')))
        assert state.schedule(owner) and state.customs(owner)==customs and state.draft(owner)==draft
        asyncio.run(w.process(frame('custom','查关税')))
        assert state.schedule(owner) is None and state.schedule(owner,include_inactive=True)['input']['origin']=='上海'
        asyncio.run(w.process(frame('resume','返回船期')))
        assert state.schedule(owner)['input']['origin']=='上海'
        asyncio.run(w.process(frame('exit','返回报价')))
        assert state.schedule(owner) is None and state.customs(owner) is None and state.draft(owner)==draft
        with state.db:
            for table in ('sessions','customs_sessions','knowledge_sessions','schedule_sessions'):
                state.db.execute(f'UPDATE {table} SET updated=0 WHERE id=?',(owner,))
        assert state.schedule(owner,include_inactive=True) is None
    finally: state.close()


def test_api_permissions_contract_and_no_business_writes(context,collector,monkeypatch):
    client,factory=context;before=counts(factory)
    payload={'origin':'上海','destination':'洛杉矶','departure_from':'2026-10-19','departure_until':'2026-10-25'}
    response=client.post('/schedules/query',json=payload)
    assert response.status_code==200 and response.json()['status']=='answered'
    assert counts(factory)==before
    assert client.post('/schedules/query',json={**payload,'url':'http://localhost'}).status_code==422
    monkeypatch.setenv('DEV_AUTH_DISABLED','false')
    assert client.post('/schedules/query',json=payload).status_code==401


def test_cli_uses_same_api_private_session_and_carrier_ids(tmp_path,monkeypatch,capsys):
    import sys
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]/'scripts'))
    import schedules_query
    session=tmp_path/'session.json';session.write_text(json.dumps({'base_url':'https://fixture.invalid/api','credential':'fixture-secret'}));session.chmod(0o600)
    def request(url,path,**kwargs):
        assert path=='/schedules/query'
        assert kwargs['data']['carriers']==['ONE'] and kwargs['data']['origin_ids']=={'ONE':'CNSHA'}
        assert kwargs['data']['departure_from']=='2026-10-19'
        return {'status':'answered','reply':'fixture'}
    monkeypatch.setattr(schedules_query,'request',request)
    monkeypatch.setattr(sys,'argv',['schedules_query.py','--session',str(session),'--origin','上海','--destination','温哥华','--destination-country','CA','--carrier','ONE','--from','2026-10-19','--origin-id','ONE=CNSHA'])
    assert schedules_query.main()==0 and 'fixture-secret' not in capsys.readouterr().out


@pytest.mark.parametrize('fault',['nonlive','coverage','runtime','timeout'])
def test_subprocess_guard_failures_are_unavailable(monkeypatch,tmp_path,fault):
    monkeypatch.setenv('SCHEDULE_STATE_DIR',str(tmp_path))
    monkeypatch.setattr(ss.shutil,'which',lambda _: None if fault=='runtime' else '/fixture/node')
    def run(args,**kwargs):
        assert isinstance(args,list) and kwargs.get('shell') is None
        if fault=='timeout': raise ss.subprocess.TimeoutExpired(args,55)
        result=fixture_result('ONE')
        if fault=='nonlive': result['data']['provenance']['kind']='synthetic'
        if fault=='coverage': result['data']['coverage']['complete']=False
        kwargs['stdout'].write(json.dumps(result).encode())
    monkeypatch.setattr(ss.subprocess,'run',run)
    result=ss.collect_carrier(ss.ScheduleInput(origin='Shanghai',destination='Vancouver',departure_from='2026-10-19',departure_until='2026-10-25'),'ONE')
    assert result['status']=='unavailable' and result['data'] is None
