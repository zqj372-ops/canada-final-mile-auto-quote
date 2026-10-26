"""Bounded ClearDDP reference-query adapter, independent of reviewed M2M data.

Use the existing public query contract without rotating anonymous identities,
spending paid grants, bypassing access checks, or promoting candidates to a
customs ruling. No local model calls and no quotation/pricing side effects.
"""
from __future__ import annotations

from datetime import date, datetime
import fcntl
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.ai_assistant.quote_scope import contains_task_instruction

BASE_URL = "https://clearddp.com"
HELP = ("可以直接问具体商品在美国或加拿大的关税，比如“男士上衣的加拿大税率是多少”。"
        "默认按中国原产查询；如果是其他产地，请告诉我。缺少商品属性时我会接着问，结果为待复核的关税参考。")
REFUSAL = "这里只接受商品归类、关税参考和尾程询价资料，不处理其他任务。" + HELP


class CustomsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str | None = Field(default=None, min_length=1, max_length=200)
    destination: Literal["CA", "US"] | None = None
    origin: str | None = Field(default="CN", max_length=40)
    material: str | None = Field(default=None, min_length=1, max_length=200)
    use: str | None = Field(default=None, min_length=1, max_length=200)
    code_country: Literal["CN", "CA", "US"] | None = None
    rule_date: date = Field(default_factory=lambda: datetime.now(ZoneInfo("Asia/Shanghai")).date())
    contains_steel_aluminum: bool | None = None
    vacuum_insulated: bool | None = None

    @field_validator("origin", mode="before")
    @classmethod
    def default_origin(cls, value):
        # Business default explicitly requested by the operator. Explicit origins
        # remain authoritative, including currently unsupported countries.
        return "CN" if value is None or (isinstance(value, str) and not value.strip()) else value

    @field_validator("query")
    @classmethod
    def normalize_code(cls, value):
        numeric = re.sub(r"[.\s]", "", value or "")
        return numeric if re.fullmatch(r"\d{6,10}", numeric) else value


class CustomsResponse(BaseModel):
    status: Literal["needs_input", "manual_review", "blocked", "unavailable"]
    code: str
    reply: str
    missing_fields: list[str] = Field(default_factory=list)
    input: CustomsInput
    # Only bounded, validated business projections; never raw provider prose.
    reference: dict | None = None


PROMPTS = {
    "query": "请提供商品名称或HS编码。",
    "origin": "请确认商品原产地（不是发货地）；目前此查询支持中国原产商品。",
    "destination": "请确认目的国：加拿大还是美国？",
    "code_country": "请说明这个完整HS编码属于中国、加拿大还是美国税则；不同国家的后几位不能直接通用。",
    "material": "请补充商品的主要材质。",
    "use": "请补充商品用途或功能。",
    "vacuum_insulated": "请确认商品是否具有真空保温结构（是/否）。",
    "contains_steel_aluminum": "请确认商品是否含钢或铝（是/否）。",
}


def input_blocked(value: CustomsInput) -> bool:
    texts = [value.query, value.material, value.use, value.origin]
    return any(contains_task_instruction(v) or re.search(r"讲.{0,6}(?:笑话|故事)|```|<[^>]+>|[{}]", v)
               for v in texts if v)


def missing_input(value: CustomsInput) -> list[str]:
    missing = [key for key in ("query", "origin", "destination") if not getattr(value, key)]
    numeric = bool(value.query and re.fullmatch(r"\d{6,10}", value.query))
    if numeric and len(value.query) > 6 and not value.code_country:
        missing.append("code_country")
    if not numeric:
        missing.extend(key for key in ("material", "use") if not getattr(value, key))
    return missing


def response(value: CustomsInput, status: str, code: str, reply: str, **kwargs):
    return CustomsResponse(input=value, status=status, code=code, reply=reply, **kwargs)


