"""Deterministic customs intake. Its state is separate from the cargo draft."""
import re
import unicodedata

from pydantic import ValidationError

from apps.api.services.customs_reference import CustomsInput, REFUSAL, PROMPTS, query_customs, render_reference
from packages.ai_assistant.quote_scope import contains_task_instruction

COUNTRIES = {"中国": "CN", "china": "CN", "cn": "CN", "加拿大": "CA", "canada": "CA", "ca": "CA", "美国": "US", "usa": "US", "us": "US"}
START = re.compile(r"^(?:请|帮我)?\s*(?:查|查询|新)?\s*(?:关税(?:查询)?|税率(?:查询)?|海关编码|HS(?:编码|\s*code)?|HTS)", re.I)


# A concrete rate question starts intake; explanations and policy questions stay
# in the knowledge path. No instruction text is ever forwarded as an answer.
_CONCEPT = re.compile(r"为什么|为何|怎么计算|怎么算|如何计算|区别|什么是|政策|规定|清单|(?:关税|税率|税费)(?:是|指)什么|\b(?:what is|why|policy)\b", re.I)
_TAX = re.compile(r"关税|税率|进口税|进口税费|(?:交|缴|付|收|征)(?:多少|什么)?税|\b(?:tariff|import duty|duty rate)\b", re.I)
_COMMANDS = {"关税查询", "查关税", "查税率", "查询关税", "查询税率"}
_NEW = {"新关税查询", "新关税"}


def _text(message):
    text = unicodedata.normalize("NFKC", message)
    return "".join(c for c in text if unicodedata.category(c) != "Cf").strip()


def is_customs_intent(message):
    text = _text(message)
    if text in _COMMANDS | _NEW:
        return True
    if _CONCEPT.search(text) or re.search(r"(?:含|包)关税|(?:含|包)税(?:运费|报价)", text):
        return False
    return bool(START.search(text) or _TAX.search(text) and
                re.search(r"多少|查询|查一下|帮我查|要交|\?|？|加拿大|美国|\b(?:canada|usa|how much)\b", text, re.I))


def _natural_patch(message, pending):
    """Capture customer-stated facts, never infer origin or tariff classification."""
    patch = {}
    origin = re.search(r"(中国|越南|加拿大|美国|日本|印度|墨西哥|泰国|德国)(?:制造|生产|产的|产地)|(?:产自|生产于|制造于)(中国|越南|加拿大|美国|日本|印度|墨西哥|泰国|德国)", message)
    if origin:
        name = origin[1] or origin[2]
        patch["origin"] = _country(name) or name
    rate_question = is_customs_intent(message) and bool(_TAX.search(message))
    if rate_question:
        # Remove labelled origin/HS-country clauses before resolving destination.
        destination_text = re.sub(r"(?:原产地|原产国|编码国家|编码所属国家)\s*[:：=]?\s*[^,，;；\n ]+", "", message)
        if origin:
            destination_text = destination_text.replace(origin[0], "")
        destinations = set(re.findall(r"加拿大|美国|\bCanada\b|\bUSA\b", destination_text, re.I))
        countries = {_country(x) for x in destinations}
        if len(countries) == 1:
            patch["destination"] = countries.pop()
        # Product can be before the tax question or after an explicit query verb.
        head = _TAX.split(message, maxsplit=1)[0]
        head = re.sub(r"^(?:请问|请|帮我|麻烦|我想知道|我想查|想查|查询一下|查一下|查询|查|一下|帮忙)+", "", head).strip()
        if origin:
            head = head.replace(origin[0], "")
        head = re.sub(r"(?:出口到|进口到|出口至|进口至|发往|出口|进口|到|在|至)?(?:加拿大|美国|Canada|USA)", "", head, flags=re.I)
        head = re.sub(r"(?:(?:要|需要)?(?:交|缴|付|收)?多少|要交|需要交|要缴|需要缴|交|缴|是多少|多少|的|要|有)+$", "", head).strip(" 的，,;；:：")
        head = re.sub(r"^(?:进口|出口|的|HS(?:编码)?\s*[:：]?)", "", head, flags=re.I).strip(" 的")
        if head and len(head) <= 200 and not re.search(r"[:：;；,，\n?？]|最新|现在|今天|今年|目前|[{}]", head):
            patch["query"] = head
    if not rate_question and pending != "query":
        # Plain language supplements can supply more than the currently asked field.
        for clause in re.split(r"[,，;；\n]", message):
            clause = clause.strip().rstrip("。.!！")
            country = _country(clause.removesuffix("的"))
            if country:
                field = pending if pending in {"origin", "destination", "code_country"} else "origin"
                if field == "destination" and country == "CN":
                    field = "origin"
                patch[field] = country
            if re.fullmatch(r"(?:那|换成|改成|改为|发到|出口到|进口到)?\s*(加拿大|美国)(?:呢|吧)?", clause):
                if pending not in {"origin", "code_country"}:
                    patch["destination"] = "CA" if "加拿大" in clause else "US"
            if not re.search(r"[?？]|什么|怎么|区别|不确定|不知道", clause):
                if re.search(r"棉|涤纶|聚酯|羊毛|尼龙|锦纶|粘胶|丝绸|腈纶|针织|梭织|不锈钢|塑料|木质|实木|硅胶|铝合金|玻璃|陶瓷", clause):
                    if not re.search(r"品名|用途|原产|到加拿大|到美国", clause):
                        patch["material"] = "，".join(filter(None, [patch.get("material"), clause]))
                if re.search(r"日常穿|平时穿|日常用|家用|工业用|医用|防护用|商用|用于|用来", clause):
                    patch["use"] = clause
    return patch


