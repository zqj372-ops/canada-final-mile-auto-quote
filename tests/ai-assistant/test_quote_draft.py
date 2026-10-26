from decimal import Decimal
import json

from packages.ai_assistant.model_client import AIResponse
from packages.ai_assistant.quote_extractor import (
    AIExtractedQuoteDraft, ExtractedCargoItem, apply_deterministic_extraction,
    extract_quote_draft_with_agents, _validate_cargo_items_and_totals,
    build_follow_up_question, missing_required_fields,
)
from packages.ai_assistant.quote_draft import merge_quote_draft


def parse(message):
    return apply_deterministic_extraction(AIExtractedQuoteDraft(), message)


def update(previous, message):
    return merge_quote_draft(previous, parse(message), message)


def test_dimension_correction_does_not_double_count_history_even_with_correct_model():
    class Model:
        def complete(self, messages):
            cargo = {"piece_count": 2, "cbm": 2.4, "cargo_items": [{"quantity": 2, "length_cm": 120, "width_cm": 100, "height_cm": 100}]}
            return AIResponse(content=json.dumps(cargo if "货物字段 Agent" in messages[0].content else {}))
    draft = extract_quote_draft_with_agents("2箱 100x100x100cm\n客户补充：尺寸更正为120x100x100cm，2箱", Model())
    assert draft.piece_count == 2
    assert draft.cbm == Decimal("2.400")
    assert len(draft.cargo_items) == 1


def test_model_cbm_is_independently_recalculated_from_dimensions():
    draft = AIExtractedQuoteDraft(cbm=18, cargo_items=[ExtractedCargoItem(quantity=2, length_cm=120, width_cm=100, height_cm=100, cbm=9, total_cbm=18)])
    result = _validate_cargo_items_and_totals(draft)
    assert result.cargo_items[0].cbm == Decimal("1.200000")
    assert result.cargo_items[0].total_cbm == Decimal("2.400")
    assert result.cbm == Decimal("2.400")


def test_inch_precision_survives_serialization_and_repeat_validation():
    draft = parse("2箱 48x40x60in，总重900lbs")
    for _ in range(3):
        draft = _validate_cargo_items_and_totals(AIExtractedQuoteDraft.model_validate_json(draft.model_dump_json()))
    assert draft.cbm == Decimal("3.776")
    assert draft.cargo_items[0].length_cm == Decimal("121.92")


def test_dimensions_only_replacement_preserves_count_weight_and_changes_longest():
    draft = parse("2箱 200x100x100cm，总重100kg，M6B3P8")
    draft = update(draft, "尺寸改为120x100x100cm")
    assert (draft.piece_count, draft.cbm, draft.weight_kg, draft.longest_side_cm) == (2, Decimal("2.4"), Decimal("100"), Decimal("120"))
    assert draft.postal_code == "M6B 3P8"


def test_count_change_does_not_invent_weight():
    draft = update(parse("2箱 100x100x100cm，总重100kg"), "改为3箱")
    assert draft.piece_count == 3
    assert draft.cbm == Decimal("3")
    assert draft.weight_kg is None
    assert "weight_kg" in draft.missing_fields


def test_multi_group_correction_waits_for_target_and_applies_pending_patch():
    draft = parse("1箱 100x100x100cm 50kg\n2箱 80x100x100cm 20kg")
    original = draft.model_copy(deep=True)
    draft = update(draft, "尺寸改为120x100x100cm")
    assert draft.cargo_items == original.cargo_items
    assert "cargo_update_target" in missing_required_fields(draft)
    question = build_follow_up_question(draft.missing_fields, draft)
    assert "第1组" in question and "第2组" in question
    # The pending change survives a restart/JSON round trip and an unrelated supplement.
    draft = AIExtractedQuoteDraft.model_validate_json(draft.model_dump_json())
    draft = update(draft, "邮编M6B3P8")
    draft = update(draft, "第2组")
    assert draft.draft_conflicts == []
    assert draft.pending_cargo_update is None
    assert draft.cargo_items[0] == original.cargo_items[0]
    assert draft.cargo_items[1].quantity == 2
    assert draft.cargo_items[1].length_cm == Decimal("120")
    assert draft.cbm == Decimal("3.400")
    assert draft.weight_kg == original.weight_kg
    assert draft.postal_code == "M6B 3P8"