def query_customs(value: CustomsInput, *, client=None) -> CustomsResponse:
    if input_blocked(value):
        return response(value, "blocked", "customs_scope_only", REFUSAL)
    if value.origin and value.origin.upper() not in {"CN", "CHINA", "中国"}:
        return response(value, "blocked", "customs_origin_unsupported", "目前此查询只支持中国原产商品，不能套用到其他原产地。请由报关人员按实际原产地核查。")
    missing = missing_input(value)
    if missing:
        return response(value, "needs_input", "customs_details_required", "关税查询资料已保留。" + PROMPTS[missing[0]], missing_fields=missing)
    try:
        raw = (client or ClearDDPReferenceClient()).query(value)
        if raw.get("nextQuestion"):
            field = {"vacuumInsulated": "vacuum_insulated", "contains_steel_aluminum": "contains_steel_aluminum",
                     "material": "material", "use": "use"}.get(raw["nextQuestion"].get("attribute"))
            if not field or raw.get("mode") != "online_search" or raw.get("testData") is not True or raw.get("dataStatus", {}).get("ready") is not False:
                raise ValueError("unsupported_clarification")
            return response(value, "needs_input", "customs_source_clarification", PROMPTS[field], missing_fields=[field])
        projection = project_reference(raw, value)
        return response(value, "manual_review", "customs_reference_only", render_reference(projection), reference=projection)
    except CustomsUnavailable as exc:
        return response(value, "unavailable", exc.code, exc.reply)
    except (ValueError, TypeError, KeyError, AttributeError):
        return response(value, "unavailable", "customs_response_invalid", "关税来源返回的数据不完整或无法核验，本次不提供税率。资料已保留，请稍后重试或在ClearDDP网站核对。")


class CustomsUnavailable(Exception):
    def __init__(self, code, reply):
        self.code, self.reply = code, reply
        super().__init__(code)  # Never put an upstream body/cookie in an exception.


def unavailable(code="customs_upstream_unavailable", reply="关税查询服务暂时不可用，资料已保留。请稍后重试或到 https://clearddp.com/ 查询。"):
    return CustomsUnavailable(code, reply)


