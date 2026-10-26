"""Merge current-turn facts, keeping shipment totals and unfinished operations distinct."""
from __future__ import annotations

import re
from decimal import Decimal

from packages.ai_assistant.quote_extractor import (
    AIExtractedQuoteDraft, ExtractedCargoItem, _find_explicit_piece_count,
    _find_per_piece_weight, _find_authoritative_weight, _normalize_cargo_item, _clear_extracted_address_noise,
    missing_required_fields, apply_deterministic_extraction,
)
from packages.ai_assistant.service_requirements import mentioned_service_fields, explicit_service_requirements

CARGO = {"cbm", "weight_kg", "piece_count", "longest_side_cm", "cargo_items"}
SCALARS = ("address_line", "postal_code", "city", "province", "packaging_type", "explicit_pallet_count", "is_stackable", "address_type")
DIMENSIONS = ("length_cm", "width_cm", "height_cm")


def _has_cargo(patch):
    return any(getattr(patch, field) not in (None, []) for field in CARGO)


def _has_dimensions(patch):
    return any(any(getattr(item, field) is not None for field in DIMENSIONS) for item in patch.cargo_items)


def _target(message):
    targets = re.findall(r"第\s*([1-9]\d*|一|二|三|四|五|六|七|八|九|十)\s*组", message)
    if not targets:
        return None
    token = targets[-1]
    return int(token) - 1 if token.isdigit() else "一二三四五六七八九十".index(token)


def _operation(message, patch):
    if re.search(r"全部替换|整票替换|重新提供|完整货物|replace all", message, re.I):
        return "replace_all"
    # '总重增加到' and '增加尾板' do not add cargo rows.
    if re.search(r"(?:另加|新增|再加|追加|增加|\badd\b)\s*(?:货物|一|两|[0-9]|\d|箱|件|托|\bcargo\b)", message, re.I):
        return "add"
    if _target(message) is None and len(patch.cargo_items) > 1 and re.search(r"更正|修改|改为", message):
        return "replace_all"
    return "update"


def _pending(draft, operation, patch, message, conflict, index=None):
    draft.pending_cargo_update = {"version": 1, "operation": operation,
        "scope": "shipment" if operation in {"add", "replace_all"} or (operation == "confirm_volume" and index is None) else "group",
        "group_index": index, "patch": patch.model_dump(mode="json"), "message": message}
    draft.draft_conflicts = [conflict]


def _clear_pending(draft):
    draft.pending_cargo_update = None
    draft.draft_conflicts = []


def _totals(draft):
    if not draft.cargo_items:
        return
    draft.cargo_items = [_normalize_cargo_item(i) for i in draft.cargo_items]
    draft.piece_count = sum(i.quantity for i in draft.cargo_items)
    volumes = [i.total_cbm for i in draft.cargo_items]
    weights = [i.total_weight_kg for i in draft.cargo_items]
    draft.cbm = sum(volumes, Decimal(0)) if all(v is not None for v in volumes) else None
    draft.weight_kg = sum(weights, Decimal(0)) if all(v is not None for v in weights) else None
    lengths = [getattr(i, f) for i in draft.cargo_items for f in DIMENSIONS if getattr(i, f) is not None]
    if lengths:
        draft.longest_side_cm = max(lengths)
    if draft.shipment_weight_kg is not None:
        draft.weight_kg = draft.shipment_weight_kg
    if draft.shipment_cbm is not None:
        draft.cbm = draft.shipment_cbm


def _edit_item(old, patch, message):
    item = old.model_copy(deep=True)
    if patch.cargo_items:
        for field in DIMENSIONS:
            value = getattr(patch.cargo_items[0], field)
            if value is not None:
                setattr(item, field, value)
    quantity = _find_explicit_piece_count(message)
    item.quantity = quantity if quantity is not None else old.quantity
    each = _find_per_piece_weight(message)
    if each is not None:
        item.weight_kg, item.total_weight_kg = each, each * item.quantity
    elif patch.weight_kg is not None:
        item.total_weight_kg = patch.weight_kg
        item.weight_kg = patch.weight_kg / item.quantity
    elif item.quantity != old.quantity:
        item.weight_kg = item.total_weight_kg = None
    if not _has_dimensions(patch) and patch.cbm is not None:
        item.total_cbm, item.cbm = patch.cbm, patch.cbm / item.quantity
    elif item.quantity != old.quantity or _has_dimensions(patch):
        item.total_cbm = None
    return _normalize_cargo_item(item)