def test_full_replacement_and_explicit_addition_have_different_totals():
    draft = parse("1箱 100x100x100cm 50kg")
    added = update(draft, "新增1箱 120x100x100cm 20kg")
    replaced = update(draft, "全部替换：1箱 120x100x100cm 20kg")
    assert (added.piece_count, added.cbm, added.weight_kg) == (2, Decimal("2.2"), Decimal("70"))
    assert (replaced.piece_count, replaced.cbm, replaced.weight_kg) == (1, Decimal("1.2"), Decimal("20"))
    incomplete = update(draft, "新增1箱")
    assert incomplete.draft_conflicts == ["cargo_add_details"]
    assert incomplete.cargo_items == draft.cargo_items


def test_postal_change_drops_old_location_but_keeps_cargo():
    draft = parse("2箱 100x100x100cm 总重100kg")
    draft.postal_code, draft.city, draft.province, draft.address_line = "M6B 3P8", "Toronto", "ON", "1 Old Street"
    draft = update(draft, "邮编改为V6B1A1")
    assert draft.postal_code == "V6B 1A1"
    assert draft.city is None and draft.province is None and draft.address_line is None
    assert draft.piece_count == 2


def test_omitted_service_is_retained_and_uncertainty_withdraws_it():
    draft = AIExtractedQuoteDraft(requires_liftgate=True, requires_appointment=False)
    draft = update(draft, "总重100kg")
    assert draft.requires_liftgate is True and draft.requires_appointment is False
    draft = update(draft, "是否需要尾板待确认")
    assert draft.requires_liftgate is None
    draft = update(draft, "不需要尾板")
    assert draft.requires_liftgate is False


def test_precise_followup_lists_only_missing_fields_and_known_summary():
    draft = AIExtractedQuoteDraft(postal_code="M6B 3P8", piece_count=2, cbm=2.4)
    question = build_follow_up_question(["weight_kg"], draft)
    assert "已记录" in question and "M6B 3P8" in question
    assert "请补充 总重量 kg" in question
    assert "请补充 加拿大邮编" not in question
    assert "长×宽×高" in build_follow_up_question(["cbm"], draft)


def test_legacy_multi_group_ambiguity_remains_a_blocker_after_agent_merge():
    class Model:
        def complete(self, messages):
            return AIResponse(content='{}')
    raw = "1箱 100x100x100cm 50kg\n2箱 80x100x100cm 20kg\n客户补充：尺寸改为120x100x100cm"
    draft = extract_quote_draft_with_agents(raw, Model())
    assert "cargo_update_target" in draft.missing_fields
    assert draft.pending_cargo_update is not None


def test_legacy_service_correction_uses_last_turn_not_conflict_across_history():
    class Model:
        def complete(self, messages):
            return AIResponse(content='{}')
    draft = extract_quote_draft_with_agents("需要尾板\n客户补充：不需要尾板", Model())
    assert draft.requires_liftgate is False


def test_customer_correction_without_internal_delimiter_overrides_even_correct_model():
    class Model:
        def complete(self, messages):
            return AIResponse(content=json.dumps({'piece_count': 2, 'cbm': 2.4, 'cargo_items': [
                {'quantity': 2, 'length_cm': 120, 'width_cm': 100, 'height_cm': 100}
            ]} if '货物字段 Agent' in messages[0].content else {}))
    result = extract_quote_draft_with_agents('2箱100x100x100cm\n更正：2箱120x100x100cm', Model())
    assert (result.piece_count, result.cbm) == (2, Decimal('2.4'))