class ClearDDPReferenceClient:
    def __init__(self, *, directory: Path | None = None, transport=None, enabled: bool | None = None):
        self.directory = directory or Path(os.getenv("CLEARDDP_STATE_DIR", "outputs/clearddp"))
        self.transport = transport
        self.enabled = enabled if enabled is not None else os.getenv("CLEARDDP_REFERENCE_ENABLED", "false").lower() == "true"

    def query(self, value: CustomsInput) -> dict:
        if not self.enabled:
            raise unavailable("customs_not_enabled", "关税查询入口已准备好，当前尚未启用来源连接。资料已保留，请联系报价服务管理员启用。")
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            cookie_path = self.directory / "device.json"
            lock_path = self.directory / "device.lock"
            if cookie_path.is_symlink() or lock_path.is_symlink():
                raise unavailable("customs_session_invalid")
            with lock_path.open("a") as lock:
                os.chmod(lock_path, 0o600)
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    raise unavailable("customs_busy", "关税服务正在处理另一项查询，请稍后重试；资料已保留。") from None
                cookie = None
                if cookie_path.exists():
                    saved = json.loads(cookie_path.read_text())
                    if saved.get("blocked"):
                        raise unavailable("customs_session_expired", "关税查询会话需要管理员核对；不会自动更换身份重置额度。")
                    cookie = saved["rc_device"]
                    if not isinstance(cookie, str) or not re.fullmatch(r"[A-Za-z0-9._-]{20,512}", cookie):
                        raise unavailable("customs_session_invalid")
                with httpx.Client(base_url=BASE_URL, transport=self.transport, follow_redirects=False,
                                  timeout=httpx.Timeout(60, connect=5), trust_env=False,
                                  headers={"User-Agent": "CanadaQuoteBot/1.0", "Accept": "application/json"},
                                  cookies={"rc_device": cookie} if cookie else {}) as http:
                    status, _ = self._request(http, "GET", "/api/status", params={"ruleDate": value.rule_date.isoformat()})
                    # This adapter is deliberately tied to the site's explicit
                    # online-reference mode. It never falls back from M2M auth.
                    if status.get("ready") is not False or not any("联网候选" in str(r) for r in status.get("reasons", [])):
                        raise unavailable("customs_reference_mode_unavailable")
                    quota, headers = self._request(http, "GET", "/api/quota")
                    supplied = SimpleCookie()
                    for header in headers.get_list("set-cookie"):
                        supplied.load(header)
                    new_cookie = supplied.get("rc_device")
                    if new_cookie:
                        if cookie and cookie != new_cookie.value:
                            self._save_device(cookie_path, {"rc_device": cookie, "blocked": "session_expired"})
                            raise unavailable("customs_session_expired", "关税查询会话已失效，需要管理员核对；不会自动更换身份重置额度。")
                        cookie = new_cookie.value
                        if not re.fullmatch(r"[A-Za-z0-9._-]{20,512}", cookie):
                            raise unavailable("customs_session_invalid")
                        self._save_device(cookie_path, {"rc_device": cookie})
                    if not cookie:
                        raise unavailable("customs_session_invalid")
                    if type(quota.get("freeRemaining")) is not int or quota["freeRemaining"] <= 0:
                        raise unavailable("customs_quota_exhausted", "ClearDDP 来源的可用免费查询额度不足，请到原网站核对；当前资料已保留。")
                    body = {"query": value.query, "ruleDate": value.rule_date.isoformat(),
                            "attributes": {"originCountry": "CN"}}
                    if value.code_country:
                        body["codeCountry"] = value.code_country
                    for source, target in (("material", "material"), ("use", "use"),
                                           ("contains_steel_aluminum", "contains_steel_aluminum"), ("vacuum_insulated", "vacuumInsulated")):
                        fact = getattr(value, source)
                        if fact is not None:
                            body["attributes"][target] = fact
                    payload, _ = self._request(http, "POST", "/api/query", json=body)
                    return payload
        except CustomsUnavailable:
            raise
        except (OSError, ValueError, KeyError, httpx.HTTPError):
            raise unavailable() from None

    @staticmethod
    def _save_device(path, data):
        temporary = path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as out:
            json.dump(data, out)
        temporary.replace(path)
        os.chmod(path, 0o600)

    @staticmethod
    def _request(http, method, path, **kwargs):
        with http.stream(method, path, timeout=httpx.Timeout(60 if method == "POST" else 10, connect=5), **kwargs) as result:
            if result.status_code in {401, 403, 402, 429}:
                raise unavailable("customs_access_limited", "关税来源要求验证或已限制查询，请到原网站处理；当前资料已保留。")
            if result.status_code != 200 or "application/json" not in result.headers.get("content-type", ""):
                raise unavailable()
            parts, size = [], 0
            for chunk in result.iter_bytes():
                size += len(chunk)
                if size > 1_048_576:
                    raise unavailable("customs_response_too_large")
                parts.append(chunk)
            payload = json.loads(b"".join(parts))
            if not isinstance(payload, dict):
                raise unavailable("customs_response_invalid")
            return payload, result.headers


OFFICIAL_HOSTS = {"cbsa-asfc.gc.ca", "canada.ca", "laws-lois.justice.gc.ca", "usitc.gov", "ustr.gov", "trade.gov", "cbp.gov", "customs.gov.cn"}
RATE_LABELS = {"base_duty": "基本关税", "additional_duty": "附加关税", "trade_remedy": "贸易救济税",
               "gst": "GST", "tax": "税项", "fee": "费用", "official_fee": "官方费用", "excise_duty": "消费税", "excise_tax": "消费税"}


def official_url(value):
    if not isinstance(value, str) or len(value) > 600 or re.search(r"\s|[<>\\]", value):
        return False
    parsed = urlsplit(value)
    return (parsed.scheme == "https" and not parsed.username and not parsed.password and parsed.port in (None, 443)
            and any(parsed.hostname == host or (parsed.hostname or "").endswith("." + host) for host in OFFICIAL_HOSTS))


