"""Deterministic, incremental schedule conversation; no shipment data changes."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from difflib import SequenceMatcher
import re
import unicodedata

from pydantic import ValidationError

from apps.api.services.sailing_schedule import ScheduleInput, port_names, match_ports, query_schedules, render_results, today_local

HELP = '可以直接说“上海到加拿大温哥华，下周船期”，也可以发送“船期菜单”按序号选择。目前查询 ONE 和 COSCO，未指定日期查未来四周。'
COUNTRIES = {'中国':'CN','加拿大':'CA','美国':'US','新西兰':'NZ','澳大利亚':'AU','日本':'JP','韩国':'KR','新加坡':'SG','荷兰':'NL','德国':'DE','英国':'GB','法国':'FR','香港':'HK'}
CARRIER_PATTERN = r'(?<![A-Za-z])(?:ONE|COSCO)(?![A-Za-z])|中远海运|中远|海洋网联'


def _carrier_typo(text):
    # Approximate carrier names require confirmation; never silently select one.
    for match in re.finditer(r'(?<![A-Za-z])[A-Za-z]{4,6}(?![A-Za-z])',text):
        token=match[0].upper()
        if token != 'COSCO' and SequenceMatcher(None,token,'COSCO').ratio() >= .8:
            return match[0]
    return None


def _carrier_prompt(state):
    raw=state['carrier_candidates'][0]['text']
    values=state.get('input',{})
    route=f"已保留路线：{values.get('origin') or '待填写'} → {values.get('destination') or '待填写'}。\n"
    return (f'“{raw}”不是已识别的船公司名称，你是指 COSCO（中远海运）吗？\n'+route+
            '回复“1”或“COSCO”确认，也可改为“ONE”，或发送“船期菜单”重新选择。确认前不会查询。')


def _text(text):
    text = unicodedata.normalize('NFKC', text).strip()
    for old,new in [('下个礼拜','下周'),('下礼拜','下周'),('下星期','下周'),('这个礼拜','本周'),('这星期','本周'),('本星期','本周')]:
        text = text.replace(old,new)
    return text


MENU_STEPS = ('origin','destination','dates','carriers','routing','confirm')
PORT_MENUS = {
    'origin': [('上海','CN'),('宁波','CN'),('盐田','CN'),('蛇口','CN'),('青岛','CN'),('厦门','CN')],
    'destination': [('温哥华','CA'),('鲁珀特王子港','CA'),('蒙特利尔','CA'),('哈利法克斯','CA'),('洛杉矶','US'),('长滩','US')],
}


def _menu_prompt(state):
    step,values = state['menu'],state.get('input',{})
    heading = f'船期菜单 {MENU_STEPS.index(step)+1}/6'
    if step in PORT_MENUS:
        label = '起运港' if step == 'origin' else '目的港'
        options = [(p['zh'],p['country']) for p in state.get('menu_candidates',[])] or PORT_MENUS[step]
        content = f'请选择{label}，也可直接输入港口名称：\n'+'\n'.join(
            f'{i}. {name}（{country}）' for i,(name,country) in enumerate(options,1))
        if not state.get('menu_candidates'):
            content += '\n7. 其他港口（手动输入，查询时由船公司核对）'
    elif step == 'dates':
        content = '选择出发日期：\n1. 未来四周\n2. 下周\n3. 下个月\n也可输入“10月20日至30日”或“2026-10-20 至 2026-10-30”。'
    elif step == 'carriers':
        content = '选择船公司：\n1. ONE 和 COSCO\n2. ONE\n3. COSCO'
    elif step == 'routing':
        content = '选择航线：\n1. 不限直达/中转\n2. 只看直达\n3. 只看中转'
    else:
        routing = {'any':'不限直达/中转','direct':'只看直达','transshipment':'只看中转'}[values.get('routing','any')]
        content = (f"请核对：{values.get('origin')}（{values.get('origin_country') or '待船公司确认'}） → "
                   f"{values.get('destination')}（{values.get('destination_country') or '待船公司确认'}）\n"
                   f"出发日期：{values.get('departure_from')} 至 {values.get('departure_until')}\n"
                   f"船公司：{'、'.join(values.get('carriers',['ONE','COSCO']))}；{routing}\n"
                   '1. 开始查询\n2. 修改起运港\n3. 修改目的港\n4. 修改日期\n5. 修改船公司\n6. 修改航线')
    return heading+'\n'+content+'\n回复序号即可；可发送“上一步”“取消船期菜单”或“返回报价”。'


def _menu_turn(text,state,today):
    """Only the currently shown menu owns a bare number. No lookup until confirm."""
    if text in {'船期菜单','菜单查船期','菜单'}:
        state['menu']='origin'
        state.pop('candidates',None)
        state.pop('carrier_candidates',None)
        state.pop('menu_candidates',None)
        state.pop('menu_freeform',None)
        return _menu_prompt(state),state
    if text == '取消船期菜单':
        state.pop('menu',None);state.pop('menu_candidates',None);state.pop('menu_freeform',None)
        return '已退出船期菜单，已填资料保留。可以直接描述查询条件，或发送“返回报价”。',state
    if 'menu' not in state:
        return None
    if text == '返回船期':
        return _menu_prompt(state),state
    step,values=state['menu'],deepcopy(state.get('input',{}))
    if text in {'上一步','返回上一步'}:
        state['menu']=MENU_STEPS[max(0,MENU_STEPS.index(step)-1)]
        state.pop('menu_candidates',None)
        state.pop('menu_freeform',None)
        return _menu_prompt(state),state
    number = re.fullmatch(r'(?:第)?([1-9])(?:个|项)?[。.!！]?',text)
    choice = int(number[1]) if number else None
    if step in PORT_MENUS:
        pending=state.get('menu_candidates')
        if choice==7 and not pending:
            state['menu_freeform']=True
            return '请输入完整港口名称，例如“Rotterdam”或“荷兰鹿特丹”。最终以船公司官方匹配为准。',state
        options=pending or [{'zh':name,'country':country} for name,country in PORT_MENUS[step]]
        port=options[choice-1] if choice and choice<=len(options) else None
        if not choice:
            country_choice=COUNTRIES.get(text,text.upper() if text.upper() in COUNTRIES.values() else None)
            scoped=[p for p in (pending or []) if p['country']==country_choice]
            if len(scoped)==1:
                port=scoped[0]
            supplied_country=next((code for name,code in COUNTRIES.items() if text.startswith(name)),None)
            name=text
            if supplied_country:
                name=next(text[len(k):].strip() for k,v in COUNTRIES.items() if v==supplied_country and text.startswith(k))
            kind,matches=match_ports(name,supplied_country)
            if kind=='exact' and len(matches)==1:
                port=matches[0]
            elif matches and port is None:
                state['menu_candidates']=matches
                return '这个名称需要确认，请选择：\n'+'\n'.join(f"{i}. {p['zh']}（{p['country']}）" for i,p in enumerate(matches,1))+'\n也可输入完整港口名称，或发送“上一步”。',state
            if port is None and state.get('menu_freeform') and re.fullmatch(r"[A-Za-z\u4e00-\u9fff .'-]{2,80}",name):
                port={'zh':name,'country':supplied_country}
        if not port:
            return '暂未识别这个港口，请用完整中英文名称或选择列表中的序号。\n'+_menu_prompt(state),state
        values[step],values[step+'_country']=port['zh'],port['country']
        values[step+'_ids']={}
        state.pop('menu_candidates',None)
        state.pop('menu_freeform',None)
    elif step=='dates':
        try:
            dates=_dates({1:'未来四周',2:'下周',3:'下个月'}.get(choice,text),today)
            if not dates or not 0<=(dates[1]-dates[0]).days<=89: raise ValueError()
        except ValueError:
            return '没有识别到有效日期，单次范围为1—90天。\n'+_menu_prompt(state),state
        values['departure_from'],values['departure_until']=map(str,dates)
    elif step=='carriers':
        selected={1:['ONE','COSCO'],2:['ONE'],3:['COSCO']}.get(choice)
        if selected is None:
            selected=['ONE','COSCO'] if text in {'两家','全部','都查'} else ['ONE'] if text.upper()=='ONE' else ['COSCO'] if text.upper() in {'COSCO','中远','中远海运'} else None
        if not selected:
            suggestion=f'“{text}”可能是 COSCO（中远海运），请回复“COSCO”或序号3确认。\n' if _carrier_typo(text) else ''
            return suggestion+'请选择已接入的船公司。\n'+_menu_prompt(state),state
        values['carriers']=selected
    elif step=='routing':
        routing={1:'any',2:'direct',3:'transshipment'}.get(choice) or {'不限':'any','都可以':'any','直达':'direct','直航':'direct','中转':'transshipment'}.get(text)
        if not routing: return '请选择航线类型。\n'+_menu_prompt(state),state
        values['routing']=routing
    else:
        if choice in {2,3,4,5,6}:
            state['menu']=MENU_STEPS[choice-2]
            return _menu_prompt(state),state
        if choice==1 or text in {'开始查询','确认查询','确认'}:
            result=query_schedules(ScheduleInput(**values),today=today)
            state.pop('menu',None)
            state.update(input=result.query.model_dump(mode='json'),last_reply=result.reply,results=result.results,candidates=result.candidates,offset=0)
            return result.reply,state
        return _menu_prompt(state),state
    state['input']=values
    state['menu']=MENU_STEPS[MENU_STEPS.index(step)+1]
    return _menu_prompt(state),state


def _route(text):
    """Extract both route endpoints, including a typo, before alias matching."""
    typo=_carrier_typo(text)
    if typo:
        text=re.sub(r'(?<![A-Za-z])'+re.escape(typo)+r'(?![A-Za-z])','',text,flags=re.I)
    text = re.sub(CARRIER_PATTERN,'',text,flags=re.I)
    text = re.sub(r'^(?:(?:请|帮我|麻烦|帮忙|我想|想|查一下|查下|查查|查询|查|看看|看下|看一下|船期|从)\s*)+','',text)
    parts=re.split(r'\s*(?:到|至|去|→|->|\bto\b)\s*',text,maxsplit=1,flags=re.I)
    if len(parts)!=2: return None
    left,right=parts
    if re.search(r'\d|周|日期|月份',left): return None
    right=re.split(r'[,，;；]|下下周|下周|本周|这周|下个月|月底|月初|\d{1,4}[-/年月]|什么时候|啥时候|哪天|有(?:什么|哪些|啥)?船|船期|开船|的船|next week|next month',right,maxsplit=1,flags=re.I)[0]
    left=left.strip(' ,，:：').removeprefix('从').strip();right=right.strip(' ,，:：的')
    if not left or not right or max(len(left),len(right))>80: return None
    return left,right


def _ports(text):
    hits = []
    for port in port_names():
        for alias in [port['zh'], port['en'], *port['aliases']]:
            pattern = re.escape(alias)
            if alias.isascii():
                pattern = r'(?<![A-Za-z])'+pattern+r'(?![A-Za-z])'
            for match in re.finditer(pattern, text, re.I):
                hits.append((match.start(),match.end(),port))
    # Prefer the longest alias, retaining same-name country alternatives.
    selected = []
    for start,end,port in sorted(hits,key=lambda h:(h[0],-(h[1]-h[0]))):
        if any(a<=start and b>=end and (a,b)!=(start,end) for a,b,_ in selected):
            continue
        if not any(a==start and b==end and p==port for a,b,p in selected):
            selected.append((start,end,port))
    groups = {}
    for start,end,port in selected:
        groups.setdefault((start,end),[]).append(port)
    found = []
    previous_end = 0
    for (start,end),ports in sorted(groups.items()):
        prefix = text[max(previous_end,start-12):start]
        country = next((code for name,code in COUNTRIES.items() if name in prefix),None)
        # Explicit parenthetical country/ISO suffix is also accepted.
        suffix = re.match(r'\s*[（(]\s*([^）)]+)[）)]',text[end:])
        if suffix:
            country = COUNTRIES.get(suffix[1],suffix[1].upper() if re.fullmatch('[A-Za-z]{2}',suffix[1]) else country)
        eligible = [p for p in ports if not country or p['country']==country]
        port = eligible[0] if len(eligible)==1 else ports[0]
        found.append((start,end,port['zh'],country or (port['country'] if len(ports)==1 else None)))
        previous_end = end
    return found


def is_schedule_intent(message, previous=None):
    text = _text(message)
    if re.search(r'是什么|什么意思|怎么理解|有什么区别|举个例子',text):
        return False
    implicit_route = (_route(text) and re.search(r'有啥船|有船|开船|班船|几号走|(?:的)?船[。.!！?？\s]*$',text)
                      and not re.search(r'报价|运费|多少钱|费用',text))
    if re.search(r'船期|开船时间|(?:哪天|什么时候|啥时候).{0,4}(?:开船|有船)|航次查询|sailing\s+schedule|(?:查|看看|看下).{0,100}(?:船|航次)',text,re.I) or implicit_route:
        return not bool(re.search(r'是什么|什么意思|怎么理解',text))
    if previous and previous.get('active') and (previous.get('menu') or previous.get('carrier_candidates')):
        # A visible menu owns answers, but not explicit knowledge/cargo questions.
        return not bool(re.search(r'是什么|有什么区别|为什么|举个例子|\d\s*(?:箱|托|kg|公斤|CBM)|邮编|报价',text,re.I))
    if not previous or not previous.get('active'):
        return False
    return bool(_ports(text) or match_ports(text)[1] or re.search(r'下周|本周|这周|下个月|月底|后天|明天|今天|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}月|\d{1,2}[/.]\d{1,2}|直达|直航|中转|只看|换成|刷新|更多|下一页|起运港|目的港|next week|next month',text,re.I)
                or re.fullmatch(r'(?:第)?\d{1,2}(?:个)?[。.！!]?|ONE|COSCO|中远(?:海运)?|海洋网联',text,re.I)
                or text in COUNTRIES or text.upper() in set(COUNTRIES.values()))


def _dates(text, today):
    text = re.sub('next week','下周',text,flags=re.I)
    text = re.sub('next month','下个月',text,flags=re.I)
    text = text.replace('号到','日到').replace('号至','日至')
    if '月底' in text:
        end=(today.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)
        return max(today,end.replace(day=21)),end
    slash = re.findall(r'(?<!\d)(\d{1,2})[/.](\d{1,2})(?!\d)',text)
    if slash:
        dates=[date(today.year,int(m),int(d)) for m,d in slash]
        if len(dates)>2: raise ValueError('too_many_dates')
        if len(dates)==1:
            shorthand=re.search(r'\d{1,2}[/.]\d{1,2}\s*(?:至|到|—|-)\s*(\d{1,2})(?!\d|[/.])',text)
            if shorthand: dates.append(dates[0].replace(day=int(shorthand[1])))
        return dates[0],dates[-1]
    week = re.search(r'(下下|下|本|这)周([一二三四五六日天])?',text)
    if week:
        delta = {'下下':14,'下':7,'本':0,'这':0}[week[1]]
        start = today+timedelta(days=delta-today.weekday())
        if week[2]:
            day = start+timedelta(days='一二三四五六日'.index(week[2].replace('天','日')))
            return day,day
        return max(start,today),start+timedelta(days=6)
    if '下个月' in text:
        start = (today.replace(day=28)+timedelta(days=4)).replace(day=1)
        end = (start.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)
        if '上旬' in text: return start,start.replace(day=10)
        if '中旬' in text: return start.replace(day=11),start.replace(day=20)
        if '下旬' in text: return start.replace(day=21),end
        return start,end
    if '未来四周' in text or '未来4周' in text:
        return today,today+timedelta(days=27)
    if '明天' in text:
        return today+timedelta(days=1),today+timedelta(days=1)
    if '后天' in text:
        return today+timedelta(days=2),today+timedelta(days=2)
    if '今天' in text:
        return today,today
    iso = re.findall(r'\d{4}-\d{1,2}-\d{1,2}',text)
    if iso:
        values = [date(*map(int,v.split('-'))) for v in iso]
        if len(values)>2:
            raise ValueError('too_many_dates')
        return values[0],values[-1]
    matches = list(re.finditer(r'(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号]?',text))
    if matches:
        values = [date(int(m[1] or today.year),int(m[2]),int(m[3])) for m in matches]
        if len(values)>2:
            raise ValueError('too_many_dates')
        last = re.search(r'(?:至|到|—|-)\s*(\d{1,2})(?:[日号]|(?=\D|$))',text[matches[-1].end():])
        if len(values)==1 and last:
            values.append(values[0].replace(day=int(last[1])))
        return values[0],values[-1]
    # Month-only asks for that whole month, never a fabricated day.
    month = re.search(r'(?:(\d{4})年)?(\d{1,2})月',text)
    if month:
        start = date(int(month[1] or today.year),int(month[2]),1)
        return start,(start.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)
    return None


def schedule_turn(message, previous=None, *, today=None):
    text, today = _text(message), today or today_local()
    state = deepcopy(previous) if previous and previous.get('version')==1 else {'version':1,'active':True,'input':{}}
    state['active'] = True
    if text in {'新船期查询','重查新船期'}:
        state = {'version':1,'active':True,'input':{}}
    if text in {'查船期','船期查询','查询船期'} and not state.get('input') and not state.get('last_reply'):
        text='船期菜单'
    # A full route can switch back to natural input at any menu step.
    route=_route(text)
    if route and state.get('menu'):
        state.pop('menu',None);state.pop('menu_candidates',None);state.pop('menu_freeform',None)
    menu_result=_menu_turn(text,state,today)
    if menu_result is not None:
        return menu_result
    confirmed_carrier=False
    if state.get('carrier_candidates'):
        if re.fullmatch(r'1[。.!！]?|是|是的|确认|COSCO|中远(?:海运)?',text,re.I):
            text='COSCO';confirmed_carrier=True
        elif re.fullmatch(r'(?:只看|换成)?ONE',text,re.I):
            text='ONE';confirmed_carrier=True
        elif not route and text not in {'新船期查询','重查新船期','船期菜单'}:
            return _carrier_prompt(state),state
        state.pop('carrier_candidates',None)
    values = deepcopy(state.get('input',{}))
    original_values = deepcopy(values)
    if text in {'更多船期','更多','下一页'} and state.get('results'):
        state['offset'] = state.get('offset',0)+5
        return render_results(ScheduleInput(**values),state['results'],offset=state['offset']),state
    if text in {'查船期','船期查询','查询船期','返回船期'} and state.get('last_reply'):
        return state['last_reply'],state
    # Select only a previously displayed candidate, never an arbitrary identifier.
    candidates = state.get('candidates',[])[:12]
    choice = re.fullmatch(r'(?:第)?(\d{1,2})(?:个)?[。.！!]?',text)
    country = COUNTRIES.get(text,text.upper() if text.upper() in COUNTRIES.values() else None)
    candidate = None
    if choice and candidates and not 1 <= int(choice[1]) <= len(candidates):
        return f'请回复上面列出的序号（1—{len(candidates)}），或补充更准确的港口和国家。',state
    if choice and 1 <= int(choice[1]) <= len(candidates):
        candidate = candidates[int(choice[1])-1]
    elif country and candidates:
        matches = [c for c in candidates if c.get('country_code')==country]
        if len(matches)==1:
            candidate = matches[0]
    if candidate:
        side = candidate['side']
        if candidate.get('carrier'):
            values.setdefault(side+'_ids',{})[candidate['carrier']] = candidate['carrier_location_id']
        else:
            values[side+'_country'] = candidate['country_code']
            values[side] = candidate.get('text',values.get(side))
    ports = _ports(text)
    if route:
        for side,raw in zip(('origin','destination'),route):
            country=next((code for name,code in COUNTRIES.items() if raw.startswith(name)),None)
            if country:
                raw=next(raw[len(k):].strip() for k,v in COUNTRIES.items() if v==country and raw.startswith(k))
            else:
                known=_ports(raw)
                if len(known)==1 and known[0][0]==0:
                    raw,country=known[0][2],known[0][3]
            values[side],values[side+'_country'],values[side+'_ids']=raw,country,{}
    elif ports:
        if len(ports)>=2:
            assignments = [('origin',ports[0]),('destination',ports[1])]
        else:
            pending_sides={c['side'] for c in candidates}
            pending_side=next(iter(pending_sides)) if len(pending_sides)==1 else None
            side = 'origin' if re.search(r'起运|出发|从',text[:ports[0][0]]) or re.match(r'\s*(?:出发|起运)',text[ports[0][1]:]) else 'destination' if re.search(r'目的|到|去',text[:ports[0][0]]) else pending_side or ('origin' if not values.get('origin') else 'destination')
            assignments = [(side,ports[0])]
        for side,(_,_,name,port_country) in assignments:
            values[side] = name
            values[side+'_country'] = port_country
            values[side+'_ids'] = {}
    elif not candidate:
        # Unknown English ports are still resolved by the official carrier.
        route = re.search(r'(?:从)?([A-Za-z][A-Za-z .-]{1,60}?)\s+(?:to|到|至|→)\s+([A-Za-z][A-Za-z .-]{1,60}?)(?=\s+\d|[,，;；]|$)',text,re.I)
        if route:
            for side,name in zip(('origin','destination'),route.groups()):
                values[side]=name.strip();values[side+'_ids']={};values[side+'_country']=None
        for side,label in [('origin','起运港'),('destination','目的港')]:
            field = re.search(label+r'\s*[:：]\s*([^,，;；\n]{1,80})',text)
            if field:
                values[side]=field[1].strip();values[side+'_ids']={};values[side+'_country']=None
        if not state.get('candidates') and re.fullmatch(r'[A-Za-z\u4e00-\u9fff .-]{2,50}',text) and text not in {'查船期','船期查询','新船期查询','刷新船期','返回船期'}:
            kind,matches=match_ports(text)
            if matches:
                side='origin' if not values.get('origin') else 'destination'
                values[side],values[side+'_country'],values[side+'_ids']=text,None,{}
    unsupported = re.search(r'(?<![A-Za-z])(?:MAERSK|MSC|HMM|OOCL|CMA|EVERGREEN)(?![A-Za-z])|马士基|长荣|达飞|东方海外|现代商船|地中海航运',text,re.I)
    if unsupported:
        return f'目前已接入 ONE 和 COSCO，尚未接入{unsupported[0]}。可以指定这两家查询。',state
    carriers = []
    if re.search(r'(?<![A-Za-z])ONE(?![A-Za-z])|海洋网联',text,re.I): carriers.append('ONE')
    if re.search(r'(?<![A-Za-z])COSCO(?![A-Za-z])|中远',text,re.I): carriers.append('COSCO')
    if carriers: values['carriers']=carriers
    if re.search(r'两家|全部船公司',text): values['carriers']=['ONE','COSCO']
    if '直达' in text or '直航' in text: values['routing']='direct'
    elif '中转' in text: values['routing']='transshipment'
    if '都可以' in text or '不限' in text: values['routing']='any'
    try:
        dates = _dates(text,today)
        if dates:
            values['departure_from'],values['departure_until'] = (v.isoformat() for v in dates)
        query = ScheduleInput(**values)
    except (ValueError,ValidationError):
        return '日期范围无法识别：请提供有效的开始和结束日期，例如“2026-10-19 至 2026-10-25”，范围最多90天。已有港口资料已保留。',state
    typo=_carrier_typo(text)
    if typo:
        state.update(input=values,carrier_candidates=[{'text':typo,'carrier':'COSCO'}])
        # A pending replacement must not expose results from a previous query.
        for key in ('results','last_reply','candidates','offset'):
            state.pop(key,None)
        return _carrier_prompt(state),state
    if values == original_values and not candidate and not confirmed_carrier and text not in {'新船期查询','重查新船期','刷新船期','返回船期','查船期','船期查询','查询船期'}:
        return '这句话里的查询条件还没识别清楚，原来的资料已保留。可以直接写港口和日期，或发送“船期菜单”按序号选择。',state
    result = query_schedules(query,today=today)
    state.update(input=result.query.model_dump(mode='json'),last_reply=result.reply,results=result.results,candidates=result.candidates,offset=0)
    return result.reply,state