def test_per_piece_weight_uses_preserved_quantity():
    result = update(parse('2箱100x100x100cm'), '尺寸改为120x100x100cm，每箱50kg')
    assert (result.piece_count, result.cbm, result.weight_kg) == (2, Decimal('2.4'), Decimal('100'))
    assert result.cargo_items[0].weight_kg == Decimal('50')


def test_replacement_with_multiple_groups_keeps_all_rows():
    result = update(parse('2箱100x100x100cm 总重100kg'), '更正尺寸：\n1箱120x100x100cm 10kg\n2箱80x100x100cm 20kg')
    assert (result.piece_count, result.cbm, result.weight_kg) == (3, Decimal('2.8'), Decimal('50'))
    assert len(result.cargo_items) == 2


def test_pending_addition_survives_restart_and_retains_operation():
    result = update(parse('1箱100x100x100cm 50kg'), '新增1箱')
    result = AIExtractedQuoteDraft.model_validate_json(result.model_dump_json())
    result = update(result, '120x100x100cm 20kg')
    assert (result.piece_count, result.cbm, result.weight_kg) == (2, Decimal('2.2'), Decimal('70'))
    assert result.pending_cargo_update is None


def test_volume_conflict_retains_longest_and_requires_confirmation():
    result = update(parse('3箱300x50x50cm 总重100kg'), '总体积改为3CBM')
    assert result.longest_side_cm == Decimal('300')
    assert 'cargo_volume_conflict' in result.missing_fields
    assert len(result.cargo_items) == 1
    result = update(result, '以总体积为准')
    assert result.cbm == Decimal('3') and result.longest_side_cm == Decimal('300')
    assert not result.draft_conflicts


def test_shipment_weight_is_not_a_group_edit():
    result = update(parse('1箱100x100x100cm\n2箱80x100x100cm'), '总重500kg')
    assert result.weight_kg == Decimal('500')
    assert not result.draft_conflicts
    assert all(i.weight_kg is None for i in result.cargo_items)
    result = update(result, '第2组尺寸改为120x100x100cm')
    assert result.weight_kg == Decimal('500')


def test_target_confirmation_keeps_new_postal_and_service_facts():
    result = update(parse('1箱100x100x100cm 50kg\n2箱80x100x100cm 20kg'), '尺寸改为120x100x100cm')
    result = update(result, '第2组，邮编M6B3P8，不需要尾板')
    assert result.postal_code == 'M6B 3P8' and result.requires_liftgate is False
    assert result.cbm == Decimal('3.4')


def test_postal_update_with_authorized_defaults_cannot_become_city():
    from apps.api.services.wecom_quote_worker import with_quote_defaults
    result = parse('2箱100x100x100cm 总重100kg')
    result.postal_code, result.city, result.province = 'M6B 3P8', 'Toronto', 'ON'
    message, _ = with_quote_defaults('邮编改为V6B1A1')
    result = update(result, message)
    assert result.postal_code == 'V6B 1A1'
    assert result.city is None and result.province is None


def test_increased_total_weight_is_not_an_add_operation():
    result = update(parse('2箱100x100x100cm 总重100kg'), '总重增加到120kg')
    assert result.weight_kg == Decimal('120') and not result.draft_conflicts


def test_pending_add_keeps_quantity_across_three_supplements_and_can_cancel():
    original = parse('1箱100x100x100cm 50kg')
    draft = update(original, '新增2箱')
    assert draft.pending_cargo_update['operation'] == 'add'
    draft = update(draft, '120x100x100cm')
    draft = AIExtractedQuoteDraft.model_validate_json(draft.model_dump_json())
    assert draft.cargo_items == original.cargo_items
    draft = update(draft, '每箱20kg')
    assert (draft.piece_count, draft.cbm, draft.weight_kg) == (3, Decimal('3.4'), Decimal('90'))
    draft = update(draft, '新增2箱')
    draft = update(draft, '取消新增，邮编M6B3P8')
    assert draft.pending_cargo_update is None and draft.postal_code == 'M6B 3P8'
    assert draft.piece_count == 3