def project_reference(raw: dict, value: CustomsInput) -> dict:
    status = raw["dataStatus"]
    if raw.get("mode") != "online_search" or raw.get("testData") is not True or status.get("ready") is not False:
        raise ValueError("unsupported_reference_mode")
    if raw.get("ruleDate") != value.rule_date.isoformat() or not isinstance(status.get("evaluatedAt"), str):
        raise ValueError("reference_date_mismatch")
    datetime.fromisoformat(status["evaluatedAt"].replace("Z", "+00:00"))
    sources = {item["id"]: item for item in raw["sources"]}
    if len(sources) != len(raw["sources"]) or len(sources) > 200:
        raise ValueError("duplicate_source")
    rows = [row for row in raw["results"] if row.get("country") == value.destination]
    if len(rows) != 1:
        raise ValueError("destination_result_missing")
    row = rows[0]
    if len(row.get("rates", [])) > 30:
        raise ValueError("too_many_rates")
    code = row["code"]
    if not isinstance(code, str) or not re.fullmatch(r"\d{6,10}", code) or row.get("codeDigits") != len(code):
        raise ValueError("invalid_code")
    if row.get("status") not in {"candidate", "possible", "manual_review"}:
        raise ValueError("invalid_reference_status")
    projected, referenced = [], {}
    for rate in row.get("rates", []):
        source = sources[rate["sourceId"]]
        if not official_url(source["officialUrl"]):
            raise ValueError("untrusted_rate_source")
        if rate["effectiveFrom"] > value.rule_date.isoformat() or (rate.get("effectiveTo") and rate["effectiveTo"] < value.rule_date.isoformat()):
            raise ValueError("rate_date_not_covered")
        if not source.get("releaseId") or not source.get("edition") or not source.get("retrievedAt"):
            raise ValueError("missing_source_version")
        if not re.fullmatch(r"[\w .:/-]{1,128}", source["releaseId"]) or not re.fullmatch(r"[\w .:/-]{1,80}", source["edition"]):
            raise ValueError("invalid_source_version")
        datetime.fromisoformat(source["retrievedAt"].replace("Z", "+00:00"))
        category = rate.get("category")
        if category not in RATE_LABELS:
            continue
        text = str(rate.get("displayValue", ""))
        # No unconstrained model prose in the bot reply; complex rate formulas
        # and legal conditions must be checked against the linked source.
        shown = text if re.fullmatch(r"\d{1,3}(?:\.\d{1,6})?\s*%|Free|免税|0", text, re.I) else "按原站条件核对"
        projected.append({"label": RATE_LABELS[category], "value": shown, "source_id": rate["sourceId"]})
        referenced[rate["sourceId"]] = {key: source[key] for key in ("officialUrl", "releaseId", "edition", "retrievedAt")}
    if not projected:
        raise ValueError("rates_missing")
    return {"country": value.destination, "query": value.query, "origin": "CN", "code": code, "rule_date": value.rule_date.isoformat(),
            "test_data": True, "ready": False, "rates": projected[:12], "sources": referenced,
            "review_required": True, "evaluated_at": status["evaluatedAt"]}


def render_reference(value: dict) -> str:
    country = {"CA": "加拿大", "US": "美国"}[value["country"]]
    lines = [f"{country}关税候选参考（待人工复核）", f"规则日期：{value['rule_date']}；候选编码：{value['code']}"]
    lines.append(f"查询资料：{' '.join(value['query'].split())}；原产地：中国")
    lines.extend(f"{rate['label']}：{rate['value']}（候选参考）" for rate in value["rates"])
    lines += ["以上税项不能直接相加作为总税负，也不代表最终归类或应纳税额。附加税、反倾销/反补贴、适用范围及豁免仍需核查。",
              "来源："]
    lines.extend(list(dict.fromkeys(item["officialUrl"] for item in value["sources"].values()))[:4])
    lines.append("来源版次：" + "、".join(dict.fromkeys(item["edition"] for item in value["sources"].values())))
    lines.append("完整条件请在 https://clearddp.com/ 核对。可补充商品属性或发送“重查”，发送“返回报价”继续尾程报价。")
    return "\n".join(lines)
