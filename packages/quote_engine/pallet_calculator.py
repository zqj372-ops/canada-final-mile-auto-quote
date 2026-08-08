"""Deterministic pallet calculations for oversize freight (v2).

v2 billing model (2026-08-07 design spec ``NA_OVERSIZE_RULE_V2``)::

    billing_pallets = max(
        position_pallets,   # per line: standard 48x40 pallet positions by floor area
        volume_pallets,     # whole order: ceil(total CBM / volume_cbm_per_pallet)
        weight_pallets,     # whole order: ceil(total kg / weight_kg_per_pallet)
        long_piece_pallets, # per line: each piece > threshold bills 2 pallets
        wooden_crate_pallets, # per line: wooden crates >= 1 pallet each (long crates 2)
        explicit_pallets,   # customer-stated count, adopted only within tolerance
    )

There is no separate oversize surcharge: oversized/heavy freight enters the
Zone lookup price through pallet count.  Per-unit mechanical limits and
out-of-table totals turn the quote to manual review instead of adding fees.
Vehicle profiles are a conservative capacity reference only and never gate
automatic quoting (design v2 section 5).

Aggregate fallback (design v2 section 6.1.2): when no complete handling-unit
row is available and ``aggregate_quote_enabled`` is set, the whole-order
volume/weight formula runs directly on the declared totals with soft risk
tags instead of failing closed to manual.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pydantic import ValidationError

from packages.quote_engine.oversize_config import (
    FlexiblePackageDeal,
    OversizePalletRuleConfig,
    default_oversize_pallet_rule,
)
from packages.quote_engine.oversize_models import HandlingUnitInput
from packages.quote_engine.vehicle_packing import assess_vehicle_capacity


_MILLION = Decimal("1000000")
_ZERO = Decimal("0")
_LB_PER_KG = Decimal("2.2046226218")
_CUBIC_INCHES_PER_CBM = Decimal("61023.7440947323")
_LB_PER_CUBIC_FOOT_PER_KG_PER_CBM = Decimal("16.01846337396")
_DEAL_PACKAGING_ALIASES = {
    "woven_bag": "woven bag",
    "flexible_packaging": "flexible packaging",
    "柔性包装": "柔性包装",
    "编织袋": "编织袋",
}
# Soft risks never force manual review; they are audit/risk-tag material only.
_SOFT_REVIEW_RISKS = frozenset(
    {
        "aggregate_based_quote",
        "customer_piece_count_check_skipped",
        # Missing stack limits are conservatively normalized to unknown, which
        # means the line remains countable for billing but cannot be used to
        # claim a stack in vehicle capacity assessment.
        "handling_unit_stack_constraints_missing",
        "long_piece_count_unconfirmed",
        "low_density_dimensional_risk",
        "oversize_vehicle_dimension_exceeded",
        "oversize_vehicle_payload_exceeded",
        "oversize_vehicle_volume_exceeded",
        "reconciliation_skipped_aggregate",
    }
)
_TRACE_INPUT_KEYS = (
    "quantity",
    "handling_unit_quantity",
    "packaging_type",
    "packaging",
    "length_cm",
    "length",
    "width_cm",
    "width",
    "height_cm",
    "height",
    "unit_weight_kg",
    "unit_gross_weight",
    "unit_gross_weight_kg",
    "gross_weight_kg",
    "cbm",
    "unit_cbm",
    "contained_customer_pieces",
    "stackability",
    "max_stack_layers",
    "max_top_load_kg",
    "floor_rotation_allowed",
    "rotation_allowed",
    "source_span",
)


class _RuleConfigurationError(ValueError):
    """Raised when a caller supplies an invalid oversize rule snapshot."""


@dataclass(frozen=True)
class PalletCalculationResult:
    """Internal result used by the Zone calculator and audit trail.

    ``components`` intentionally accepts values other than integers.  In
    particular, derived weights, volumes and dimensions stay as ``Decimal``
    values until the audit layer serializes them.

    ``pricing_mode`` is ``per_pallet`` unless the flexible-package deal
    matched (design v2 section 2.8); the Zone engine then prices the flat
    ``flat_rate_usd`` container rate instead of the Zone matrix.
    """

    billing_pallets: int | None
    components: dict[str, object]
    manual_review_required: bool = False
    risk_tags: tuple[str, ...] = ()
    internal_note: str | None = None
    surcharges: dict[str, Decimal] = field(default_factory=dict)
    internal_trace: dict[str, object] = field(default_factory=dict)
    pricing_mode: str = "per_pallet"
    flat_rate_usd: Decimal | None = None


@dataclass(frozen=True)
class _NormalizedUnit:
    """A validated unit plus replayable source data for tracing."""

    index: int
    unit: HandlingUnitInput
    raw_input: dict[str, object] = field(default_factory=dict)
    normalized_input: dict[str, object] = field(default_factory=dict)


def calculate_billing_pallets(
    handling_units: Sequence[HandlingUnitInput | Mapping[str, object]] | None = None,
    rule: OversizePalletRuleConfig | Mapping[str, object] | None = None,
    *,
    # Legacy order-level fields.  They are retained for reconciliation and API
    # compatibility only; in line mode none can create a pallet basis by
    # themselves.  In aggregate mode (design v2 6.1.2) the declared totals are
    # the input for the whole-order volume/weight formula.
    cbm: Decimal | None = None,
    weight_kg: Decimal | None = None,
    piece_count: int | None = None,
    packaging_type: str | None = None,
    longest_side_cm: Decimal | None = None,
    explicit_pallet_count: int | None = None,
    is_stackable: bool | None = None,
    # Published order-level reconciliation names.
    declared_customer_piece_count: int | None = None,
    declared_total_weight_kg: Decimal | None = None,
    declared_total_volume_cbm: Decimal | None = None,
    # A few callers use the shorter aliases.  Keeping these aliases here makes
    # migration of the Zone request additive while the old aggregate fields
    # remain auditable.
    declared_piece_count: int | None = None,
    declared_weight_kg: Decimal | None = None,
    declared_volume_cbm: Decimal | None = None,
) -> PalletCalculationResult:
    """Calculate billable pallets from physical handling-unit rows.

    The first two arguments are intentionally positional-compatible with the
    new ``(handling_units, rule)`` contract.  Legacy aggregate arguments are
    never used to invent dimensions, pallets, or long-piece multipliers in
    line mode; they feed the aggregate fallback tier only.
    """

    risks: list[str] = []

    # Resolve aliases once.  Explicit new names take precedence over the old
    # names used by ZoneQuoteRequest.
    declared_customer = (
        declared_customer_piece_count
        if declared_customer_piece_count is not None
        else declared_piece_count
    )
    if declared_customer is None:
        declared_customer = piece_count
    declared_weight = (
        declared_total_weight_kg
        if declared_total_weight_kg is not None
        else declared_weight_kg
    )
    if declared_weight is None:
        declared_weight = weight_kg
    declared_volume = (
        declared_total_volume_cbm
        if declared_total_volume_cbm is not None
        else declared_volume_cbm
    )
    if declared_volume is None:
        declared_volume = cbm

    # Validate an explicitly supplied pallet count before any early-return
    # path.  ``None`` means no lower bound was supplied; every other value
    # must be finite, integral, and non-negative.  Keep the candidate at zero
    # for arithmetic only after recording the invalid-input risk.
    explicit_value = _as_int(explicit_pallet_count)
    explicit_invalid = False
    if explicit_pallet_count is not None:
        explicit_invalid = explicit_value is None or explicit_value < 0
        if explicit_invalid:
            _extend_unique(risks, ["explicit_pallet_count_invalid"])
    explicit_candidate = (
        explicit_value
        if explicit_value is not None and explicit_value >= 0
        else 0
    )

    # Validate the supplied rule before calculating any candidate.  An invalid
    # snapshot must fail closed; the published default is used only to give the
    # manual trace a stable rule identity, never to produce an automatic quote.
    rule_error: _RuleConfigurationError | None = None
    try:
        oversize_rule = _coerce_rule(rule)
    except _RuleConfigurationError as exc:
        oversize_rule = default_oversize_pallet_rule()
        rule_error = exc
        _extend_unique(risks, ["oversize_rule_invalid"])

    # Aggregate values are not a fallback.  Preserve old component keys so
    # legacy audit/Zone serializers can explicitly observe that no virtual
    # volume or long-piece pallet was produced.
    empty_components: dict[str, object] = {
        "position_pallets": 0,
        "volume_pallets": 0,
        "long_piece_pallets": 0,
        "wooden_crate_pallets": 0,
        "total_size_pallets": 0,
        "weight_pallets": 0,
        "explicit_pallet_count": explicit_candidate,
    }
    if rule_error is not None:
        return _manual_result(
            billing_pallets=None,
            components=empty_components,
            risks=risks,
            oversize_rule=oversize_rule,
            note="超大件计费规则无效；需人工确认规则配置后重新报价。",
            declared_values={
                "declared_customer_piece_count": declared_customer,
                "declared_total_weight_kg": declared_weight,
                "declared_total_volume_cbm": declared_volume,
                "explicit_pallet_count": _safe_trace_value(explicit_pallet_count),
                "explicit_pallet_count_valid": not explicit_invalid,
            },
            customer_piece_check="skipped_invalid_rule",
            trace_metadata={"rule_validation": _rule_validation_trace(rule)},
        )
    if handling_units is None or not isinstance(handling_units, Sequence) or isinstance(
        handling_units, (str, bytes)
    ):
        invalid_lines: list[dict[str, object]] = []
        normalized_units: list[_NormalizedUnit] = []
    else:
        invalid_lines = []
        normalized_units = []
        for index, raw in enumerate(handling_units):
            normalized, row_risks, row_trace = _normalize_handling_unit(raw, index)
            _extend_unique(risks, row_risks)
            if normalized is None:
                invalid_lines.append(row_trace)
            else:
                normalized_units.append(normalized)

    # ---- Mode selection -------------------------------------------------
    # Complete rows drive the exact per-line calculation.  When none are
    # usable and the aggregate tier is enabled, the declared totals feed the
    # whole-order formula with soft risk tags instead of failing closed.
    if normalized_units:
        return _calculate_line_mode(
            normalized_units=normalized_units,
            invalid_lines=invalid_lines,
            risks=risks,
            oversize_rule=oversize_rule,
            declared_customer=declared_customer,
            declared_weight=declared_weight,
            declared_volume=declared_volume,
            packaging_type=packaging_type,
            longest_side_cm=longest_side_cm,
            explicit_pallet_count=explicit_pallet_count,
            explicit_candidate=explicit_candidate,
            explicit_invalid=explicit_invalid,
            is_stackable=is_stackable,
        )
    if oversize_rule.aggregate_quote_enabled:
        return _calculate_aggregate_mode(
            invalid_lines=invalid_lines,
            risks=risks,
            oversize_rule=oversize_rule,
            declared_customer=declared_customer,
            declared_weight=declared_weight,
            declared_volume=declared_volume,
            packaging_type=packaging_type,
            longest_side_cm=longest_side_cm,
            explicit_pallet_count=explicit_pallet_count,
            explicit_candidate=explicit_candidate,
            explicit_invalid=explicit_invalid,
            is_stackable=is_stackable,
        )

    risks.append("handling_units_missing")
    return _manual_result(
        billing_pallets=None,
        components=empty_components,
        risks=risks,
        oversize_rule=oversize_rule,
        note="完整 handling_units 明细缺失且聚合降级档已关闭；不能使用 CBM、件数或最长边推导托数。",
        declared_values={
            "declared_customer_piece_count": declared_customer,
            "declared_total_weight_kg": declared_weight,
            "declared_total_volume_cbm": declared_volume,
            "explicit_pallet_count": _safe_trace_value(explicit_pallet_count),
            "explicit_pallet_count_valid": not explicit_invalid,
        },
        customer_piece_check="skipped_missing_rows",
    )


def _calculate_line_mode(
    *,
    normalized_units: list[_NormalizedUnit],
    invalid_lines: list[dict[str, object]],
    risks: list[str],
    oversize_rule: OversizePalletRuleConfig,
    declared_customer: int | None,
    declared_weight: Decimal | None,
    declared_volume: Decimal | None,
    packaging_type: str | None,
    longest_side_cm: Decimal | None,
    explicit_pallet_count: int | None,
    explicit_candidate: int,
    explicit_invalid: bool,
    is_stackable: bool | None,
) -> PalletCalculationResult:
    lines: list[dict[str, object]] = []
    derived_weight = _ZERO
    derived_volume = _ZERO
    total_position_pallets = 0
    total_long_piece_pallets = 0
    total_wooden_crate_pallets = 0
    floor_slots_exceeded = False
    weight_over_mechanical_limit = False

    for normalized in normalized_units:
        unit = normalized.unit
        line = _calculate_unit_line(unit, oversize_rule, normalized.index)
        line.update(
            {
                "contained_customer_pieces": unit.contained_customer_pieces,
                "supplied_unit_cbm": unit.cbm,
                "source_span": unit.source_span,
                "raw_input": dict(normalized.raw_input),
                "normalized_input": dict(normalized.normalized_input),
            }
        )
        lines.append(line)
        if line["floor_slots_exceeded"]:
            floor_slots_exceeded = True
        if line["weight_over_mechanical_limit"]:
            weight_over_mechanical_limit = True
        quantity = Decimal(unit.quantity)
        derived_weight += unit.unit_weight_kg * quantity
        derived_volume += line["unit_cbm"] * quantity  # type: ignore[operator]
        total_position_pallets += int(line["line_position_pallets"])
        total_long_piece_pallets += int(line["line_long_piece_pallets"])
        total_wooden_crate_pallets += int(line["line_wooden_crate_pallets"])

    if floor_slots_exceeded:
        _extend_unique(risks, ["oversize_floor_slots_exceeded"])
    if weight_over_mechanical_limit:
        _extend_unique(risks, ["unit_weight_over_mechanical_limit"])

    # A valid declared weight/volume is used only after reconciliation.  The
    # configured tolerance is the larger of the absolute tolerance and the
    # relative tolerance evaluated at max(abs(derived), abs(declared)).  This
    # is deliberately conservative for volumes and does not affect
    # size-pallet calculation.
    calculation_weight = derived_weight
    declared_weight_value = _as_decimal(declared_weight)
    if declared_weight is not None and declared_weight_value is None:
        _extend_unique(risks, ["declared_weight_invalid"])
    elif declared_weight_value is not None:
        if declared_weight_value < _ZERO:
            _extend_unique(risks, ["declared_weight_invalid"])
        else:
            weight_tolerance = _absolute_plus_relative_tolerance(
                derived_weight,
                declared_weight_value,
                oversize_rule.weight_tolerance_absolute_kg,
                oversize_rule.weight_tolerance_ratio,
            )
            if abs(declared_weight_value - derived_weight) > weight_tolerance:
                _extend_unique(risks, ["declared_weight_out_of_tolerance"])
            calculation_weight = max(derived_weight, declared_weight_value)

    calculation_volume = derived_volume
    declared_volume_value = _as_decimal(declared_volume)
    if declared_volume is not None and declared_volume_value is None:
        _extend_unique(risks, ["declared_volume_invalid"])
    elif declared_volume_value is not None:
        if declared_volume_value < _ZERO:
            _extend_unique(risks, ["declared_volume_invalid"])
        else:
            volume_tolerance = _relative_or_absolute_tolerance(
                derived_volume,
                declared_volume_value,
                oversize_rule.volume_tolerance_absolute_cbm,
                oversize_rule.volume_tolerance_ratio,
            )
            if abs(declared_volume_value - derived_volume) > volume_tolerance:
                _extend_unique(risks, ["declared_volume_out_of_tolerance"])
            calculation_volume = max(derived_volume, declared_volume_value)

    # Customer-piece checks are intentionally all-or-nothing at row level.  A
    # malformed row blocks reconciliation even when the remaining valid rows
    # contain complete counts; we must never report a check based only on a
    # partial valid subset.
    contained_values = [
        unit.contained_customer_pieces for normalized in normalized_units for unit in [normalized.unit]
    ]
    if invalid_lines:
        customer_check_status = "skipped_invalid_rows"
        _extend_unique(risks, ["customer_piece_count_check_skipped"])
    elif contained_values and all(value is not None for value in contained_values):
        contained_total = sum(int(value) for value in contained_values if value is not None)
        if declared_customer is not None:
            declared_customer_value = _as_int(declared_customer)
            if declared_customer_value is None or declared_customer_value < 0:
                _extend_unique(risks, ["customer_piece_count_invalid"])
            else:
                piece_tolerance = _relative_or_absolute_tolerance_int(
                    contained_total,
                    declared_customer_value,
                    oversize_rule.customer_piece_tolerance_absolute,
                    oversize_rule.customer_piece_tolerance_ratio,
                )
                if Decimal(abs(declared_customer_value - contained_total)) > piece_tolerance:
                    _extend_unique(risks, ["customer_piece_count_mismatch"])
        customer_check_status = "checked"
    else:
        customer_check_status = "skipped_partial_rows"
        _extend_unique(risks, ["customer_piece_count_check_skipped"])

    volume_pallets = _ceil_decimal(
        calculation_volume / oversize_rule.volume_cbm_per_pallet
    )
    weight_pallets = _ceil_decimal(
        calculation_weight / oversize_rule.weight_kg_per_pallet
    )

    deal_result = _flexible_package_deal_check(
        packaging_type=packaging_type,
        unit_rows=[normalized.unit for normalized in normalized_units],
        is_stackable=is_stackable,
        declared_pieces=None,
        deal=oversize_rule.flexible_package_deal,
        risks=risks,
    )
    flat_rate_usd: Decimal | None = None
    pricing_mode = "per_pallet"
    if deal_result.pricing_mode == "flat_rate":
        pricing_mode = "flat_rate"
        flat_rate_usd = deal_result.quote_usd

    return _finalize_billing(
        oversize_rule=oversize_rule,
        risks=risks,
        position_pallets=total_position_pallets,
        volume_pallets=volume_pallets,
        weight_pallets=weight_pallets,
        long_piece_pallets=total_long_piece_pallets,
        wooden_crate_pallets=total_wooden_crate_pallets,
        derived_weight=derived_weight,
        calculation_weight=calculation_weight,
        derived_volume=derived_volume,
        calculation_volume=calculation_volume,
        explicit_pallet_count=explicit_pallet_count,
        explicit_candidate=explicit_candidate,
        explicit_invalid=explicit_invalid,
        customer_check_status=customer_check_status,
        declared_customer=declared_customer,
        declared_weight_value=declared_weight_value,
        declared_volume_value=declared_volume_value,
        lines=lines + invalid_lines,
        line_mode=True,
        unit_rows=[normalized.unit for normalized in normalized_units],
        is_stackable=is_stackable,
        longest_side_cm=longest_side_cm,
        pricing_mode=pricing_mode,
        flat_rate_usd=flat_rate_usd,
        note=deal_result.note,
    )


def _calculate_aggregate_mode(
    *,
    invalid_lines: list[dict[str, object]],
    risks: list[str],
    oversize_rule: OversizePalletRuleConfig,
    declared_customer: int | None,
    declared_weight: Decimal | None,
    declared_volume: Decimal | None,
    packaging_type: str | None,
    longest_side_cm: Decimal | None,
    explicit_pallet_count: int | None,
    explicit_candidate: int,
    explicit_invalid: bool,
    is_stackable: bool | None,
) -> PalletCalculationResult:
    # Row-level hard risks are irrelevant on the successful aggregate path:
    # incomplete rows are exactly what triggers the fallback (design v2
    # 6.1.2), and the whole-order formula is driven by declared totals.  When
    # the aggregate totals are also missing, the row-level reasons are the
    # most precise manual diagnosis, so they are re-added in that branch.
    row_hard_risks = [risk for risk in risks if risk.startswith("handling_unit_")]
    risks = [risk for risk in risks if not risk.startswith("handling_unit_")]

    declared_weight_value = _as_decimal(declared_weight)
    declared_volume_value = _as_decimal(declared_volume)
    if declared_weight_value is None or declared_weight_value < _ZERO:
        declared_weight_value = None
    if declared_volume_value is None or declared_volume_value < _ZERO:
        declared_volume_value = None

    calculation_weight = declared_weight_value or _ZERO
    calculation_volume = declared_volume_value or _ZERO
    # The whole-order formula needs at least one declared dimension; piece
    # count alone cannot produce a pallet basis.
    if calculation_weight == _ZERO and calculation_volume == _ZERO:
        _extend_unique(risks, ["aggregate_info_insufficient"])
        _extend_unique(risks, row_hard_risks)
        empty_components: dict[str, object] = {
            "position_pallets": 0,
            "volume_pallets": 0,
            "long_piece_pallets": 0,
            "wooden_crate_pallets": 0,
            "total_size_pallets": 0,
            "weight_pallets": 0,
            "explicit_pallet_count": explicit_candidate,
            "line_count": len(invalid_lines),
            "aggregate_based": True,
        }
        return _manual_result(
            billing_pallets=None,
            components=empty_components,
            risks=risks,
            oversize_rule=oversize_rule,
            note="聚合信息不足以计算托数：总体积与总重量均缺失。",
            declared_values={
                "declared_customer_piece_count": declared_customer,
                "declared_total_weight_kg": declared_weight_value,
                "declared_total_volume_cbm": declared_volume_value,
                "explicit_pallet_count": _safe_trace_value(explicit_pallet_count),
                "explicit_pallet_count_valid": not explicit_invalid,
            },
            customer_piece_check="skipped_aggregate",
            trace_metadata={"aggregate_mode": True},
        )

    volume_pallets = _ceil_decimal(
        calculation_volume / oversize_rule.volume_cbm_per_pallet
    )
    weight_pallets = _ceil_decimal(
        calculation_weight / oversize_rule.weight_kg_per_pallet
    )

    # Overlength: only an explicit long-piece count could multiply pallets in
    # aggregate mode; a known longest side without a count stays at zero with
    # an unconfirmed risk tag (design v2 6.1.2).
    long_piece_pallets = 0
    if (
        longest_side_cm is not None
        and _as_decimal(longest_side_cm) is not None
        and _as_decimal(longest_side_cm) > oversize_rule.long_piece_threshold_cm
    ):
        _extend_unique(risks, ["long_piece_count_unconfirmed"])

    # Wooden crates keep their strong per-piece rule even in aggregate mode
    # (SOP v1.11: 7 件木箱 = 7 托, not carton fallback).
    packaging = _normalize_packaging(packaging_type)
    wooden_crate_pallets = (
        int(declared_customer) if _is_wooden_crate(packaging) and declared_customer is not None else 0
    )

    # Aggregate rows carry no line-level reconciliation evidence.
    _extend_unique(risks, ["aggregate_based_quote", "reconciliation_skipped_aggregate"])

    deal_result = _flexible_package_deal_check(
        packaging_type=packaging_type,
        unit_rows=[],
        is_stackable=is_stackable,
        declared_pieces=declared_customer,
        deal=oversize_rule.flexible_package_deal,
        risks=risks,
    )
    flat_rate_usd: Decimal | None = None
    pricing_mode = "per_pallet"
    if deal_result.pricing_mode == "flat_rate":
        pricing_mode = "flat_rate"
        flat_rate_usd = deal_result.quote_usd

    return _finalize_billing(
        oversize_rule=oversize_rule,
        risks=risks,
        position_pallets=0,
        volume_pallets=volume_pallets,
        weight_pallets=weight_pallets,
        long_piece_pallets=long_piece_pallets,
        wooden_crate_pallets=wooden_crate_pallets,
        derived_weight=calculation_weight,
        calculation_weight=calculation_weight,
        derived_volume=calculation_volume,
        calculation_volume=calculation_volume,
        explicit_pallet_count=explicit_pallet_count,
        explicit_candidate=explicit_candidate,
        explicit_invalid=explicit_invalid,
        customer_check_status="skipped_aggregate",
        declared_customer=declared_customer,
        declared_weight_value=declared_weight_value,
        declared_volume_value=declared_volume_value,
        lines=invalid_lines,
        line_mode=False,
        unit_rows=[],
        is_stackable=is_stackable,
        longest_side_cm=longest_side_cm,
        pricing_mode=pricing_mode,
        flat_rate_usd=flat_rate_usd,
        note=deal_result.note,
        trace_metadata={"aggregate_mode": True},
    )


def _finalize_billing(
    *,
    oversize_rule: OversizePalletRuleConfig,
    risks: list[str],
    position_pallets: int,
    volume_pallets: int,
    weight_pallets: int,
    long_piece_pallets: int,
    wooden_crate_pallets: int,
    derived_weight: Decimal,
    calculation_weight: Decimal,
    derived_volume: Decimal,
    calculation_volume: Decimal,
    explicit_pallet_count: int | None,
    explicit_candidate: int,
    explicit_invalid: bool,
    customer_check_status: str,
    declared_customer: int | None,
    declared_weight_value: Decimal | None,
    declared_volume_value: Decimal | None,
    lines: list[dict[str, object]],
    line_mode: bool,
    unit_rows: list[HandlingUnitInput],
    is_stackable: bool | None,
    longest_side_cm: Decimal | None,
    pricing_mode: str,
    flat_rate_usd: Decimal | None,
    note: str | None,
    trace_metadata: Mapping[str, object] | None = None,
) -> PalletCalculationResult:
    derived = max(
        position_pallets,
        volume_pallets,
        weight_pallets,
        long_piece_pallets,
        wooden_crate_pallets,
    )

    # Explicit pallets are adopted only within tolerance and only in
    # per-pallet mode; the flat-rate container deal replaces per-pallet
    # billing entirely (design v2 2.7/2.8).
    explicit_conflict = False
    if explicit_pallet_count is not None and not explicit_invalid:
        if pricing_mode == "flat_rate":
            pass
        elif derived <= 0:
            explicit_conflict = True
        else:
            ratio = abs(Decimal(explicit_candidate) - Decimal(derived)) / Decimal(derived)
            if ratio > oversize_rule.explicit_pallet_tolerance_ratio:
                explicit_conflict = True
    if explicit_conflict:
        _extend_unique(risks, ["explicit_pallet_count_conflict"])
    billing_pallets = max(derived, explicit_candidate) if not explicit_conflict else derived

    # Out-of-table totals never price automatically (design v2 4.3).
    if pricing_mode == "per_pallet" and billing_pallets > 26:
        _extend_unique(risks, ["billing_pallets_out_of_table"])

    # Density risk is soft; DIM pallets join the max set only when enabled.
    _extend_density_and_dim_risks(
        risks=risks,
        oversize_rule=oversize_rule,
        calculation_weight=calculation_weight,
        calculation_volume=calculation_volume,
    )

    components: dict[str, object] = {
        "position_pallets": position_pallets,
        "volume_pallets": volume_pallets,
        "weight_pallets": weight_pallets,
        "long_piece_pallets": long_piece_pallets,
        "wooden_crate_pallets": wooden_crate_pallets,
        # Legacy alias kept for audit consumers that predate v2 naming.
        "total_size_pallets": position_pallets,
        "explicit_pallet_count": explicit_candidate,
        "derived_total_weight_kg": derived_weight,
        "calculation_weight_kg": calculation_weight,
        "derived_total_volume_cbm": derived_volume,
        "calculation_total_volume_cbm": calculation_volume,
        "line_count": len(lines),
        "pricing_mode": pricing_mode,
        "flat_rate_usd": flat_rate_usd,
        "aggregate_based": not line_mode,
    }
    if oversize_rule.dim_pallet_adjustment_enabled:
        components["dim_pallets"] = _dim_pallets(oversize_rule, calculation_volume)

    internal_trace: dict[str, object] = {
        "rule_id": oversize_rule.rule_id,
        "lines": lines,
        "totals": {
            "derived_total_weight_kg": derived_weight,
            "calculation_weight_kg": calculation_weight,
            "derived_total_volume_cbm": derived_volume,
            "calculation_total_volume_cbm": calculation_volume,
            "position_pallets": position_pallets,
            "volume_pallets": volume_pallets,
            "weight_pallets": weight_pallets,
            "long_piece_pallets": long_piece_pallets,
            "wooden_crate_pallets": wooden_crate_pallets,
            "explicit_pallet_count": explicit_candidate,
            "explicit_pallet_count_input": _safe_trace_value(explicit_pallet_count),
            "explicit_pallet_count_valid": not explicit_invalid,
            "billing_pallets": billing_pallets,
            "pricing_mode": pricing_mode,
            "customer_piece_check": customer_check_status,
        },
        "reconciliation": {
            "declared_customer_piece_count": declared_customer,
            "declared_total_weight_kg": declared_weight_value,
            "declared_total_volume_cbm": declared_volume_value,
            "customer_piece_check": customer_check_status,
            "explicit_pallet_count": _safe_trace_value(explicit_pallet_count),
            "explicit_pallet_count_valid": not explicit_invalid,
            "risk_tags": tuple(risks),
        },
    }
    if trace_metadata:
        internal_trace.update(trace_metadata)

    # Vehicle capacity is a conservative reference; its risks never block an
    # otherwise deterministic quote (design v2 section 5).
    vehicle_capacity = assess_vehicle_capacity(
        unit_rows,
        rule=oversize_rule,
        total_weight_kg=calculation_weight,
        total_volume_cbm=calculation_volume,
        longest_side_cm=longest_side_cm,
    )
    internal_trace["vehicle_capacity"] = vehicle_capacity.candidates
    internal_trace["vehicle_capacity_risks"] = list(vehicle_capacity.risk_tags)
    internal_trace["vehicle"] = {
        "status": "reference_only",
        "candidates": vehicle_capacity.candidates,
        "reason_codes": list(vehicle_capacity.risk_tags),
    }
    _extend_unique(risks, list(vehicle_capacity.risk_tags))

    # Row invalidity, declaration mismatches and per-unit auto limits all
    # remain hard blocks.  A candidate number is retained for internal audit;
    # the public Zone DTO is responsible for hiding it on manual results.
    # Aggregate/density/vehicle risks are soft reference material.
    manual = any(risk not in _SOFT_REVIEW_RISKS for risk in risks)
    if manual and note is None:
        note = _build_manual_note(risks)
    return PalletCalculationResult(
        billing_pallets=billing_pallets,
        components=components,
        manual_review_required=manual,
        risk_tags=tuple(risks),
        internal_note=note,
        surcharges={
            # v2 has no oversize surcharges; oversized/heavy freight enters
            # the Zone table price through pallet count (design v2 4.4).
            "footprint_surcharge": _ZERO,
            "high_board_surcharge": _ZERO,
            "heavy_surcharge": _ZERO,
            "total_surcharge": _ZERO,
        },
        internal_trace=internal_trace,
        pricing_mode=pricing_mode,
        flat_rate_usd=flat_rate_usd,
    )


def _extend_density_and_dim_risks(
    *,
    risks: list[str],
    oversize_rule: OversizePalletRuleConfig,
    calculation_weight: Decimal,
    calculation_volume: Decimal,
) -> None:
    if calculation_weight <= _ZERO or calculation_volume <= _ZERO:
        return
    density_kg_per_cbm = calculation_weight / calculation_volume
    density_lb_per_cuft = density_kg_per_cbm / _LB_PER_CUBIC_FOOT_PER_KG_PER_CBM
    if density_lb_per_cuft < oversize_rule.low_density_threshold_lb_per_cuft:
        _extend_unique(risks, ["low_density_dimensional_risk"])


def _dim_pallets(oversize_rule: OversizePalletRuleConfig, volume_cbm: Decimal) -> int:
    """Optional DIM pallets: ceil(DIM weight / weight equivalent)."""

    dim_weight_lb = volume_cbm * _CUBIC_INCHES_PER_CBM / oversize_rule.dim_factor
    weight_equivalent_lb = oversize_rule.weight_kg_per_pallet * _LB_PER_KG
    return _ceil_decimal(dim_weight_lb / weight_equivalent_lb)


@dataclass(frozen=True)
class _DealCheckResult:
    pricing_mode: str
    quote_usd: Decimal | None = None
    note: str | None = None


def _flexible_package_deal_check(
    *,
    packaging_type: str | None,
    unit_rows: Sequence[HandlingUnitInput],
    is_stackable: bool | None,
    declared_pieces: int | None,
    deal: FlexiblePackageDeal | None,
    risks: list[str],
) -> _DealCheckResult:
    """Detect the flexible-package flat-rate deal (design v2 2.8).

    Trigger: packaging keyword hit + total pieces >= min_pieces + stackable.
    Keyword hit with insufficient evidence is a manual trigger, because the
    carrier flat rate must not silently fall back to per-pallet billing.
    """

    if deal is None:
        return _DealCheckResult(pricing_mode="per_pallet")
    keywords = [keyword.strip().lower() for keyword in deal.keywords if keyword.strip()]

    # Line mode: the deal is judged on the matched handling-unit rows only.
    # Order-level packaging cannot trigger a deal when the rows disagree.
    if unit_rows:
        matched = [unit for unit in unit_rows if _packaging_matches_deal(unit.packaging_type, keywords)]
        if not matched:
            return _DealCheckResult(pricing_mode="per_pallet")
        pieces = 0
        pieces_complete = True
        for unit in matched:
            if unit.contained_customer_pieces is None:
                pieces_complete = False
            else:
                pieces += unit.contained_customer_pieces
        stackable = all(unit.stackability == "stackable" for unit in matched)
    else:
        order_packaging = _normalize_packaging(packaging_type)
        if not order_packaging or not _packaging_matches_deal(order_packaging, keywords):
            return _DealCheckResult(pricing_mode="per_pallet")
        pieces = declared_pieces
        pieces_complete = declared_pieces is not None
        stackable = is_stackable is True

    # Information insufficient to decide the flat rate -> manual review.
    # Piece count is decisive first: a known count below the threshold rules
    # the deal out, so no manual review is needed.  Unknown pieces or an
    # unknown stack state on an otherwise qualifying load must not silently
    # fall back to per-pallet billing (design v2 2.9).
    if not pieces_complete:
        _extend_unique(risks, ["flexible_package_deal_info_missing"])
        return _DealCheckResult(
            pricing_mode="per_pallet",
            note="编织袋/柔性包装包干价判定信息不足：件数缺失，需人工确认。",
        )
    if pieces is not None and pieces < deal.min_pieces:
        return _DealCheckResult(pricing_mode="per_pallet")
    if unit_rows:
        stack_unknown = any(unit.stackability == "unknown" for unit in matched)
    else:
        stack_unknown = is_stackable is None
    if stack_unknown:
        _extend_unique(risks, ["flexible_package_deal_info_missing"])
        return _DealCheckResult(
            pricing_mode="per_pallet",
            note="编织袋/柔性包装包干价判定信息不足：堆叠状态缺失，需人工确认。",
        )
    if not stackable:
        return _DealCheckResult(pricing_mode="per_pallet")
    return _DealCheckResult(pricing_mode="flat_rate", quote_usd=deal.quote_usd_per_container)


def _packaging_matches_deal(packaging: str | None, keywords: Sequence[str]) -> bool:
    if not packaging:
        return False
    normalized = _normalize_packaging(packaging)
    alias = _DEAL_PACKAGING_ALIASES.get(normalized, normalized)
    for keyword in keywords:
        if keyword in alias or alias in keyword:
            return True
    return False


def _normalize_packaging(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower()


def _is_wooden_crate(packaging: str) -> bool:
    return packaging in {"wooden_crate", "木箱", "wooden crate"}


def _coerce_rule(
    rule: OversizePalletRuleConfig | Mapping[str, object] | None,
) -> OversizePalletRuleConfig:
    if rule is None:
        return default_oversize_pallet_rule()
    if isinstance(rule, OversizePalletRuleConfig):
        return rule
    if isinstance(rule, Mapping) and rule.get("invalid_reason") is not None:
        # The repository publishes an invalid marker instead of a default when
        # a stored snapshot fails validation.  The lenient v2 model would
        # otherwise ignore the marker and silently quote with v2 defaults,
        # breaking the fail-closed contract for broken published rules.
        raise _RuleConfigurationError("published_snapshot_invalid")
    try:
        return OversizePalletRuleConfig.model_validate(rule)
    except Exception as exc:
        raise _RuleConfigurationError("invalid_rule_configuration") from exc


def _normalize_handling_unit(
    raw: HandlingUnitInput | Mapping[str, object], index: int
) -> tuple[_NormalizedUnit | None, list[str], dict[str, object]]:
    if isinstance(raw, HandlingUnitInput):
        normalized_input = _normalized_trace_input(raw)
        raw_input = _safe_raw_field_summary(normalized_input)
        return (
            _NormalizedUnit(
                index=index,
                unit=raw,
                raw_input=raw_input,
                normalized_input=normalized_input,
            ),
            [],
            {
                "index": index,
                "status": "valid",
                "raw_input": dict(raw_input),
                "raw_field_summary": dict(raw_input),
                "normalized_input": dict(normalized_input),
            },
        )

    if not isinstance(raw, Mapping):
        raw_summary = _safe_raw_field_summary(raw)
        return (
            None,
            ["handling_unit_invalid", "handling_unit_dimensions_missing", "handling_unit_weight_missing"],
            {
                "index": index,
                "status": "invalid",
                "reason": "row_not_mapping",
                "raw_input": raw_summary,
                "raw_field_summary": dict(raw_summary),
                "normalized_input": None,
            },
        )

    payload = dict(raw)
    raw_summary = _safe_raw_field_summary(payload)
    try:
        unit = HandlingUnitInput.model_validate(payload)
        normalized_input = _normalized_trace_input(unit)
        return (
            _NormalizedUnit(
                index=index,
                unit=unit,
                raw_input=raw_summary,
                normalized_input=normalized_input,
            ),
            [],
            {
                "index": index,
                "status": "valid",
                "raw_input": dict(raw_summary),
                "raw_field_summary": dict(raw_summary),
                "normalized_input": dict(normalized_input),
            },
        )
    except ValidationError:
        risks = ["handling_unit_invalid"]
        dimensions = _raw_value(payload, "length_cm", "length")
        width = _raw_value(payload, "width_cm", "width")
        height = _raw_value(payload, "height_cm", "height")
        weight = _raw_value(
            payload,
            "unit_weight_kg",
            "unit_gross_weight",
            "unit_gross_weight_kg",
            "gross_weight_kg",
        )
        quantity = _raw_value(payload, "quantity", "handling_unit_quantity")
        packaging = _raw_value(payload, "packaging_type", "packaging")
        if not _positive_decimal(dimensions) or not _positive_decimal(width) or not _positive_decimal(height):
            risks.append("handling_unit_dimensions_missing")
        if not _positive_decimal(weight):
            risks.append("handling_unit_weight_missing")
        if not _positive_int(quantity):
            risks.append("handling_unit_quantity_missing")
        if not isinstance(packaging, str) or not packaging.strip():
            risks.append("handling_unit_packaging_missing")

        # The published rule treats incomplete stackability evidence as
        # unknown/non-stackable rather than blocking an otherwise complete
        # handling unit.  Pydantic intentionally rejects that shape, so retry
        # with an explicit unknown state after classifying the input above.
        stackability = payload.get("stackability", "unknown")
        stack_constraints_missing = (
            stackability == "stackable"
            and (payload.get("max_stack_layers") is None or payload.get("max_top_load_kg") is None)
        )
        if (
            stack_constraints_missing
            and _positive_decimal(dimensions)
            and _positive_decimal(width)
            and _positive_decimal(height)
            and _positive_decimal(weight)
            and _positive_int(quantity)
            and isinstance(packaging, str)
            and packaging.strip()
        ):
            retry_payload = dict(payload)
            retry_payload["stackability"] = "unknown"
            retry_payload.pop("max_stack_layers", None)
            retry_payload.pop("max_top_load_kg", None)
            try:
                unit = HandlingUnitInput.model_validate(retry_payload)
                normalized_input = _normalized_trace_input(unit)
                return (
                    _NormalizedUnit(
                        index=index,
                        unit=unit,
                        raw_input=raw_summary,
                        normalized_input=normalized_input,
                    ),
                    ["handling_unit_stack_constraints_missing"],
                    {
                        "index": index,
                        "status": "valid",
                        "stackability_normalized": "unknown",
                        "raw_input": dict(raw_summary),
                        "raw_field_summary": dict(raw_summary),
                        "normalized_input": dict(normalized_input),
                    },
                )
            except ValidationError:
                pass

        # Preserve a more precise invalid reason in the audit trace while
        # returning stable public risk tags.
        errors = []
        if not _positive_decimal(dimensions) or not _positive_decimal(width) or not _positive_decimal(height):
            errors.append("dimensions")
        if not _positive_decimal(weight):
            errors.append("weight")
        return (
            None,
            _unique(risks),
            {
                "index": index,
                "status": "invalid",
                "invalid_fields": errors,
                "raw_input": raw_summary,
                "raw_field_summary": dict(raw_summary),
                "normalized_input": None,
            },
        )


def _calculate_unit_line(
    unit: HandlingUnitInput,
    rule: OversizePalletRuleConfig,
    index: int,
) -> dict[str, object]:
    length = unit.length_cm
    width = unit.width_cm
    height = unit.height_cm
    floor_long = max(length, width)
    floor_short = min(length, width)
    floor_area = floor_long * floor_short
    unit_cbm = length * width * height / _MILLION

    # Standard 48x40 pallet positions by floor area (design v2 2.3).  Units
    # that fit within one standard position contribute no positions: their
    # space is already covered by the validated whole-order volume formula
    # (SOP v2.0 bills max(ceil(CBM/2), ceil(KG/500), long, wooden); the 493
    # historical orders match it 100%).  The position branch therefore only
    # guards oversized footprints, where it matches the design examples
    # (122x102 -> 2, 200x130 -> 3, 200x200 -> 4).
    if floor_area <= rule.standard_pallet_area_cm2 * (
        Decimal("1") + rule.pallet_area_tolerance_ratio
    ):
        position_slots = 0
        footprint_band = "standard"
    else:
        position_slots = _ceil_decimal(floor_area / rule.standard_pallet_area_cm2)
        footprint_band = "expansion"

    # Long pieces bill 2 pallets each (design v2 2.6).
    longest_side = max(length, width, height)
    is_long_piece = longest_side > rule.long_piece_threshold_cm
    long_piece_pallets = (
        rule.long_piece_pallets_per_piece if is_long_piece else 0
    )

    # Wooden crates bill >=1 pallet each; long crates bill 2 (design v2 2.6).
    packaging = _normalize_packaging(unit.packaging_type)
    is_wooden_crate = _is_wooden_crate(packaging)
    wooden_crate_pallets = (
        rule.wooden_crate_min_pallets_per_piece if is_wooden_crate else 0
    )
    if is_wooden_crate and is_long_piece:
        wooden_crate_pallets = rule.wooden_crate_long_pallets_per_piece

    # Per-piece hard limits (design v2 2.9).
    floor_slots_exceeded = position_slots > 4
    weight_over_mechanical_limit = (
        unit.unit_weight_kg > rule.mechanical_handling_weight_limit_kg
    )

    quantity = unit.quantity
    line_position_pallets = position_slots * quantity
    line_long_piece_pallets = long_piece_pallets * quantity
    line_wooden_crate_pallets = wooden_crate_pallets * quantity

    return {
        "index": index,
        "packaging_type": unit.packaging_type,
        "quantity": quantity,
        "length_cm": length,
        "width_cm": width,
        "height_cm": height,
        "unit_weight_kg": unit.unit_weight_kg,
        "unit_cbm": unit_cbm,
        "floor_long_cm": floor_long,
        "floor_short_cm": floor_short,
        "floor_area_cm2": floor_area,
        "longest_side_cm": longest_side,
        "is_long_piece": is_long_piece,
        "is_wooden_crate": is_wooden_crate,
        "footprint_band": footprint_band,
        "position_slots": position_slots,
        # Legacy aliases kept for audit consumers that predate v2 naming.
        "unit_size_pallets": position_slots,
        "line_size_pallets": line_position_pallets,
        "line_position_pallets": line_position_pallets,
        "long_piece_pallets": long_piece_pallets,
        "line_long_piece_pallets": line_long_piece_pallets,
        "wooden_crate_pallets": wooden_crate_pallets,
        "line_wooden_crate_pallets": line_wooden_crate_pallets,
        "floor_slots_exceeded": floor_slots_exceeded,
        "weight_over_mechanical_limit": weight_over_mechanical_limit,
        "line_weight_kg": unit.unit_weight_kg * quantity,
        "line_volume_cbm": unit_cbm * quantity,
        "stackability": unit.stackability,
        "max_stack_layers": unit.max_stack_layers,
        "max_top_load_kg": unit.max_top_load_kg,
        "floor_rotation_allowed": unit.floor_rotation_allowed,
    }


def _ceil_decimal(value: Decimal) -> int:
    if value <= _ZERO:
        return 0
    return int(value.to_integral_value(rounding="ROUND_CEILING"))


def _absolute_plus_relative_tolerance(
    derived: Decimal,
    declared: Decimal,
    absolute: Decimal,
    ratio: Decimal,
) -> Decimal:
    basis = max(abs(derived), abs(declared))
    return max(max(_ZERO, absolute), basis * max(_ZERO, ratio))


def _relative_or_absolute_tolerance(
    derived: Decimal,
    declared: Decimal,
    absolute: Decimal,
    ratio: Decimal,
) -> Decimal:
    basis = max(abs(derived), abs(declared))
    return max(max(_ZERO, absolute), basis * max(_ZERO, ratio))


def _relative_or_absolute_tolerance_int(
    derived: int,
    declared: int,
    absolute: int,
    ratio: Decimal,
) -> Decimal:
    basis = max(abs(derived), abs(declared))
    relative = Decimal(basis) * max(_ZERO, ratio)
    return max(Decimal(abs(absolute)), relative)


def _manual_result(
    *,
    billing_pallets: int | None,
    components: dict[str, object],
    risks: Sequence[str],
    oversize_rule: OversizePalletRuleConfig,
    note: str,
    declared_values: Mapping[str, object],
    lines: Sequence[dict[str, object]] = (),
    customer_piece_check: str | None = None,
    trace_metadata: Mapping[str, object] | None = None,
) -> PalletCalculationResult:
    unique_risks = tuple(_unique(list(risks)))
    reconciliation = dict(declared_values)
    if customer_piece_check is not None:
        reconciliation["customer_piece_check"] = customer_piece_check
    trace: dict[str, object] = {
        "rule_id": oversize_rule.rule_id,
        "lines": list(lines),
        "totals": {
            "customer_piece_check": customer_piece_check,
        },
        "reconciliation": reconciliation,
    }
    if trace_metadata:
        trace.update(trace_metadata)
    return PalletCalculationResult(
        billing_pallets=billing_pallets,
        components=components,
        manual_review_required=True,
        risk_tags=unique_risks,
        internal_note=note,
        surcharges={
            "footprint_surcharge": _ZERO,
            "high_board_surcharge": _ZERO,
            "heavy_surcharge": _ZERO,
            "total_surcharge": _ZERO,
        },
        internal_trace=trace,
    )


def _build_manual_note(risks: Sequence[str]) -> str:
    if "billing_pallets_out_of_table" in risks:
        return "计费托数超过价格表上限(26 托)，需供应商确认整车/分票方案。"
    if "oversize_floor_slots_exceeded" in risks:
        return "单个搬运单元地板面积超过 4 个标准托盘位，需人工确认装车或分拆方案。"
    if "unit_weight_over_mechanical_limit" in risks:
        return "单个搬运单元重量超过机械装卸上限，需人工确认装卸设备和承运能力。"
    if "explicit_pallet_count_conflict" in risks:
        return "客户显式托数与推导托数差异超出容差，需人工确认计费口径。"
    if "flexible_package_deal_info_missing" in risks:
        return "编织袋/柔性包装包干价判定信息不足（件数或堆叠状态缺失）。"
    if "aggregate_info_insufficient" in risks:
        return "聚合信息不足以计算托数：总体积与总重量均缺失。"
    if "declared_weight_out_of_tolerance" in risks:
        return "申报总重量与明细推导重量超出容差。"
    if "declared_volume_out_of_tolerance" in risks:
        return "申报总体积与明细推导体积超出容差。"
    if "customer_piece_count_mismatch" in risks:
        return "客户箱件数与搬运单元所含件数超出核对容差。"
    return "handling unit 明细存在缺失或无效字段，需人工确认。"


def _normalized_trace_input(unit: HandlingUnitInput) -> dict[str, object]:
    """Return the canonical, JSON-serializable shape used for replay."""

    return dict(unit.model_dump(mode="python"))


def _rule_validation_trace(rule: object) -> dict[str, object]:
    """Summarize an invalid rule without retaining arbitrary config values."""

    if isinstance(rule, Mapping):
        return {
            "status": "invalid",
            "risk_code": "oversize_rule_invalid",
            "input_type": "mapping",
            "provided_fields": sorted(str(key) for key in rule),
        }
    return {
        "status": "invalid",
        "risk_code": "oversize_rule_invalid",
        "input_type": type(rule).__name__,
        "provided_fields": [],
    }


def _safe_raw_field_summary(raw: object) -> dict[str, object]:
    """Keep only bounded handling-unit fields in audit traces.

    Input rows can arrive from auxiliary parsers, so an invalid row may carry
    arbitrary extra values.  The trace preserves the recognized source fields
    needed to replay validation while excluding unknown values that could
    contain unrelated customer data or non-serializable objects.
    """

    if not isinstance(raw, Mapping):
        return {
            "type": type(raw).__name__,
            "value": _safe_trace_value(raw),
        }
    return {
        key: _safe_trace_value(raw[key])
        for key in _TRACE_INPUT_KEYS
        if key in raw
    }


def _safe_trace_value(value: object) -> object:
    if isinstance(value, Decimal):
        return value if value.is_finite() else str(value)
    if value is None or isinstance(value, (bool, int, str)):
        return value
    # Do not retain arbitrary repr() output from an auxiliary parser in the
    # audit payload.  A type marker is enough to explain why Pydantic rejected
    # the field while keeping the trace bounded and safe.
    return f"<{type(value).__name__}>"


def _raw_value(payload: Mapping[str, object], *keys: str) -> object | None:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _as_decimal(value: object | None) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return decimal_value if decimal_value.is_finite() else None


def _as_int(value: object | None) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    decimal_value = _as_decimal(value)
    if decimal_value is None:
        return None
    if decimal_value != decimal_value.to_integral_value():
        return None
    return int(decimal_value)


def _positive_decimal(value: object | None) -> bool:
    decimal_value = _as_decimal(value)
    return decimal_value is not None and decimal_value > _ZERO


def _positive_int(value: object | None) -> bool:
    integer_value = _as_int(value)
    return integer_value is not None and integer_value >= 1


def _extend_unique(target: list[str], values: Sequence[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _unique(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    _extend_unique(result, values)
    return result


__all__ = ["PalletCalculationResult", "calculate_billing_pallets"]