def _followup(value, field, previous):
    labels = {"CA": "加拿大", "US": "美国"}
    parts = []
    old = (previous or {}).get("input") or {}
    if value.query and (value.query != old.get("query") or value.destination != old.get("destination")):
        parts.append(f"{value.query}" + (f"，进口到{labels[value.destination]}" if value.destination else "") + "，记下了。")
        if value.origin == "CN" and not old.get("origin"):
            parts.append("先按中国原产查询。")
    questions = {
        "query": "你想查什么商品？直接说品名或发HS编码就行。",
        "origin": "这件商品是在哪个国家生产的？需要确认原产地，不能只按发货地算。",
        "destination": "要进口到加拿大还是美国？",
        "material": "主要是什么材质？有不同成分的话，也说一下比例。",
        "use": "主要用来做什么？比如家用、工业用，或其他用途。",
        "code_country": "这个完整HS编码属于哪个国家：中国、加拿大还是美国？",
    }
    if re.search(r"衣|衫|裤|服装|外套|夹克|裙|毛衫|t恤|t-shirt|shirt", value.query or "", re.I):
        questions["origin"] = "这件衣服是在哪个国家生产的？需要确认原产地，不能只按发货地算。"
        questions["material"] = "面料成分和比例是什么？比如100%棉或棉涤混纺；也请说一下是针织还是梭织。"
        questions["use"] = "是日常穿着，还是防护服等特殊用途？"
    parts.append(questions.get(field, PROMPTS.get(field, "再补充一下商品情况，我接着帮你查。")))
    return "".join(parts)


def _country(value):
    return COUNTRIES.get(value.strip().lower().rstrip("。.!！"))


