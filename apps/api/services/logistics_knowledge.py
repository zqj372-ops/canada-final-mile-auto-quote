"""Source-backed logistics Q&A without changing shipment data or inventing facts.

Small curated corpus with aliases, question facets and durable topic follow-ups.
No web scraping, model completion, pricing, customs filing or document ingestion
runs in this path. Sources and policy review dates belong to the corpus, never
customer input. Company SOPs must be reviewed before being added to the corpus.
"""
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Literal
import unicodedata
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

CORPUS_PATH = Path(__file__).resolve().parents[3] / 'packages/ai_assistant/logistics_knowledge.json'
HELP = ('可以直接问物流和关务问题，比如“尾板和手叉车有什么区别”“DDP和DAP谁负责清关”“CARM和RPP是什么”。'
        '也可以接着问“要准备什么资料”“举个例子”。询价中途提问不会清空货物资料，补充件数、重量或邮编即可继续报价。')
SCOPE_REPLY = '我可以帮你做加拿大尾程报价、关税参考查询、ONE/COSCO公开船期查询，也能解释物流和关务问题。请说一下具体业务场景。'

_QUESTION = re.compile(r'什么|啥|谁|怎么|怎样|如何|为什么|为何|区别|差别|意思|解释|说明|讲讲|介绍|说说|了解|不懂|没概念|没听说|科普|查一下|有没有|能否|能不能|可不可以|是否|算不算|需不需要|要不要|多少|哪些|流程|注意|条件|要求|怎么办|吗[。!?？！]*$|[?？]|\b(?:what|why|how|explain|difference|tell me|do i need)\b', re.I)
_EXPLICIT = re.compile(r'^(?:请|帮我)?\s*(?:问知识|知识问答|物流知识|关务知识|知识库|咨询|请教)\s*[:：,，]?\s*', re.I)
_BUSINESS = re.compile(r'^(?:请|帮我)?\s*(?:查关税|新关税|查税率|查询税率|关税查询|查询关税|新报价|报个价|报价\s*[:：]|询价\s*[:：]|(?:HS|HTS|海关编码)\s*[:：]?\s*\d|(?:品名|材质|用途|原产地|原产国|目的国|编码国家|规则日期)\s*[:：])', re.I)
_DOMAIN = re.compile(r'物流|关务|清关|报关|进口|出口|运输|派送|发货|海运|空运|卡车|货运|海关|关税|税率|税费|免税|尾板|手叉车|托盘|原产地|私人地址|预约|发票|提单|熏蒸|滞箱|滞期|\b(?:shipping|freight|customs|import|export|ddp|dap|carm|rpp|hs|hts|fcl|lcl|ltl|sima|ispm)\b', re.I)
_FOLLOWUP = re.compile(r'^(?:那|那么|所以|这个|这样|还|那我)?\s*(?:要准备(?:什么|哪些|啥)(?:资料|文件|材料)?|需要(?:什么|哪些|啥)(?:资料|文件|材料)|怎么(?:操作|处理|办)|具体(?:一点|点|怎么做)?|详细(?:一点|点|说说)?|展开(?:说说|说)?|继续(?:说)?|举(?:个)?例子|举例|比如呢|例子呢|为什么呢|为啥呢|还有呢|然后呢|下一步(?:呢)?|怎么办|加拿大呢|美国呢|what next|tell me more|example)[。.!！?？]*$', re.I)
_UNTRUSTED = re.compile(r'忽略.{0,20}(?:指令|规则|提示)|(?:系统|开发者)提示词|扮演|越狱|你现在是|(?:写|生成|编写).{0,12}(?:代码|程序|脚本|诗|小说|故事)|翻译以下|翻译全文|base64|密钥|```|<\s*/?(?:system|developer|assistant)|\b(?:ignore|override)\b.{0,40}\b(?:instructions?|rules?|prompts?)\b|\b(?:system prompt|developer message|api key|jailbreak|act as)\b|\b(?:write|generate)\b.{0,25}\b(?:code|script|poem|story)\b', re.I | re.S)
_CURRENT = re.compile(r'(?:最新|今天|现在|目前|现行|今年|当前).{0,30}(?:政策|规定|税率|免税|关税|加征|清单)|(?:税率|关税|免税额度)(?:到底|现在)?(?:是多少|多少)|(?:是否|要不要|需要|有没有).{0,10}(?:加征|反倾销税)|(?:我|这票|这批).{0,15}(?:放行了吗|到哪|送到|查验结果)|\b(?:latest|current).{0,25}(?:tariff|duties|policy)\b', re.I)
_FACETS = (
    ('example', re.compile(r'例子|举例|比如|example', re.I)),
    ('next_steps', re.compile(r'准备|资料|文件|材料|操作|怎么办|怎么做|下一步|流程|checklist|what next', re.I)),
    ('details', re.compile(r'详细|具体|展开|还有|继续|为什么呢|为啥呢|more|detail', re.I)),
)
_ALLOWED_HOSTS = {'www.fedex.com', 'www.fedexfreight.com', 'www.cbsa-asfc.gc.ca', 'cbsa-asfc.gc.ca',
                  'www.help.cbp.gov', 'academy.iccwbo.org', 'inspection.canada.ca', 'terms.maersk.com', 'www.maersk.com'}


class KnowledgeInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=1500)
    previous_topic_id: str | None = Field(default=None, max_length=80)


class KnowledgeSource(BaseModel):
    title: str
    kind: Literal['public', 'internal']
    url: str | None = None
    verified_on: date


class KnowledgeResponse(BaseModel):
    status: Literal['answered', 'needs_input', 'requires_lookup', 'needs_review', 'out_of_scope', 'unavailable']
    code: str
    reply: str
    topic_id: str | None = None
    sources: list[KnowledgeSource] = Field(default_factory=list)
    knowledge_version: str | None = None
    next_action: Literal['ask', 'customs_query', 'operations_review'] = 'ask'


def _text(value):
    value = unicodedata.normalize('NFKC', value)
    return ''.join(c for c in value if unicodedata.category(c) != 'Cf').strip().lower()


def _keyword(text, keyword):
    keyword = _text(keyword)
    if keyword.isascii():
        return bool(re.search(r'(?<![a-z0-9])' + re.escape(keyword) + r'(?![a-z0-9])', text))
    return keyword in text


@lru_cache(maxsize=1)
def load_knowledge():
    corpus = json.loads(CORPUS_PATH.read_text(encoding='utf-8'))
    ids = set()
    for source in corpus['sources'].values():
        KnowledgeSource.model_validate(source)
        if source['kind'] == 'public':
            url = urlsplit(source['url'])
            if url.scheme != 'https' or url.hostname not in _ALLOWED_HOSTS or url.username or url.password:
                raise ValueError('invalid knowledge source')
    for entry in corpus['entries']:
        if entry['id'] in ids or not entry['keywords'] or entry['review_after_days'] <= 0:
            raise ValueError('invalid knowledge entry')
        ids.add(entry['id'])
        date.fromisoformat(entry['verified_on'])
        if not entry['source_ids'] or any(key not in corpus['sources'] for key in entry['source_ids']):
            raise ValueError('missing knowledge source')
        for field in ('answer', 'details', 'next_steps', 'example'):
            if not isinstance(entry[field], str) or not 1 <= len(entry[field]) <= 1000:
                raise ValueError('invalid knowledge text')
        for pattern in entry.get('patterns', []):
            re.compile(pattern)
    return corpus


def _rank(text, corpus):
    ranked = []
    for entry in corpus['entries']:
        matches = [keyword for keyword in entry['keywords'] if _keyword(text, keyword)]
        phrase_match = any(re.search(pattern, text, re.I) for pattern in entry.get('patterns', []))
        if matches or phrase_match:
            score = max([len(keyword) for keyword in matches] or [0]) + min(3, len(matches))
            score = max(score, 3 if phrase_match else 0)
            if ((entry['jurisdiction'] == 'CA' and '加拿大' in text)
                    or (entry['jurisdiction'] == 'US' and re.search(r'美国|\b(?:us|usa)\b', text))):
                score += 2
            ranked.append((score, entry))
    return sorted(ranked, key=lambda row: -row[0])


def is_knowledge_intent(message: str, previous: dict | None = None) -> bool:
    text = _text(message)
    if _BUSINESS.search(text):
        return False
    if _EXPLICIT.search(text):
        return True
    if previous and _FOLLOWUP.fullmatch(text):
        return True
    try:
        ranked = _rank(text, load_knowledge())
    except (OSError, ValueError, KeyError, TypeError):
        return bool(_DOMAIN.search(text) and _QUESTION.search(text))
    if _QUESTION.search(text) and (ranked or _DOMAIN.search(text)):
        return True
    # Bare glossary acronyms are useful queries; bare cargo/service words remain
    # shipment data so "尾板", "木托" and "预约" are never silently diverted.
    return text in {'ddp', 'dap', 'carm', 'rpp', 'hs', 'hts', 'fcl', 'lcl', 'ltl', 'ftl', 'sima', 'ispm15'}


def query_knowledge(value: KnowledgeInput, *, today: date | None = None) -> KnowledgeResponse:
    text = _text(value.question)
    if _UNTRUSTED.search(text):
        return KnowledgeResponse(status='out_of_scope', code='knowledge_scope_only', reply=SCOPE_REPLY)
    try:
        corpus = load_knowledge()
        return _answer(value, text, corpus, today or datetime.now(ZoneInfo('Asia/Shanghai')).date())
    except (OSError, ValueError, KeyError, TypeError):
        return KnowledgeResponse(status='unavailable', code='knowledge_unavailable', reply='知识资料暂时无法读取。报价资料还在，你可以继续补充询价信息，或稍后再问。')


