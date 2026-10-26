import asyncio
from types import SimpleNamespace

import pytest

from apps.api.services.wecom_quote_worker import QuoteWorker, State, digest, manual_review_reply, save_coded_reply, with_quote_defaults
from packages.ai_assistant.quote_extractor import AIExtractedQuoteDraft, apply_deterministic_extraction, missing_required_fields


class FakeClient:
    def __init__(self):
        self.sent = []
        self.fail_final = False

    async def reply_stream(self, frame, stream_id, text, *, finish):
        self.sent.append((frame, stream_id, text, finish))
        if finish and self.fail_final:
            raise TimeoutError("ack lost")
        return {"errcode": 0}


def frame(msg="m1", text="2箱100kg", sender="owner", **body):
    return {"headers": {"req_id": f"req-{msg}"}, "body": {
        "aibotid": "bot", "msgid": msg, "from": {"userid": sender},
        "chattype": "single", "msgtype": "text", "text": {"content": text}, **body}}


@pytest.fixture
def setup_worker(tmp_path):
    states = []

    def build(quote=None):
        state = State(tmp_path)
        states.append(state)
        calls = []

        def default_quote(message):
            calls.append(message)
            return SimpleNamespace(customer_reply="规则报价 USD 123.00", missing_fields=[])

        worker = QuoteWorker(bot_id="bot", allowed_users={"owner", "second"}, state=state,
                             client=FakeClient(), quote=quote or default_quote)
        return worker, calls

    yield build
    for state in states:
        try:
            state.close()
        except Exception:
            pass


def test_sender_bot_group_and_malformed_callbacks_are_ignored(setup_worker):
    worker, calls = setup_worker()

    async def run():
        for event in [frame(sender="stranger"), frame(aibotid="other"), frame(chattype="group"), frame(msgid=""), {"body": {}}]:
            await worker.receive(event)
        assert worker.queue.empty()
    asyncio.run(run())
    assert calls == worker.client.sent == []


def test_connection_test_and_nontext_do_not_call_quote(setup_worker):
    worker, calls = setup_worker()

    async def run():
        await worker.process(frame(text="连接测试"))
        await worker.process(frame("m2", msgtype="mixed"))
    asyncio.run(run())
    assert calls == []
    assert "自动回复正常" in worker.client.sent[0][2]
    assert "文字" in worker.client.sent[1][2]


def test_duplicate_events_never_recalculate_or_resend_after_ack(setup_worker):
    worker, calls = setup_worker()

    async def run():
        await asyncio.gather(worker.receive(frame()), worker.receive(frame()))
        assert worker.queue.qsize() == 1
        event = worker.queue.get_nowait()
        await worker.process(event)
        await worker.process(event)
    asyncio.run(run())
    assert len(calls) == 1
    assert len([s for s in worker.client.sent if s[3]]) == 1


def test_failed_final_ack_reuses_saved_reply_without_quote(setup_worker):
    worker, calls = setup_worker()
    worker.client.fail_final = True
    with pytest.raises(TimeoutError):
        asyncio.run(worker.process(frame()))
    worker.client.fail_final = False
    asyncio.run(worker.process(frame()))
    assert len(calls) == 1
    assert worker.state.event(digest("bot", "owner", "m1"))["status"] == "replied"
    finals = [s[2] for s in worker.client.sent if s[3]]
    assert finals == ["规则报价 USD 123.00"] * 2


def test_restart_does_not_repeat_interrupted_quote(tmp_path):
    state = State(tmp_path)
    state.begin(digest("bot", "owner", "m1"), digest("bot", "owner"))
    state.close()
    state = State(tmp_path)
    try:
        worker = QuoteWorker(bot_id="bot", allowed_users={"owner"}, state=state,
                             client=FakeClient(), quote=lambda _: pytest.fail("must not recalculate"))
        asyncio.run(worker.process(frame()))
        assert "中断" in worker.client.sent[0][2]
    finally:
        state.close()