def _apply_cargo(draft, patch, message, operation, index):
    if operation == "replace_all":
        for field in CARGO:
            setattr(draft, field, getattr(patch, field))
        draft.shipment_weight_kg = draft.shipment_cbm = None
        _clear_pending(draft)
        _totals(draft)
        return
    if operation == "add":
        if not draft.cargo_items and (draft.piece_count is not None or draft.cbm is not None):
            _pending(draft, "add", patch, message, "cargo_add_base_details")
            return
        if not patch.cargo_items or any(i.total_cbm is None or i.total_weight_kg is None for i in patch.cargo_items):
            _pending(draft, "add", patch, message, "cargo_add_details")
            return
        if draft.shipment_weight_kg is not None:
            draft.shipment_weight_kg += sum(i.total_weight_kg for i in patch.cargo_items)
        if draft.shipment_cbm is not None:
            draft.shipment_cbm += sum(i.total_cbm for i in patch.cargo_items)
        draft.cargo_items += [i.model_copy(deep=True) for i in patch.cargo_items]
        _clear_pending(draft)
        _totals(draft)
        return

    dimensions = _has_dimensions(patch)
    each = _find_per_piece_weight(message)
    count = _find_explicit_piece_count(message)
    # Totals supplied without a row selector/dimensions/count are shipment facts.
    shipment = index is None and not dimensions and each is None and count is None
    if shipment:
        if patch.weight_kg is not None:
            draft.shipment_weight_kg = draft.weight_kg = patch.weight_kg
        if patch.cbm is not None:
            calculated = sum((i.total_cbm or Decimal(0) for i in draft.cargo_items), Decimal(0))
            if any(any(getattr(i, f) is not None for f in DIMENSIONS) for i in draft.cargo_items) and patch.cbm != calculated:
                _pending(draft, "confirm_volume", patch, message, "cargo_volume_conflict")
            else:
                draft.shipment_cbm = draft.cbm = patch.cbm
        return
    if (index is not None and not 0 <= index < len(draft.cargo_items)) or (
        len(draft.cargo_items) > 1 and index is None) or (len(patch.cargo_items) > 1 and bool(draft.cargo_items)):
        _pending(draft, "update", patch, message, "cargo_update_target", index)
        return
    if not draft.cargo_items and draft.piece_count is not None and len(patch.cargo_items) <= 1:
        draft.cargo_items = [ExtractedCargoItem(quantity=draft.piece_count, total_weight_kg=draft.weight_kg,
                                               total_cbm=draft.cbm)]
    if draft.cargo_items:
        index = index if index is not None else 0
        old = draft.cargo_items[index]
        if not dimensions and patch.cbm is not None and any(getattr(old, f) is not None for f in DIMENSIONS) and patch.cbm != old.total_cbm:
            _pending(draft, "confirm_volume", patch, message, "cargo_volume_conflict", index)
            return
        # Retain a previously confirmed aggregate when only dimensions change.
        if draft.shipment_weight_kg is None and draft.weight_kg is not None and any(i.total_weight_kg is None for i in draft.cargo_items):
            draft.shipment_weight_kg = draft.weight_kg
        item = _edit_item(old, patch, message)
        if item.quantity != old.quantity or patch.weight_kg is not None or each is not None:
            row_weights = [row.total_weight_kg for row in draft.cargo_items]
            if draft.shipment_weight_kg is not None and (
                any(value is None for value in row_weights)
                or sum(row_weights, Decimal(0)) != draft.shipment_weight_kg
            ):
                # These old row weights no longer reconcile to the confirmed
                # shipment total. Do not revive them as authoritative totals.
                for position, row in enumerate(draft.cargo_items):
                    if position != index:
                        row.weight_kg = row.total_weight_kg = None
            draft.shipment_weight_kg = None
        draft.shipment_cbm = None
        draft.cargo_items[index] = item
    else:
        for field in CARGO:
            value = getattr(patch, field)
            if value not in (None, []):
                setattr(draft, field, value)
    _clear_pending(draft)
    _totals(draft)