def _answer(value, text, corpus, today):
    base = {'knowledge_version': corpus['version']}
    if _EXPLICIT.sub('', text).strip('。.!！?？') == '':
        return KnowledgeResponse(status='needs_input', code='knowledge_help', reply=HELP, **base)
    known = {entry['id']: entry for entry in corpus['entries']}
    previous = known.get(value.previous_topic_id)
    if _CURRENT.search(text) or re.search(r'\b20\d{2}[-年/]', text):
        customs = bool(re.search(r'税|海关|清关|报关|关务|进口|出口|tariff|customs', text))
        reply = ('这需要按具体商品、目的国、原产地和查询日期核对，知识库不能确认实时税率或最新政策。'
                 '需要本票关税参考可发送“查关税”；政策适用性请结合官方公告和报关人员核实。' if customs else
                 '这需要本票的实时记录才能确认，知识库不能确认实际放行或送达状态。请把运单/提单号和最新通知交给操作人员核对。')
        return KnowledgeResponse(status='requires_lookup', code='knowledge_live_lookup_required', reply=reply,
                                 next_action='customs_query' if customs else 'operations_review', **base)
    ranked = _rank(text, corpus)
    followup = bool(previous and _FOLLOWUP.fullmatch(text))
    if followup:
        entry = previous
    elif ranked and (is_knowledge_intent(value.question) or _EXPLICIT.search(text)):
        entry = ranked[0][1]
        if len(ranked) > 1 and ranked[0][0] == ranked[1][0] and ranked[0][0] < 5:
            return KnowledgeResponse(status='needs_input', code='knowledge_ambiguous', reply=f'你更想了解“{ranked[0][1]["title"]}”，还是“{ranked[1][1]["title"]}”？补充一下场景，我再具体说明。', **base)
    else:
        if _DOMAIN.search(text) or _EXPLICIT.search(text) or _FOLLOWUP.fullmatch(text):
            return KnowledgeResponse(status='needs_input', code='knowledge_no_match', reply='这部分我还没有足够的已核对资料。请补充目的国和具体环节，例如运输、单证、原产地或清关；我不会直接套用其他业务的规则。', **base)
        return KnowledgeResponse(status='out_of_scope', code='knowledge_scope_only', reply=SCOPE_REPLY, **base)
    sources = [KnowledgeSource.model_validate(corpus['sources'][key]) for key in entry['source_ids']]
    source_text = '\n'.join(f'来源：{s.title}' + (f' {s.url}' if s.url else '（以本次报价及已确认服务为准）') for s in sources)
    meta = {**base, 'topic_id':entry['id'], 'sources':sources}
    region = 'US' if re.search(r'美国|\b(?:us|usa|united states)\b', text) else 'CA' if re.search(r'加拿大|\bcanada\b', text) else None
    if entry['policy'] and region is None and re.search(r'欧盟|欧洲|英国|德国|法国|澳大利亚|澳洲|日本|新加坡|墨西哥', text):
        return KnowledgeResponse(status='needs_input', code='knowledge_jurisdiction_mismatch',
                                 reply='这版关务资料主要覆盖加拿大和美国，不能直接用于你提到的目的地。请按该目的国官方要求核查具体手续。', **base)
    if region and entry['jurisdiction'] not in {'general', region}:
        label = '加拿大' if entry['jurisdiction'] == 'CA' else '美国'
        return KnowledgeResponse(status='needs_input', code='knowledge_jurisdiction_mismatch',
                                 reply=f'这条资料针对{label}，不能直接套用到你问的国家。请说明要核对的具体商品或手续，再按目的国官方要求确认。\n{source_text}', **meta)
    dates = [date.fromisoformat(entry['verified_on']), *(s.verified_on for s in sources)]
    verified = min(dates)
    if any(d > today for d in dates) or (today - verified).days > entry['review_after_days']:
        return KnowledgeResponse(status='needs_review', code='knowledge_review_due',
                                 reply=f'这条资料上次核验于{verified.isoformat()}，已需要重新核对；暂不把它作为当前业务结论。请按下列来源确认现行要求。\n{source_text}', **meta)
    facet = next((key for key, pattern in _FACETS if pattern.search(text)), 'answer')
    if facet == 'answer':
        reply = entry['answer'] + '\n\n' + entry['next_steps']
    else:
        reply = entry[facet] if followup else entry['answer'] + '\n\n' + entry[facet]
    if followup:
        reply = f'接着刚才的“{entry["title"]}”说：\n' + reply
    if entry['policy']:
        reply += f'\n\n资料核验：{verified.isoformat()}；这是一般说明，具体申报仍需结合本票事实和适用规则。'
    reply += '\n' + source_text
    return KnowledgeResponse(status='answered', code='knowledge_answer', reply=reply, **meta)


def knowledge_turn(message: str, previous: dict | None):
    if len(message) > 1500:
        return '这个问题比较长，请先聚焦一个物流或关务问题（1500字以内）。原来的报价资料已保留。', previous
    value = KnowledgeInput(question=message, previous_topic_id=(previous or {}).get('topic_id'))
    result = query_knowledge(value)
    # Refusal/failure must not replace the last usable topic or any cargo data.
    state = previous
    if result.topic_id and result.status == 'answered':
        state = {'version': 1, 'active': True, 'topic_id': result.topic_id, 'knowledge_version':result.knowledge_version}
    return result.reply, state