def test_missing_fields_continue_only_same_sender_until_reset(setup_worker):
    calls = []

    def quote(message):
        calls.append(message)
        return SimpleNamespace(customer_reply="请补充重量", missing_fields=["weight_kg"])

    worker, _ = setup_worker(quote)

    async def run():
        await worker.process(frame(text="10箱"))
        await worker.process(frame("m2", text="100kg"))
        await worker.process(frame("m3", text="另一票1箱", sender="second"))
        await worker.process(frame("m4", text="新报价"))
        await worker.process(frame("m5", text="新票20箱"))
    asyncio.run(run())
    assert calls == ["10箱", "10箱\n客户补充：100kg", "另一票1箱", "新票20箱"]


def test_completed_quote_does_not_leak_into_next_shipment(setup_worker):
    worker, calls = setup_worker()

    async def run():
        await worker.process(frame(text="第一票1箱"))
        await worker.process(frame("m2", text="第二票2箱"))
    asyncio.run(run())
    assert calls == ["第一票1箱", "第二票2箱"]


def test_single_worker_lock_released_on_shutdown(tmp_path):
    state = State(tmp_path)
    with pytest.raises(RuntimeError, match="Another WeCom worker"):
        State(tmp_path)
    state.close()
    State(tmp_path).close()


def test_nonzero_ack_is_not_delivery_success(setup_worker):
    worker, _ = setup_worker()

    async def bad_ack(*args, **kwargs):
        return {"errcode": 40001}

    worker.client.reply_stream = bad_ack
    with pytest.raises(RuntimeError, match="NotAcknowledged"):
        asyncio.run(worker.process(frame(text="连接测试")))
    assert worker.state.event(digest("bot", "owner", "m1"))["status"] == "ready"


def test_quote_failure_exposes_no_exception_and_no_price(setup_worker):
    def quote(message):
        raise RuntimeError("credential-that-must-not-appear")

    worker, _ = setup_worker(quote)
    asyncio.run(worker.process(frame()))
    assert "未确认可用价格" in worker.client.sent[-1][2]
    assert "credential" not in worker.client.sent[-1][2]


def test_verified_callback_fingerprint_accepts_only_that_sender(setup_worker):
    worker, calls = setup_worker()
    worker.allowed_users = {f"sha256:{digest('owner')}"}
    assert worker.identify(frame()) is not None
    assert worker.identify(frame(sender="someone-else")) is None
    assert worker.identify(frame(sender=None)) is None


def test_omitted_quote_conditions_use_authorized_defaults():
    message, note = with_quote_defaults("39箱，6CBM，总重454kg")
    # Even a conflicting model guess cannot override the authorized defaults.
    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(
        address_type="commercial", requires_appointment=True,
        requires_liftgate=True, requires_pallet_jack=True,
    ), message)
    assert draft.address_type == "private"
    assert draft.requires_appointment is draft.requires_liftgate is draft.requires_pallet_jack is False
    assert not {"address_type", "requires_appointment", "requires_liftgate", "requires_pallet_jack"} & missing_required_fields(draft)
    assert (draft.piece_count, draft.cbm, draft.weight_kg) == (39, 6, 454)
    assert "私人地址、不需要预约、不需要尾板、不需要手叉车" in note
    assert "企微授权默认条件" in message


@pytest.mark.parametrize("message", [
    "商业地址，需要尾板，需要手叉车，需要预约",
    "commercial address, lift gate required, pallet jack required, appointment required",
    "address_type=commercial\nrequires_liftgate=true\nrequires_pallet_jack=true\nrequires_appointment=true",
])
def test_explicit_conditions_are_not_replaced_by_defaults(message):
    prepared, note = with_quote_defaults(message)
    assert prepared == message
    assert note == ""
    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(address_type="commercial"), prepared)
    assert draft.address_type == "commercial"
    assert draft.requires_appointment is draft.requires_liftgate is draft.requires_pallet_jack is True