def merge_quote_draft(previous: AIExtractedQuoteDraft, patch: AIExtractedQuoteDraft, message: str) -> AIExtractedQuoteDraft:
    draft = previous.model_copy(deep=True)
    draft.validation_notes = list(patch.validation_notes)
    draft.cargo_agent, draft.address_agent = patch.cargo_agent, patch.address_agent
    draft.confidence, draft.extraction_notes = patch.confidence, patch.extraction_notes
    if patch.postal_code and patch.postal_code != previous.postal_code:
        draft.city, draft.province, draft.address_line = None, None, None
    for field in SCALARS:
        value = getattr(patch, field)
        if value is not None and value != "unknown":
            setattr(draft, field, value)
    _clear_extracted_address_noise(draft)
    facts = explicit_service_requirements(message)
    for field in mentioned_service_fields(message):
        setattr(draft, field, facts[field])
    if re.search(r"detention_minutes|等候|等待|压车|detention", message, re.I):
        draft.detention_minutes = patch.detention_minutes

    # An explicit shipment total may accompany a group edit. Remove its clause
    # from row parsing, then apply it as a shipment fact after the cargo operation.
    shipment_weight = None
    total_clause = re.search(r"(?:整票|全票|全部货物)(?:的)?(?:总重|重量)[^，,；;\n]*", message)
    if total_clause:
        shipment_weight = _find_authoritative_weight(total_clause[0])
        if shipment_weight is not None:
            message = message[:total_clause.start()] + message[total_clause.end():]
            patch = patch.model_copy(deep=True)
            row_facts = apply_deterministic_extraction(AIExtractedQuoteDraft(), message)
            patch.weight_kg = row_facts.weight_kg
            for position, item in enumerate(patch.cargo_items):
                item.weight_kg = item.total_weight_kg = None
                if len(row_facts.cargo_items) == len(patch.cargo_items):
                    item.weight_kg = row_facts.cargo_items[position].weight_kg
                    item.total_weight_kg = row_facts.cargo_items[position].total_weight_kg
    operation, index = _operation(message, patch), _target(message)
    has_cargo = _has_cargo(patch) or _find_per_piece_weight(message) is not None
    pending = previous.pending_cargo_update
    consumed = False
    if pending and re.search(r"取消(?:本次|刚才|待补充)?(?:新增|修改|操作)|cancel (?:addition|update)", message, re.I):
        _clear_pending(draft)
        consumed = True
    elif pending and operation == "update":
        saved = AIExtractedQuoteDraft.model_validate(pending["patch"])
        pending_op = pending.get("operation") or _operation(pending["message"], saved)
        if pending_op == "confirm_volume" and re.search(r"以总体积为准|确认总体积|以第\s*\d+\s*组体积为准", message):
            saved_index = pending.get("group_index")
            if saved_index is None:
                draft.shipment_cbm = draft.cbm = saved.cbm
            else:
                # Keep dimensions as overlength evidence; aggregate is explicitly confirmed.
                draft.shipment_cbm = (draft.cbm or Decimal(0)) - (draft.cargo_items[saved_index].total_cbm or Decimal(0)) + saved.cbm
                draft.cbm = draft.shipment_cbm
            _clear_pending(draft)
            consumed = True
        elif pending_op == "add" and has_cargo:
            combined = merge_quote_draft(saved, patch, message)
            _apply_cargo(draft, combined, pending["message"] + "\n" + message, "add", None)
            consumed = True
        elif pending_op == "update" and index is not None:
            if has_cargo:
                saved = merge_quote_draft(saved, patch, message)
            _apply_cargo(draft, saved, pending["message"] + "\n" + message, "update", index)
            consumed = True
        elif pending_op == "confirm_volume" and not _has_dimensions(patch):
            # Other shipment/address facts do not resolve the volume conflict.
            if patch.weight_kg is not None:
                draft.shipment_weight_kg = draft.weight_kg = patch.weight_kg
            consumed = True
    if not consumed and has_cargo:
        _apply_cargo(draft, patch, message, operation, index)

    for field, label in (("weight_kg", "重量|总重"), ("cbm", "体积|方数"), ("piece_count", "件数|箱数"),
                         ("postal_code", "邮编"), ("address_type", "地址类型"), ("packaging_type", "包装")):
        if re.search(rf"(?:{label})\s*(?:不确定|未知|待确认|不知道)", message):
            setattr(draft, field, None)
            if field in {"weight_kg", "cbm", "piece_count"}:
                draft.cargo_items = []
                draft.shipment_weight_kg = draft.shipment_cbm = None
    if shipment_weight is not None:
        draft.shipment_weight_kg = draft.weight_kg = shipment_weight
    draft.missing_fields = sorted(missing_required_fields(draft))
    return draft
