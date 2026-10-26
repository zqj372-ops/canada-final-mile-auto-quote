"""Single-chat WeCom quote adapter; run with python -m ...wecom_quote_worker.

Only the explicitly configured bot and senders are accepted. Business decisions
and audit records remain in the existing quote service. SQLite contains only
delivery deduplication and unfinished conversation state, never pricing rules.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import signal
import sqlite3
import time
from collections.abc import Callable

from apps.api.auth import CurrentActor
from apps.api.db.repositories.sales_quote_record_repository import SalesQuoteRecordRepository
from apps.api.db.repositories.wecom_bot_config_repository import WeComBotConfigRepository
from apps.api.db.session import get_session_factory
from apps.api.services.ai_quote_service import AIAutoQuoteRequest, calculate_ai_auto_quote
from packages.ai_assistant.quote_extractor import AIExtractedQuoteDraft, build_follow_up_question
from packages.wecom.bot_client import _SilentAIBotLogger
from packages.ai_assistant.service_requirements import mentioned_service_fields
from packages.ai_assistant.quote_scope import scope_decision
from apps.api.services.customs_dialogue import customs_turn, is_customs_intent
from apps.api.services.schedule_dialogue import schedule_turn, is_schedule_intent
from apps.api.services.logistics_knowledge import knowledge_turn, is_knowledge_intent, SCOPE_REPLY as BOT_SCOPE_REPLY

LOG = logging.getLogger(__name__)
CONVERSATION_IDLE_SECONDS = 5 * 60
CONTEXT_TABLES = ("sessions", "customs_sessions", "knowledge_sessions", "schedule_sessions")
HELP = (
    "可以直接把送货地址和邮编、货物件数、包装、尺寸或体积、总重量发给我，我来核对加拿大尾程报价；缺什么再补什么。"
    "未说明时按私人地址、不需要预约/尾板/手叉车处理，有其他要求请告诉我。\n"
    "也可以随时问物流和关务问题，比如“尾板怎么用”“DDP和DAP有什么区别”。提问不会清空你的报价资料。\n"
    "发送“查关税”查询中国原产商品出口美国/加拿大的关税候选参考；也可以问“上海到加拿大温哥华下周船期”，或发送“船期菜单”按序号查询 ONE/COSCO 公开船期。"
    "“返回报价”继续尾程报价，“新报价”开始新的一票。连续5分钟未回复，当前业务会话自动重置。"
)
UNCERTAIN = "上一条处理曾中断，结果需要人工核对；为避免重复报价，不会自动重算。请核对报价记录后发送新的询价。"
QUOTE_DEFAULTS = {
    "address_type": ("private", "私人地址"),
    "requires_appointment": ("false", "不需要预约"),
    "requires_liftgate": ("false", "不需要尾板"),
    "requires_pallet_jack": ("false", "不需要手叉车"),
}


def with_quote_defaults(message: str, *, channel_label: str = "企微") -> tuple[str, str]:
    """Use authorized defaults only for omitted facts, never uncertain mentions.

    Keep this out of the conversation state so a later customer supplement can
    supersede a default. The existing confirmed-field parser applies the values
    deterministically, and the audit input labels their source explicitly.
    """
    mentioned = mentioned_service_fields(message)
    if re.search(
        r"地址类型|住宅|私人|民宅|住家|商业|商用|工厂|仓库|"
        r"\b(?:address_type|address\s+type|commercial|residential|private|"
        r"rural_residential|business|warehouse|factory|house|home)\b",
        message, re.I,
    ):
        mentioned.add("address_type")
    defaults = {field: pair for field, pair in QUOTE_DEFAULTS.items() if field not in mentioned}
    if not defaults:
        return message, ""
    fields = "\n".join(f"{field}={value}" for field, (value, _) in defaults.items())
    note = "本次未说明的条件按默认值处理：" + "、".join(label for _, label in defaults.values()) + "。"
    return f"{message}\n\n{channel_label}授权默认条件（仅用于原文未说明的字段）：\n{fields}", note


def digest(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


class State:
    def __init__(self, directory: Path):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory = directory
        self.lock = (directory / "worker.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise RuntimeError("Another WeCom worker already owns this state directory") from None
        self.db = sqlite3.connect(directory / "state.sqlite3")
        os.chmod(directory / "state.sqlite3", 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, conversation TEXT NOT NULL, status TEXT NOT NULL,
                reply TEXT, created REAL NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, message TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS customs_sessions (
                id TEXT PRIMARY KEY, draft_json TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS knowledge_sessions (
                id TEXT PRIMARY KEY, draft_json TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS schedule_sessions (
                id TEXT PRIMARY KEY, draft_json TEXT NOT NULL, updated REAL NOT NULL);
        """)
        if "draft_json" not in {row[1] for row in self.db.execute("PRAGMA table_info(sessions)")}:
            self.db.execute("ALTER TABLE sessions ADD COLUMN draft_json TEXT")
        with self.db:
            self.db.execute("UPDATE events SET status='interrupted',reply=? WHERE status='processing'", (UNCERTAIN,))

    def close(self):
        self.db.close()
        self.lock.close()

    def event(self, key):
        return self.db.execute("SELECT * FROM events WHERE id=?", (key,)).fetchone()

    def context_live(self, conversation):
        # All business modes share one idle window, including paused drafts.
        updated = self.db.execute(
            "SELECT MAX(updated) FROM (" + " UNION ALL ".join(
                f"SELECT updated FROM {table} WHERE id=?" for table in CONTEXT_TABLES
            ) + ")", (conversation,) * len(CONTEXT_TABLES),
        ).fetchone()[0]
        return updated is not None and updated > time.time() - CONVERSATION_IDLE_SECONDS

    def expire_context(self, conversation):
        if self.context_live(conversation):
            return False
        removed = 0
        with self.db:
            for table in CONTEXT_TABLES:
                removed += self.db.execute(f"DELETE FROM {table} WHERE id=?", (conversation,)).rowcount
        return bool(removed)

    def touch_context(self, conversation):
        now = time.time()
        for table in CONTEXT_TABLES:
            self.db.execute(f"UPDATE {table} SET updated=? WHERE id=?", (now, conversation))

    def begin(self, key, conversation):
        expired = self.expire_context(conversation)
        with self.db:
            self.db.execute("INSERT INTO events VALUES (?,?, 'processing', NULL,?,?)", (key, conversation, time.time(), time.time()))
            self.touch_context(conversation)
        return expired

    def finish(self, key, reply, conversation, continuation: str | None, draft: dict | None = None, *, customs: dict | None = None, knowledge: dict | None = None, schedule: dict | None = None):
        with self.db:
            self.db.execute("UPDATE events SET reply=?,status='ready',updated=? WHERE id=?", (reply, time.time(), key))
            if continuation is not None:
                self.db.execute("INSERT OR REPLACE INTO sessions (id,message,updated,draft_json) VALUES (?,?,?,?)",
                                (conversation, continuation, time.time(), json.dumps(draft, ensure_ascii=False) if draft else None))
            if customs is not None:
                self.db.execute("INSERT OR REPLACE INTO customs_sessions VALUES (?,?,?)",
                                (conversation, json.dumps(customs, ensure_ascii=False), time.time()))
            if knowledge is not None:
                self.db.execute("INSERT OR REPLACE INTO knowledge_sessions VALUES (?,?,?)",
                                (conversation, json.dumps(knowledge, ensure_ascii=False), time.time()))
            if schedule is not None:
                self.db.execute("INSERT OR REPLACE INTO schedule_sessions VALUES (?,?,?)",
                                (conversation, json.dumps(schedule, ensure_ascii=False), time.time()))
            self.touch_context(conversation)

    def schedule(self, conversation, *, include_inactive=False):
        row = self.db.execute("SELECT * FROM schedule_sessions WHERE id=?", (conversation,)).fetchone()
        if not row or not self.context_live(conversation):
            return None
        try:
            value = json.loads(row['draft_json'])
            return value if isinstance(value, dict) and value.get('version') == 1 and (value.get('active') or include_inactive) else None
        except ValueError:
            return None

    def knowledge(self, conversation):
        row = self.db.execute("SELECT * FROM knowledge_sessions WHERE id=?", (conversation,)).fetchone()
        if not row or not self.context_live(conversation):
            return None
        try:
            value = json.loads(row["draft_json"])
            return value if isinstance(value, dict) and value.get("version") == 1 and value.get("active") else None
        except ValueError:
            return None

    def customs(self, conversation):
        row = self.db.execute("SELECT * FROM customs_sessions WHERE id=?", (conversation,)).fetchone()
        if not row or not self.context_live(conversation):
            return None
        try:
            value = json.loads(row["draft_json"])
            return value if isinstance(value, dict) and value.get("version") == 1 and value.get("active") else None
        except ValueError:
            return None

    def sent(self, key):
        with self.db:
            event = self.event(key)
            self.db.execute("UPDATE events SET status='replied',updated=? WHERE id=?", (time.time(), key))
            if event and event["status"] != "replied":
                self.touch_context(event["conversation"])

    def previous(self, conversation):
        row = self.db.execute("SELECT * FROM sessions WHERE id=?", (conversation,)).fetchone()
        return row["message"] if row and self.context_live(conversation) else ""

    def draft(self, conversation):
        row = self.db.execute("SELECT draft_json,updated FROM sessions WHERE id=?", (conversation,)).fetchone()
        if not row or not self.context_live(conversation) or not row["draft_json"]:
            return None
        try:
            return AIExtractedQuoteDraft.model_validate_json(row["draft_json"]).model_dump(mode="json")
        except ValueError:
            return None  # Legacy/raw text remains available; never trust corrupt state.