@pytest.mark.parametrize("message", ["是否需要尾板？", "尾板待确认", "需要尾板，不需要尾板"])
def test_uncertain_or_conflicting_service_still_requires_confirmation(message):
    prepared, note = with_quote_defaults(message)
    draft = apply_deterministic_extraction(AIExtractedQuoteDraft(), prepared)
    assert draft.requires_liftgate is None
    assert "requires_liftgate" in missing_required_fields(draft)
    assert "requires_liftgate=false" not in prepared
    assert "不需要尾板" not in note
    assert draft.address_type == "private"
    assert draft.requires_appointment is draft.requires_pallet_jack is False


def test_defaults_do_not_hide_uncertain_address_type():
    prepared, note = with_quote_defaults("地址类型待确认")
    assert "address_type=private" not in prepared
    assert "私人地址" not in note


def manual_result(*tags, matched_by="city_fallback_not_found", notes=()):
    return SimpleNamespace(
        missing_fields=[], extraction=AIExtractedQuoteDraft(validation_notes=list(notes)),
        internal_note="internal diagnostic must stay private",
        quote_result=SimpleNamespace(
            risk_tags=list(tags), matched_by=matched_by, postal_code="J7A 4M9",
            city="Rosemère", province="QC", origin="toronto", zone=2, billing_pallets=10,
            matched_rule="raw diagnostic must stay private",
        ),
    )


def test_manual_reply_explains_destination_blocker_and_failed_cargo_extraction():
    reply = manual_review_reply(manual_result(
        "zone_not_found", notes=["cargo_agent_failed:private model diagnostic"],
    ))
    assert "J7A 4M9，Rosemère，QC 未匹配到配送分区" in reply
    assert "数量、体积或重量仍需复核" in reply
    assert "原因：" in reply and "处理：" in reply
    assert "补充分区和有效运价" in reply
    assert "5150 CBM" not in reply
    assert "private" not in reply and "diagnostic" not in reply


@pytest.mark.parametrize(("tag", "expected"), [
    ("zone_price_not_found", "多伦多、Zone 2、当前资料推导的 10 托档"),
    ("zone_price_disabled", "已暂停自动报价"),
    ("split_record_conflict", "匹配到多个配送分区"),
    ("origin_matrix_mismatch", "始发仓与现有分区运价来源冲突"),
    ("postal_prefix_missing", "无法识别加拿大邮编前缀"),
    ("long_piece_count_suspicious", "超长件规则推导出的计费托数异常"),
    ("missing_billable_pallet_basis", "缺少可用于确定计费托数的货物资料"),
    ("billing_pallets_manual_required", "无法自动确定计费托数"),
    ("flat_rate_packaging_required", "特殊软包装"),
])
def test_manual_reply_has_actionable_business_reason(tag, expected):
    reply = manual_review_reply(manual_result(tag))
    assert expected in reply
    assert "处理：" in reply and "请" in reply


@pytest.mark.parametrize(("matched_by", "tags", "expected"), [
    ("city_zone_prefix_not_configured", ["zone_not_found"], "邮编前缀不在该城市的有效配送分区配置"),
    ("city_fallback_expected_origin_not_found", ["zone_not_found"], "始发仓与目的省份要求不符"),
    ("province_conflict", ["zone_not_found", "zone_rule_province_mismatch"], "省份冲突"),
])
def test_manual_reply_distinguishes_zone_mismatch_subtypes(matched_by, tags, expected):
    assert expected in manual_review_reply(manual_result(*tags, matched_by=matched_by))


@pytest.mark.parametrize("note", ["address_agent_failed:private error", "address_agent_deadline_exceeded"])
def test_manual_reply_explains_address_failure_without_raw_error(note):
    reply = manual_review_reply(manual_result(notes=[note]))
    assert "地址资料识别未完整通过校验" in reply
    assert "private" not in reply