def test_unspecified_multirow_patch_must_not_drop_rows_or_replace_existing():
    original = parse('2箱100x100x100cm 100kg')
    result = update(original, '1箱120x100x100cm 10kg\n2箱80x100x100cm 20kg')
    assert result.cargo_items == original.cargo_items
    assert 'cargo_update_target' in result.missing_fields


def test_explicit_group_with_multiple_rows_requires_clarification():
    original = parse('1箱100x100x100cm 50kg\n2箱80x100x100cm 20kg')
    result = update(original, '第2组更正：1箱120x100x100cm 10kg\n2箱80x100x100cm 20kg')
    assert result.cargo_items == original.cargo_items
    assert 'cargo_update_target' in result.missing_fields


def test_confirmed_shipment_total_survives_validation_without_invented_row_weights():
    draft = update(parse('1箱100x100x100cm 50kg\n2箱80x100x100cm 20kg'), '整票总重500kg')
    draft = _validate_cargo_items_and_totals(AIExtractedQuoteDraft.model_validate_json(draft.model_dump_json()))
    assert draft.weight_kg == Decimal('500')
    assert [i.total_weight_kg for i in draft.cargo_items] == [Decimal('50'), Decimal('40')]


def test_explicit_shipment_weight_and_group_dimensions_in_same_reply_are_separate():
    draft = update(parse('1箱100x100x100cm 50kg\n2箱80x100x100cm 20kg'), '第2组尺寸改为120x100x100cm，整票总重500kg')
    assert (draft.cbm, draft.weight_kg) == (Decimal('3.4'), Decimal('500'))
    assert [i.total_weight_kg for i in draft.cargo_items] == [Decimal('50'), Decimal('40')]
    assert draft.shipment_weight_kg == Decimal('500')


def test_addition_cannot_replace_aggregate_only_original_cargo():
    draft = AIExtractedQuoteDraft(piece_count=2, cbm=2, weight_kg=100)  # Legacy aggregate-only draft.
    assert not draft.cargo_items
    result = update(draft, '新增1箱120x100x100cm 20kg')
    assert result.piece_count == 2 and result.cbm == Decimal('2')
    assert 'cargo_add_base_details' in result.missing_fields


def test_model_cannot_claim_customer_confirmed_volume_or_pending_operation():
    from packages.ai_assistant.quote_extractor import extract_quote_draft
    class Model:
        def complete(self, messages):
            return AIResponse(content=json.dumps({'shipment_cbm': 99, 'shipment_weight_kg': 999,
                'pending_cargo_update': {'operation': 'confirm_volume'}, 'draft_conflicts': ['invented']}))
    draft = extract_quote_draft('2箱100x100x100cm 总重100kg', Model())
    assert draft.cbm == Decimal('2') and draft.weight_kg == Decimal('100')
    assert draft.shipment_cbm is None and draft.shipment_weight_kg is None
    assert draft.pending_cargo_update is None and not draft.draft_conflicts


def test_addition_preserves_authoritative_shipment_totals():
    draft = update(parse('1箱100x100x100cm 50kg\n2箱80x100x100cm 20kg'), '总重500kg')
    draft = update(draft, '新增1箱100x100x100cm 20kg')
    assert draft.weight_kg == Decimal('520')
    draft = update(parse('3箱300x50x50cm 总重100kg'), '总体积改为3CBM')
    draft = update(draft, '以总体积为准')
    draft = update(draft, '新增1箱100x100x100cm 20kg')
    assert draft.cbm == Decimal('4') and draft.longest_side_cm == Decimal('300')


def test_group_edit_cannot_revive_row_weights_superseded_by_shipment_total():
    draft = update(parse('1箱100x100x100cm 50kg\n2箱80x100x100cm 20kg'), '总重500kg')
    draft = update(draft, '第2组总重60kg')
    assert draft.weight_kg is None and 'weight_kg' in draft.missing_fields
    draft = update(draft, '第2组尺寸改为120x100x100cm')
    assert draft.weight_kg is None
    draft = update(draft, '整票总重520kg')
    assert draft.weight_kg == Decimal('520')