class QuoteWorker:
    def __init__(self, *, bot_id: str, allowed_users: set[str], state: State, client, quote: Callable, supports_drafts: bool = False):
        if not bot_id or not allowed_users:
            raise ValueError("Explicit bot identity and sender allowlist are required")
        self.bot_id, self.allowed_users = bot_id, allowed_users
        self.state, self.client, self.quote = state, client, quote
        self.supports_drafts = supports_drafts
        self.queue = asyncio.Queue(maxsize=20)
        self.pending: set[str] = set()
        self.concurrency = 4
        self._slots = asyncio.Semaphore(self.concurrency)
        self._conversation_locks: dict[str, asyncio.Lock] = {}
        self._active: set[str] = set()
        self._tasks: set[asyncio.Task] = set()
        self.status = {"connected": False, "received": 0, "replied": 0, "errors": 0}

    def write_status(self, **updates):
        self.status.update(updates, updated_at=time.time())
        temporary = self.state.directory / "status.tmp"
        temporary.write_text(json.dumps(self.status), encoding="utf-8")
        temporary.replace(self.state.directory / "status.json")

    def identify(self, frame):
        body = frame.get("body") or {}
        sender = (body.get("from") or {}).get("userid")
        if (body.get("aibotid") != self.bot_id or body.get("chattype") != "single"
                or not self.sender_allowed(sender) or not body.get("msgid")
                or not (frame.get("headers") or {}).get("req_id")):
            return None
        return digest(self.bot_id, sender, body["msgid"]), digest(self.bot_id, sender)

    def sender_allowed(self, sender):
        return isinstance(sender, str) and (
            sender in self.allowed_users or f"sha256:{digest(sender)}" in self.allowed_users
        )

    async def send(self, frame, key, text, *, finish=True):
        # The protocol bounds UTF-8 bytes, not Python character count. Fail closed
        # instead of truncating prices or conditions halfway through a quote.
        if len(text.encode("utf-8")) > 18000:
            text = "报价内容过长，请在报价工作台查看完整结果及适用条件。"
        ack = await self.client.reply_stream(frame, key[:32], text, finish=finish)
        if not isinstance(ack, dict) or ack.get("errcode") != 0:
            raise RuntimeError("WeComReplyNotAcknowledged")

    async def receive(self, frame):
        body = frame.get("body") or {}
        sender = (body.get("from") or {}).get("userid")
        self.write_status(
            callbacks=self.status.get("callbacks", 0) + 1,
            last_callback_at=time.time(),
            callback_bot_matches=body.get("aibotid") == self.bot_id,
            callback_sender_allowed=self.sender_allowed(sender),
            callback_sender_fingerprint=digest(sender) if isinstance(sender, str) else None,
            callback_content_fingerprint=digest((body.get("text") or {}).get("content", "")),
            callback_single_chat=body.get("chattype") == "single",
            callback_has_message_id=bool(body.get("msgid")),
            callback_has_request_id=bool((frame.get("headers") or {}).get("req_id")),
        )
        identity = self.identify(frame)
        if not identity:
            return
        key, _ = identity
        if key in self.pending or (self.state.event(key) and self.state.event(key)["status"] == "replied"):
            return
        # Dispatched tasks waiting for a conversation/slot still count towards
        # the waiting buffer. Draining the inbox must not create an unbounded queue.
        if self.queue.full() or len(self.pending) - len(self._active) >= self.queue.maxsize:
            await self.send(frame, key, "当前询价较多，请稍后重新发送。")
            return
        # Reserve before awaiting the SDK so simultaneous redeliveries cannot enqueue twice.
        self.pending.add(key)
        try:
            self.queue.put_nowait(frame)
            self.write_status(received=self.status["received"] + 1, last_received_at=time.time())
        except Exception:
            self.pending.discard(key)
            raise

    async def process(self, frame):
        identity = self.identify(frame)
        if identity is None:
            return
        key, conversation = identity
        old = self.state.event(key)
        if old:
            if old["status"] != "replied":
                self.state.expire_context(conversation)
                await self.send(frame, key, old["reply"] or UNCERTAIN)
                self.state.sent(key)
            return
        expired = self.state.begin(key, conversation)
        content = ((frame["body"].get("text") or {}).get("content") or "").strip()
        # Users often copy the quoted command from the help text. Unwrap only
        # complete control commands, never alter ordinary inquiry text.
        commands = {"连接测试", "测试", "ping", "新报价", "重新开始", "重置",
                    "你好", "您好", "hello", "hi", "帮助", "菜单", "查关税", "新关税查询", "返回报价", "退出关税", "物流知识", "关务知识", "知识库",
                    "查船期", "船期查询", "新船期查询", "返回船期", "退出船期", "更多船期", "刷新船期", "船期菜单", "取消船期菜单"}
        for opening, closing in (("「", "」"), ("『", "』"), ("“", "”"), ('"', '"'), ("'", "'")):
            if content.startswith(opening) and content.endswith(closing) and content[1:-1].strip() in commands:
                content = content[1:-1].strip()
                break
        if content in {"菜单", "帮助"} and self.state.schedule(conversation):
            content = "船期菜单"
        continuation = None
        draft = None
        customs = None
        knowledge = None
        schedule = None
        if frame["body"].get("msgtype") != "text":
            reply = "目前支持文字询价。图片、语音和文件还未接入解析，请把货物和地址资料以文字发送。"
        elif content in {"连接测试", "测试", "ping"}:
            reply = "连接测试成功：已收到你的消息，服务器自动回复正常。\n" + HELP
        elif content in {"新报价", "重新开始", "重置"}:
            reply, continuation = "已开始新的一票。" + HELP, ""
            customs = {"version": 1, "active": False}
            knowledge = {"version": 1, "active": False}
            schedule = {"version": 1, "active": False}
        elif content in {"返回报价", "退出关税", "退出船期"}:
            reply = ("已返回尾程报价，原有报价草稿已保留。请继续补充资料。" if self.state.previous(conversation)
                     else "已返回尾程报价，请发送这票货的地址和货物资料。")
            customs = {"version": 1, "active": False}
            knowledge = {"version": 1, "active": False}
            schedule = {"version": 1, "active": False}
        elif content in {"你好", "您好", "hello", "hi", "帮助", "菜单", "你能做什么", "你会什么"}:
            reply = HELP
        elif content.lower().rstrip("。.!！") in {"谢谢", "谢谢你", "感谢", "辛苦了", "多谢", "thank you", "thanks"}:
            reply = "不客气，有物流或关务问题随时问我。5分钟内可以继续补充这票货的信息，超时后会开始新会话。"
        elif not content or len(content) > 6000:
            reply = "请发送不超过 6000 字的文字询价。"
        elif is_schedule_intent(content, self.state.schedule(conversation)) and not is_customs_intent(content):
            try:
                await self.send(frame, key, "已收到，正在核对港口、日期和船公司公开船期。", finish=False)
            except Exception:
                self.write_status(errors=self.status["errors"] + 1)
            try:
                reply, schedule = await asyncio.to_thread(schedule_turn, content, self.state.schedule(conversation, include_inactive=True))
            except Exception as exc:
                LOG.warning("Schedule query failed: %s", type(exc).__name__)
                reply = "船期查询暂时未完成，已有资料已保留。请稍后重试，或补充港口和出发日期。"
                self.write_status(errors=self.status["errors"] + 1)
        elif is_knowledge_intent(content, self.state.knowledge(conversation)) and not is_customs_intent(content):
            try:
                reply, knowledge = await asyncio.to_thread(knowledge_turn, content, self.state.knowledge(conversation))
            except Exception as exc:
                LOG.warning("Knowledge lookup failed: %s", type(exc).__name__)
                reply = "这部分资料暂时无法读取，已有报价和关税资料都还在，请稍后再问。"
                self.write_status(errors=self.status["errors"] + 1)
        elif is_customs_intent(content) or self.state.customs(conversation):
            knowledge = {"version": 1, "active": False}
            if self.state.schedule(conversation):
                schedule = {**self.state.schedule(conversation), "active": False}
            previous_customs = self.state.customs(conversation)
            try:
                await self.send(frame, key, "已收到，正在核对关税查询资料与参考来源。", finish=False)
            except Exception:
                self.write_status(errors=self.status["errors"] + 1)
            try:
                reply, customs = await asyncio.to_thread(customs_turn, content, previous_customs)
            except Exception as exc:
                LOG.warning("Customs query failed: %s", type(exc).__name__)
                reply = "关税查询暂时无法完成，已有资料已保留，请稍后重试。"
                self.write_status(errors=self.status["errors"] + 1)
        elif (scope := scope_decision(content, has_draft=bool(self.state.previous(conversation)))) != "quote":
            reply = HELP if scope == "help" else BOT_SCOPE_REPLY
        else:
            knowledge = {"version": 1, "active": False}
            previous = self.state.previous(conversation)
            message = f"{previous}\n客户补充：{content}" if previous else content
            if len(message) > 12000:
                reply, continuation = "补充资料过长，请发送“新报价”后重新整理完整资料。", ""
            else:
                try:
                    await self.send(frame, key, "已收到，正在核对询价资料与报价规则。", finish=False)
                except Exception:
                    self.write_status(errors=self.status["errors"] + 1)
                try:
                    previous_draft = self.state.draft(conversation) if self.supports_drafts else None
                    if previous_draft is not None:
                        result = await asyncio.to_thread(self.quote, message, previous_extraction=previous_draft, current_message=content)
                    else:
                        result = await asyncio.to_thread(self.quote, message)
                    if self.supports_drafts and result.missing_fields:
                        draft = result.extraction.model_dump(mode="json")
                    reply = result.customer_reply or "这票需要人工核对，请查看报价工作台。"
                    continuation = message if result.missing_fields else ""
                except Exception as exc:
                    LOG.warning("Quote failed: %s", type(exc).__name__)
                    reply = "报价服务暂时无法完成处理，请人工核对报价记录；当前未确认可用价格。"
                    self.write_status(errors=self.status["errors"] + 1)
                    continuation = None  # Preserve the last usable draft on transient failures.
        if expired:
            reply = "连续5分钟未回复，上一轮业务会话已重置。\n" + reply
        self.state.finish(key, reply, conversation, continuation, draft, customs=customs, knowledge=knowledge, schedule=schedule)
        await self.send(frame, key, reply)
        self.state.sent(key)
        self.write_status(replied=self.status["replied"] + 1, last_replied_at=time.time())

    async def _consume_frame(self, frame):
        body = frame.get("body") or {}
        key = digest(self.bot_id, (body.get("from") or {}).get("userid"), body.get("msgid"))
        try:
            identity = self.identify(frame)
            if identity is None:
                return
            key, conversation = identity
            # FIFO per sender, including resets, customs and delivery retries.
            # Wait for this sender BEFORE taking a global slot so one sender's
            # backlog cannot occupy all four slots. Locks are bounded by the
            # authorized senders of this worker and live only for its lifetime.
            lock = self._conversation_locks.setdefault(conversation, asyncio.Lock())
            async with lock:
                async with self._slots:
                    self._active.add(key)
                    try:
                        await self.process(frame)  # Rechecks current authorization.
                    finally:
                        self._active.discard(key)
        except Exception as exc:
            # A ready reply survives send failures and is reused on redelivery.
            LOG.warning("Message processing failed: %s", type(exc).__name__)
            self.write_status(errors=self.status["errors"] + 1)

    def _message_done(self, task, key):
        # A task cancelled before its first instruction never enters its finally
        # block, so inbox accounting belongs to the completion callback.
        self._tasks.discard(task)
        self.pending.discard(key)
        self.queue.task_done()
        if not task.cancelled() and task.exception() is not None:
            LOG.warning("Message task failed: %s", type(task.exception()).__name__)

    async def consume(self):
        try:
            while True:
                frame = await self.queue.get()
                body = frame.get("body") or {}
                key = digest(self.bot_id, (body.get("from") or {}).get("userid"), body.get("msgid"))
                task = asyncio.create_task(self._consume_frame(frame))
                self._tasks.add(task)
                task.add_done_callback(lambda done, key=key: self._message_done(done, key))
        finally:
            # Both shared and personal runtimes await this consumer before
            # closing SQLite. No message coroutine may use it after shutdown.
            tasks = tuple(self._tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            while not self.queue.empty():
                frame = self.queue.get_nowait()
                body = frame.get("body") or {}
                self.pending.discard(digest(self.bot_id, (body.get("from") or {}).get("userid"), body.get("msgid")))
                self.queue.task_done()


def load_bot(config_id):
    with get_session_factory()() as db:
        repo = WeComBotConfigRepository(db)
        bot = repo.get_config(config_id)
        if not bot or not bot.enabled or bot.bot_type != "wecom_aibot_long_connection":
            raise RuntimeError("Configured WeCom long-connection bot is unavailable")
        secret = repo.decrypt_secret_value(bot)
        if not bot.bot_id or not secret:
            raise RuntimeError("Configured WeCom credentials are incomplete")
        return bot.bot_id, secret, bot.name


def manual_review_reply(result):
    """Explain structured business blockers without exposing raw diagnostics."""
    if result.missing_fields:
        return "资料尚未齐全，暂时无法自动报价。\n" + build_follow_up_question(result.missing_fields, result.extraction)
    quote = result.quote_result
    tags = set(quote.risk_tags) if quote else set()
    reasons, actions = [], []
    if quote and "zone_not_found" in tags:
        destination = "，".join(" ".join(str(v).split())[:80] for v in
                               (quote.postal_code, quote.city, quote.province) if v) or "当前目的地"
        if quote.matched_by == "city_zone_prefix_not_configured":
            reasons.append(f"已找到城市规则，但 {destination} 的邮编前缀不在该城市的有效配送分区配置中。")
        elif quote.matched_by == "city_fallback_expected_origin_not_found":
            reasons.append(f"{destination} 已有的分区记录，其始发仓与目的省份要求不符。")
        elif "zone_rule_province_mismatch" in tags:
            reasons.append(f"{destination} 未找到可信分区，已有候选记录存在省份冲突。")
        else:
            reasons.append(f"{destination} 未匹配到配送分区，无法选择对应运价。")
        actions.append("请核对完整地址、邮编和城市；如信息无误，需报价人员补充分区和有效运价，或向承运商人工询价。")
    if quote and "zone_price_not_found" in tags:
        origin = {"toronto": "多伦多", "calgary": "卡尔加里"}.get(quote.origin, "当前始发仓")
        detail = "、".join(v for v in (origin, f"Zone {quote.zone}" if quote.zone is not None else "",
                          f"当前资料推导的 {quote.billing_pallets} 托档" if quote.billing_pallets is not None else "") if v)
        reasons.append(f"报价表缺少 {detail} 的运价。")
        actions.append("请报价人员核对计费托数，并取得该分区、托数对应的有效运价。")
    issues = {
        "zone_price_disabled": ("该配送分区已暂停自动报价。", "请报价人员确认该线路当前是否可承接，并核实有效运价。"),
        "split_record_conflict": ("目的地匹配到多个配送分区，无法唯一确定。", "请核对完整地址和邮编，由报价人员确认正确的配送分区。"),
        "origin_matrix_mismatch": ("目的省份要求的始发仓与现有分区运价来源冲突。", "请报价人员确认正确始发仓及其对应分区，核实后再报价。"),
        "postal_prefix_missing": ("无法识别加拿大邮编前缀。", "请提供完整、正确的加拿大邮编及送货地址。"),
        "long_piece_count_suspicious": ("超长件规则推导出的计费托数异常。", "请核对实际件数、最长边和实际托盘数，避免把重量或货品数量当成运输件数。"),
        "missing_billable_pallet_basis": ("缺少可用于确定计费托数的货物资料。", "请补充总体积（CBM）、总重（KG）或实际托盘数。"),
        "billing_pallets_manual_required": ("当前货物资料无法自动确定计费托数。", "请核对包装、体积、重量、尺寸及实际托盘数，由报价人员确认计费方式。"),
        "flat_rate_packaging_required": ("这类特殊软包装货物需按整票或整托人工确认价格。", "请补充包装方式、是否可堆叠及实际托盘数，交由报价人员询价。"),
    }
    for tag, (reason, action) in issues.items():
        if tag in tags:
            reasons.append(reason)
            actions.append(action)
    notes = result.extraction.validation_notes
    if any(note.startswith("cargo_agent_failed:") or note == "cargo_agent_deadline_exceeded" for note in notes):
        reasons.append("货物资料识别未完整通过校验，当前识别的数量、体积或重量仍需复核。")
        actions.append("请分别注明总件数、总体积（CBM）、总重（KG）、包装及实际托盘数，核对后再确认计费托数。")
    if any(note.startswith("address_agent_failed:") or note == "address_agent_deadline_exceeded" for note in notes):
        reasons.append("地址资料识别未完整通过校验。")
        actions.append("请核对送货地址、城市、省份和完整邮编。")
    if not reasons:
        reasons.append("系统尚未返回可识别的具体拦截原因。")
        actions.append("请报价人员按报价编码查看对应记录，核实未通过的规则后再确认价格。")
    if "rural_fsa_secondary_confirmation" in tags:
        actions.append("该邮编还需核实完整地址、卡车准入及可能的偏远附加费。")
    return "暂时无法自动报价。\n原因：\n" + "\n".join(f"- {v}" for v in dict.fromkeys(reasons)) + \
        "\n处理：\n" + "\n".join(f"- {v}" for v in dict.fromkeys(actions))


def save_coded_reply(db, result, actor, quote_message):
    """Add a persistent customer reference using the existing unique record key."""
    if result.quote_result is None:
        return
    record = SalesQuoteRecordRepository(db).get_latest_record_by_quote_id(result.quote_result.quote_id)
    if record is not None:
        db.refresh(record, with_for_update=True)
    if (record is None or record.actor_name != actor.name or record.actor_role != actor.role
            or record.actor_user_id != actor.user_id or record.actor_api_key_id != actor.api_key_id
            or record.customer_message != quote_message
            or record.result_json.get("quote_result") != result.quote_result.model_dump(mode="json")):
        raise RuntimeError("WeComQuoteRecordUnavailable")
    # One-to-one mapping, no random collisions, truncation, or wraparound.
    if not 1 <= record.id < 90_000_000:
        raise RuntimeError("WeComQuoteCodeExhausted")
    code = str(10_000_000 + record.id)
    prefix = f"报价编码：{code}\n"
    reply = result.customer_reply or "这票需要人工核对，请查看报价工作台。"
    if not reply.startswith(prefix):
        reply = prefix + reply
    result.customer_reply = reply
    result.quote_result.sales_note = reply
    record.customer_reply = reply
    record.result_json = {**record.result_json, "quote_code": code, "customer_reply": reply,
                          "quote_result": result.quote_result.model_dump(mode="json")}
    db.commit()


def quote_for_bot(config_id, expected_bot_id, message, *, previous_extraction=None, current_message=None):
    with get_session_factory()() as db:
        bot = WeComBotConfigRepository(db).get_config(config_id)
        if not bot or not bot.enabled or bot.bot_id != expected_bot_id:
            raise RuntimeError("WeCom bot disabled or changed")
        # A restricted integration principal: no user impersonation, API token,
        # record lookup, admin action, learning publication or arbitrary tools.
        actor = CurrentActor(api_key_id=None, name=f"企微自动报价：{bot.name}", role="sales")
        quote_message, default_note = with_quote_defaults(message)
        kwargs = {} if previous_extraction is None else {
            "previous_extraction": previous_extraction,
            "current_message": (current_message or "") + quote_message[len(message):],
        }
        result = calculate_ai_auto_quote(db, AIAutoQuoteRequest(customer_message=quote_message), actor, notify_manual=False, **kwargs)
        if result.manual_review_required:
            result.customer_reply = manual_review_reply(result)
        if default_note:
            result.customer_reply = (result.customer_reply or "这票需要人工核对，请查看报价工作台。") + "\n\n" + default_note
        save_coded_reply(db, result, actor, quote_message)
        return result


async def run():
    from aibot import WSClient, WSClientOptions

    config_id = int(os.environ["WECOM_QUOTE_BOT_CONFIG_ID"])
    allowed = {s.strip() for s in os.environ["WECOM_QUOTE_ALLOWED_USERS"].split(",") if s.strip()}
    bot_id, secret, _ = load_bot(config_id)
    state = State(Path(os.getenv("WECOM_QUOTE_STATE_DIR", "outputs/wecom_quote")))
    client = WSClient(WSClientOptions(bot_id=bot_id, secret=secret, max_reconnect_attempts=-1, logger=_SilentAIBotLogger()))
    worker = QuoteWorker(bot_id=bot_id, allowed_users=allowed, state=state, client=client,
                         quote=lambda message, **kwargs: quote_for_bot(config_id, bot_id, message, **kwargs), supports_drafts=True)
    client.on("message", worker.receive)
    client.on("authenticated", lambda: worker.write_status(connected=True, authenticated_at=time.time()))
    client.on("disconnected", lambda *_: worker.write_status(connected=False))
    client.on("error", lambda *_: worker.write_status(errors=worker.status["errors"] + 1))
    stopped = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stopped.set)
    consumer = asyncio.create_task(worker.consume())
    worker.write_status(connected=False)
    try:
        await client.connect()
        while not stopped.is_set():
            worker.write_status()
            try:
                await asyncio.wait_for(stopped.wait(), timeout=15)
            except asyncio.TimeoutError:
                pass
    finally:
        client.disconnect()
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)
        worker.write_status(connected=False)
        state.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="Read redacted worker health without connecting")
    args = parser.parse_args()
    if args.status:
        path = Path(os.getenv("WECOM_QUOTE_STATE_DIR", "outputs/wecom_quote")) / "status.json"
        status = json.loads(path.read_text()) if path.exists() else {"connected": False}
        status["fresh"] = time.time() - status.get("updated_at", 0) < 60
        print(json.dumps(status))
        raise SystemExit(0 if status["fresh"] and status["connected"] else 1)
    os.umask(0o077)
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(run())


if __name__ == "__main__":
    main()