def test_manual_reply_missing_fields_and_unknown_reason_have_honest_fallbacks():
    result = manual_result("unknown_tag")
    reply = manual_review_reply(result)
    assert "尚未返回可识别的具体拦截原因" in reply
    assert "按报价编码查看对应记录" in reply
    assert "diagnostic" not in reply
    result.quote_result = None
    result.missing_fields = ["weight_kg", "requires_liftgate"]
    reply = manual_review_reply(result)
    assert "总重量 kg、是否需要尾板" in reply


def test_manual_reply_keeps_rural_check_as_secondary_action():
    reply = manual_review_reply(manual_result("zone_not_found", "rural_fsa_secondary_confirmation"))
    assert "未匹配到配送分区" in reply and "卡车准入" in reply


def test_later_explicit_supplement_supersedes_previous_defaults(setup_worker):
    prepared_messages = []

    def quote(message):
        prepared, _ = with_quote_defaults(message)
        prepared_messages.append(prepared)
        return SimpleNamespace(customer_reply="请补充邮编", missing_fields=["postal_code"])

    worker, _ = setup_worker(quote)

    async def run():
        await worker.process(frame(text="39箱，6CBM，总重454kg"))
        await worker.process(frame("m2", text="商业地址，需要尾板"))
    asyncio.run(run())
    assert "address_type=private" in prepared_messages[0]
    assert "requires_liftgate=false" in prepared_messages[0]
    assert "address_type=private" not in prepared_messages[1]
    assert "requires_liftgate=false" not in prepared_messages[1]
    assert "企微授权默认条件" not in worker.state.previous(digest("bot", "owner"))


def coded_reply_fixture(monkeypatch, record_id=1):
    from unittest.mock import Mock
    from apps.api.auth import CurrentActor

    actor = CurrentActor(api_key_id=None, name="fixture bot", role="sales")
    quote = SimpleNamespace(quote_id="internal-quote", sales_note="规则报价 USD 123.00")
    quote.model_dump = lambda **_: {"quote_id": quote.quote_id, "sales_note": quote.sales_note}
    result = SimpleNamespace(quote_result=quote, customer_reply=quote.sales_note)
    record = SimpleNamespace(id=record_id, actor_name=actor.name, actor_role=actor.role,
                             actor_user_id=None, actor_api_key_id=None, customer_message="询价",
                             result_json={"quote_result": quote.model_dump()})
    repository = Mock()
    repository.get_latest_record_by_quote_id.return_value = record
    monkeypatch.setattr("apps.api.services.wecom_quote_worker.SalesQuoteRecordRepository", lambda _: repository)
    return Mock(), result, actor, record


@pytest.mark.parametrize(("record_id", "expected"), [(1, "10000001"), (89_999_999, "99999999")])
def test_quote_code_is_eight_digits_and_stable(monkeypatch, record_id, expected):
    db, result, actor, record = coded_reply_fixture(monkeypatch, record_id)
    save_coded_reply(db, result, actor, "询价")
    assert result.customer_reply == f"报价编码：{expected}\n规则报价 USD 123.00"
    assert record.result_json["quote_code"] == expected
    save_coded_reply(db, result, actor, "询价")
    assert result.customer_reply.count("报价编码：") == 1


@pytest.mark.parametrize("record_id", [0, 90_000_000])
def test_quote_code_never_wraps_or_exceeds_eight_digits(monkeypatch, record_id):
    db, result, actor, _ = coded_reply_fixture(monkeypatch, record_id)
    with pytest.raises(RuntimeError, match="CodeExhausted"):
        save_coded_reply(db, result, actor, "询价")
    db.commit.assert_not_called()
    assert "报价编码" not in result.customer_reply


def test_changed_or_unrelated_record_is_not_overwritten(monkeypatch):
    db, result, actor, record = coded_reply_fixture(monkeypatch)
    record.result_json["quote_result"]["sales_note"] = "人工已调整价格"
    with pytest.raises(RuntimeError, match="RecordUnavailable"):
        save_coded_reply(db, result, actor, "询价")
    db.commit.assert_not_called()
    record.result_json["quote_result"] = result.quote_result.model_dump()
    record.actor_name = "other bot"
    with pytest.raises(RuntimeError, match="RecordUnavailable"):
        save_coded_reply(db, result, actor, "询价")
    db.commit.assert_not_called()