def customs_turn(message: str, previous: dict | None, *, query=None):
    """Return (reply, durable state). Rejects leave previous state untouched."""
    message = _text(message)
    if contains_task_instruction(message) or len(message) > 1500 or re.search(r"讲.{0,6}(?:笑话|故事)|```|[{}]", message):
        return REFUSAL, previous
    if message in _NEW:
        previous = None
    resume = message in _COMMANDS | _NEW
    if resume and (previous or {}).get("last_reference"):
        return render_reference(previous["last_reference"]), previous
    data = dict((previous or {}).get("input") or {})
    pending = (previous or {}).get("pending")
    retry = message.strip() in {"重查", "重新查询"} and bool(data)
    patch = _natural_patch(message, pending) if not resume else {}
    patterns = {
        "query": r"(?:品名|商品名称|产品名称|HS(?:编码|\s*code)?|海关编码|HTS)\s*[:：=]\s*([^;；\n，,]+)",
        "material": r"(?:材质|材料)\s*[:：=]\s*([^;；\n，,]+)",
        "use": r"(?:用途|功能)\s*[:：=]\s*([^;；\n，,]+)",
        "origin": r"(?:原产地|原产国)\s*[:：=]?\s*([^;；\n，, ]+)",
        "destination": r"(?:目的国|进口国|出口到|出口至|发往|到|至)\s*[:：=]?\s*(加拿大|美国|Canada|USA|CA|US)",
        "code_country": r"(?:编码国家|编码所属国家|代码国家)\s*[:：=]?\s*(中国|加拿大|美国|China|Canada|USA|CN|CA|US)",
        "rule_date": r"(?:规则日期|日期)\s*[:：=]?\s*(\d{4}-\d{2}-\d{2})",
    }
    for field, pattern in patterns.items():
        match = re.search(pattern, message, re.I)
        if match:
            patch[field] = match[1].strip()
    for field in ("origin", "destination", "code_country"):
        if field in patch:
            patch[field] = _country(patch[field]) or patch[field]
    if not resume and "query" not in patch and START.match(message):
        first = re.split(r"[;；\n，,]", START.sub("", message, count=1).strip(" ：:，,；;"), maxsplit=1)[0]
        first = re.sub(patterns["destination"], "", first, flags=re.I).strip()
        if first and len(first) <= 200 and not re.search(r"[:：=]|是多少|多少|查询", first):
            patch["query"] = first
    if not patch and pending and not retry and not resume:
        text = message.strip().rstrip("。.!！")
        if pending in {"origin", "destination", "code_country"}:
            if _country(text):
                patch[pending] = _country(text)
        elif pending in {"vacuum_insulated", "contains_steel_aluminum"}:
            if text.lower() in {"是", "否", "有", "没有", "yes", "no"}:
                patch[pending] = text.lower() in {"是", "有", "yes"}
        elif pending in {"query", "material", "use"} and not is_customs_intent(text):
            if len(text) <= 200 and not re.search(r"[?？]|不知道|不清楚|不确定|^(?:为什么|怎么|如何|什么是|讲个|帮我|请你)", text):
                patch[pending] = text
    if not patch and not resume and is_customs_intent(message):
        # A short command with a product/code is supported; structured labels
        # are preferred when also supplying origin, destination or attributes.
        text = START.sub("", message, count=1).strip(" ：:，,；;")
        if text and len(text) <= 200 and not re.search(r"[;；\n，]|关税|税率", text):
            patch["query"] = text
    if not patch and not retry and not resume:
        try:
            value = CustomsInput.model_validate(data)
        except ValidationError:
            value = CustomsInput()
        if pending == "material" and re.search(r"不知道|不清楚|不确定", message):
            return "可以看看商品的成分标或详情页，把面料/材质标注的文字发给我；暂时不确定的部分先留空，我不会替你猜。", previous
        return _followup(value, pending or "query", previous), previous
    if patch.get("query") and data.get("query") and patch["query"] != data["query"]:
        # Another item may have different origin/material/use, even on the same route.
        data = {key: val for key, val in data.items() if key in {"destination", "rule_date"}}
    data.update(patch)
    if data.get("query"):
        numeric = re.sub(r"[.\s]", "", data["query"])
        if re.fullmatch(r"\d{6,10}", numeric):
            data["query"] = numeric
    try:
        value = CustomsInput.model_validate(data)
    except ValidationError:
        return "资料格式无法识别。目的国请填加拿大或美国，日期请用YYYY-MM-DD；每个商品属性不超过200字。", previous
    result = (query or query_customs)(value)
    if result.code == "customs_scope_only":
        return result.reply, previous
    origin_source = "user" if "origin" in patch else (
        (previous or {}).get("origin_source", "user") if data.get("origin") else "default_cn")
    state = {"version": 1, "input": value.model_dump(mode="json"), "active": True, "origin_source": origin_source,
             "pending": result.missing_fields[0] if result.missing_fields else None,
             "last_status": result.status, "last_code": result.code, "last_reference": result.reference}
    reply = _followup(value, state["pending"], previous) if result.status == "needs_input" and state["pending"] else result.reply
    return reply, state