def test_missing_record_or_commit_failure_never_sends_untracked_price(monkeypatch, setup_worker):
    from unittest.mock import Mock

    db, result, actor, _ = coded_reply_fixture(monkeypatch)
    repository = Mock()
    repository.get_latest_record_by_quote_id.return_value = None
    monkeypatch.setattr("apps.api.services.wecom_quote_worker.SalesQuoteRecordRepository", lambda _: repository)
    with pytest.raises(RuntimeError, match="RecordUnavailable"):
        save_coded_reply(db, result, actor, "询价")

    db, result, actor, _ = coded_reply_fixture(monkeypatch)
    db.commit.side_effect = RuntimeError("database unavailable")

    def quote(_):
        save_coded_reply(db, result, actor, "询价")
        return result

    worker, _ = setup_worker(quote)
    asyncio.run(worker.process(frame()))
    assert "未确认可用价格" in worker.client.sent[-1][2]
    assert "报价编码" not in worker.client.sent[-1][2]
    assert "USD" not in worker.client.sent[-1][2]


def test_missing_fields_do_not_receive_a_quote_code():
    from unittest.mock import Mock
    db = Mock()
    result = SimpleNamespace(quote_result=None, customer_reply="请补充邮编")
    save_coded_reply(db, result, None, "10箱")
    assert result.customer_reply == "请补充邮编"
    db.commit.assert_not_called()


def test_quote_code_survives_failed_delivery_and_worker_restart(tmp_path):
    reply = "报价编码：10000123\n规则报价 USD 123.00"
    state = State(tmp_path)
    worker = QuoteWorker(bot_id="bot", allowed_users={"owner"}, state=state, client=FakeClient(),
                         quote=lambda _: SimpleNamespace(customer_reply=reply, missing_fields=[]))
    worker.client.fail_final = True
    with pytest.raises(TimeoutError):
        asyncio.run(worker.process(frame()))
    state.close()
    state = State(tmp_path)
    try:
        restarted = QuoteWorker(bot_id="bot", allowed_users={"owner"}, state=state, client=FakeClient(),
                                quote=lambda _: pytest.fail("must reuse stored quote and code"))
        asyncio.run(restarted.process(frame()))
        assert restarted.client.sent[-1][2] == reply
    finally:
        state.close()


def test_structured_draft_restart_ack_retry_sender_isolation_reset_and_expiry(tmp_path):
    from packages.ai_assistant.quote_draft import merge_quote_draft
    calls = []

    def quote(message, *, previous_extraction=None, current_message=None):
        calls.append((message, previous_extraction, current_message))
        patch = apply_deterministic_extraction(AIExtractedQuoteDraft(), current_message or message)
        result = merge_quote_draft(AIExtractedQuoteDraft.model_validate(previous_extraction), patch, current_message) if previous_extraction else patch
        missing = sorted(missing_required_fields(result))
        return SimpleNamespace(customer_reply="请补充总重", missing_fields=missing, extraction=result)

    def start():
        state = State(tmp_path)
        worker = QuoteWorker(bot_id="bot", allowed_users={"owner", "second"}, state=state, client=FakeClient(), quote=quote, supports_drafts=True)
        return worker

    worker = start()
    conversation = digest("bot", "owner")
    asyncio.run(worker.process(frame("d1", "2箱 100x100x100cm")))
    assert worker.state.draft(conversation)["piece_count"] == 2
    worker.state.close()
    worker = start()
    try:
        worker.client.fail_final = True
        with pytest.raises(TimeoutError):
            asyncio.run(worker.process(frame("d2", "尺寸改为120x100x100cm")))
        assert worker.state.draft(conversation)["cbm"] == "2.400"
        worker.client.fail_final = False
        asyncio.run(worker.process(frame("d2", "尺寸改为120x100x100cm")))
        assert len(calls) == 2  # Saved reply and draft were committed before the missing ACK.
        assert calls[1][2] == "尺寸改为120x100x100cm"
        assert calls[1][1]["piece_count"] == 2
        assert "客户补充：" in calls[1][0]  # Full raw evidence retained separately.
        asyncio.run(worker.process(frame("d3", "总重100kg", sender="second")))
        assert calls[-1][1] is None
        assert worker.state.draft(conversation)["cbm"] == "2.400"
        with worker.state.db:
            for table in ("sessions", "customs_sessions", "knowledge_sessions", "schedule_sessions"):
                worker.state.db.execute(f"UPDATE {table} SET updated=0 WHERE id=?", (conversation,))
        assert worker.state.draft(conversation) is None
        asyncio.run(worker.process(frame("d4", "2箱 100x100x100cm")))
        assert calls[-1][1] is None
        asyncio.run(worker.process(frame("d5", "新报价")))
        assert worker.state.previous(conversation) == "" and worker.state.draft(conversation) is None
    finally:
        worker.state.close()


def test_transient_quote_error_keeps_last_structured_draft(tmp_path):
    state = State(tmp_path)
    conversation = digest("bot", "owner")
    state.begin("seed", conversation)
    draft = AIExtractedQuoteDraft(piece_count=2).model_dump(mode="json")
    state.finish("seed", "补充", conversation, "2箱", draft)

    def failed(*args, **kwargs):
        raise TimeoutError("fixture failure")

    worker = QuoteWorker(bot_id="bot", allowed_users={"owner"}, state=state, client=FakeClient(), quote=failed, supports_drafts=True)
    try:
        asyncio.run(worker.process(frame("error", "总重100kg")))
        assert state.draft(conversation) == draft
        assert state.previous(conversation) == "2箱"
    finally:
        state.close()


def test_legacy_state_upgrade_preserves_raw_history_and_handles_corrupt_draft(tmp_path):
    import sqlite3
    import time
    db = sqlite3.connect(tmp_path / "state.sqlite3")
    db.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, message TEXT NOT NULL, updated REAL NOT NULL)")
    db.execute("INSERT INTO sessions VALUES ('conversation', '旧询价', ?)", (time.time(),))
    db.commit()
    db.close()
    state = State(tmp_path)
    try:
        assert state.previous("conversation") == "旧询价" and state.draft("conversation") is None
        state.db.execute("UPDATE sessions SET draft_json='broken'")
        assert state.draft("conversation") is None
        assert state.previous("conversation") == "旧询价"
    finally:
        state.close()


@pytest.mark.parametrize('command', ['「新报价」', '『重置』', '“重新开始”', '"新报价"', "' 新报价 '"])
def test_quoted_reset_clears_raw_and_json_draft_without_model_call(setup_worker, command):
    worker, calls = setup_worker()
    conversation = digest('bot', 'owner')
    worker.state.begin('existing', conversation)
    worker.state.finish('existing', 'previous reply', conversation, '2箱100x100x100cm',
                        AIExtractedQuoteDraft(piece_count=2, cbm=2).model_dump(mode='json'))
    worker.state.sent('existing')
    asyncio.run(worker.process(frame('quoted-reset', command)))
    assert calls == []
    assert worker.state.previous(conversation) == ''
    assert worker.state.draft(conversation) is None
    assert worker.client.sent[-1][2].startswith('已开始新的一票。')
    assert worker.state.event(digest('bot', 'owner', 'quoted-reset'))['status'] == 'replied'


def test_quoted_inquiry_is_not_rewritten_as_control_command(setup_worker):
    worker, calls = setup_worker()
    message = '「新报价，2箱100x100x100cm」'
    asyncio.run(worker.process(frame(text=message)))
    assert calls == [message]
