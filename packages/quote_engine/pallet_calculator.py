"""Deterministic pallet and surcharge calculations for oversize freight.

The public quote flow historically supplied only an aggregate CBM, weight and
piece count.  Those values are still accepted as keyword arguments so older
callers fail safely, but they are reconciliation fields only.  A successful
calculation always starts with a complete sequence of physical handling units.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pydantic import ValidationError

from packages.quote_engine.oversize_config import (
    OversizePalletRuleConfig,
    default_oversize_pallet_rule,
)
from packages.quote_engine.oversize_models import HandlingUnitInput
from packages.quote_engine.vehicle_packing import PackingStatus, select_vehicle


_MILLION = Decimal("1000000")
_ZERO = Decimal("0")
_SOFT_REVIEW_RISKS = frozenset(
    {
        "customer_piece_count_check_skipped",
        # Missing stack limits are conservatively normalized to unknown, which
        # means the line remains countable for billing but cannot be used to
        # claim a stack in vehicle packing.
        "handling_unit_stack_constraints_missing",
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
    """

    billing_pallets: int | None
    components: dict[str, object]
    manual_review_required: bool = False
    risk_tags: tuple[str, ...] = ()
    internal_note: str | None = None
    surcharges: dict[str, Decimal] = field(default_factory=dict)
    internal_trace: dict[str, object] = field(default_factory=dict)


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
    # compatibility only; none can create a pallet basis by themselves.
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
    never used to invent dimensions, pallets, or long-piece multipliers.
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
    ) or len(handling_units) == 0:
        risks.append("handling_units_missing")
        return _manual_result(
            billing_pallets=None,
            components=empty_components,
            risks=risks,
            oversize_rule=oversize_rule,
            note="完整 handling_units 明细缺失；不能使用 CBM、件数或最长边推导托数。",
            declared_values={
                "declared_customer_piece_count": declared_customer,
                "declared_total_weight_kg": declared_weight,
                "declared_total_volume_cbm": declared_volume,
                "explicit_pallet_count": _safe_trace_value(explicit_pallet_count),
                "explicit_pallet_count_valid": not explicit_invalid,
            },
            customer_piece_check="skipped_missing_rows",
        )

    normalized_units: list[_NormalizedUnit] = []
    invalid_lines: list[dict[str, object]] = []
    for index, raw in enumerate(handling_units):
        normalized, row_risks, row_trace = _normalize_handling_unit(raw, index)
        _extend_unique(risks, row_risks)
        if normalized is None:
            invalid_lines.append(row_trace)
        else:
            normalized_units.append(normalized)

    # We can retain a candidate from valid rows when another row is malformed,
    # but the result remains blocked for automatic quoting.
    lines: list[dict[str, object]] = []
    derived_weight = _ZERO
    derived_volume = _ZERO
    total_size_pallets = 0
    total_footprint_surcharge = _ZERO
    total_high_board_surcharge = _ZERO
    total_heavy_surcharge = _ZERO

    for normalized in normalized_units:
        unit = normalized.unit
        line = _calculate_unit_line(unit, oversize_rule, normalized.index)
        # Keep the source-side reconciliation fields next to the calculated
        # line.  ``unit_cbm`` below is always derived from dimensions; the
        # separate supplied value is retained (including an explicit null) so
        # an audit reader can replay the exact input without confusing the two.
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
        if line["weight_over_auto_limit"]:
            _extend_unique(risks, ["handling_unit_weight_over_auto_limit"])
        if line["height_over_auto_limit"]:
            _extend_unique(risks, ["handling_unit_height_over_auto_limit"])
        quantity = Decimal(unit.quantity)
        derived_weight += unit.unit_weight_kg * quantity
        derived_volume += line["unit_cbm"] * quantity  # type: ignore[operator]
        total_size_pallets += int(line["line_size_pallets"])
        total_footprint_surcharge += line["line_footprint_surcharge"]  # type: ignore[operator]
        total_high_board_surcharge += line["line_high_board_surcharge"]  # type: ignore[operator]
        total_heavy_surcharge += line["line_heavy_surcharge"]  # type: ignore[operator]

    # No usable rows means no candidate billing number.  This is distinct from
    # a usable candidate that is blocked by a declaration or an auto-limit.
    if not normalized_units:
        empty_components["line_count"] = 0
        return _manual_result(
            billing_pallets=None,
            components=empty_components,
            risks=risks or ["handling_unit_invalid"],
            oversize_rule=oversize_rule,
            note="所有 handling unit 明细均无效；尺寸、重量和单位必须完整且已归一化。",
            declared_values={
                "declared_customer_piece_count": declared_customer,
                "declared_total_weight_kg": declared_weight,
                "declared_total_volume_cbm": declared_volume,
                "explicit_pallet_count": _safe_trace_value(explicit_pallet_count),
                "explicit_pallet_count_valid": not explicit_invalid,
            },
            lines=invalid_lines,
            customer_piece_check="skipped_invalid_rows",
        )

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

    # Explicit pallets are only a lower bound.  Invalid values have already
    # been recorded above and the zero candidate is used only for arithmetic;
    # the resulting quote remains manual.
    explicit = explicit_candidate

    weight_pallets = _ceil_decimal(calculation_weight / oversize_rule.weight_basis_kg)
    billing_pallets = max(total_size_pallets, weight_pallets, explicit)

    surcharges = {
        "footprint_surcharge": total_footprint_surcharge,
        "high_board_surcharge": total_high_board_surcharge,
        "heavy_surcharge": total_heavy_surcharge,
        "total_surcharge": (
            total_footprint_surcharge
            + total_high_board_surcharge
            + total_heavy_surcharge
        ),
    }
    components: dict[str, object] = {
        "volume_pallets": 0,
        "long_piece_pallets": 0,
        "wooden_crate_pallets": 0,
        "total_size_pallets": total_size_pallets,
        "weight_pallets": weight_pallets,
        "explicit_pallet_count": explicit,
        "derived_total_weight_kg": derived_weight,
        "calculation_weight_kg": calculation_weight,
        "derived_total_volume_cbm": derived_volume,
        "calculation_total_volume_cbm": calculation_volume,
        "line_count": len(lines),
    }
    internal_trace: dict[str, object] = {
        "rule_id": oversize_rule.rule_id,
        "lines": lines + invalid_lines,
        "totals": {
            "derived_total_weight_kg": derived_weight,
            "calculation_weight_kg": calculation_weight,
            "derived_total_volume_cbm": derived_volume,
            "calculation_total_volume_cbm": calculation_volume,
            "total_size_pallets": total_size_pallets,
            "weight_pallets": weight_pallets,
            "explicit_pallet_count": explicit,
            "explicit_pallet_count_input": _safe_trace_value(explicit_pallet_count),
            "explicit_pallet_count_valid": not explicit_invalid,
            "billing_pallets": billing_pallets,
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

    # Vehicle validation consumes the same physical rows and the adopted
    # order-level totals used above.  It is an internal hard check: vehicle
    # count/layout never multiplies billing pallets, and an uncertain or
    # impossible layout only turns the result into manual review.
    vehicle_result = select_vehicle(
        [normalized.unit for normalized in normalized_units],
        rule=oversize_rule,
        total_weight_kg=calculation_weight,
        total_volume_cbm=calculation_volume,
    )
    if vehicle_result.status is PackingStatus.INCONCLUSIVE:
        _extend_unique(risks, ["oversize_vehicle_inconclusive"])
    elif vehicle_result.status is PackingStatus.PROVEN_NOT_FIT:
        _extend_unique(risks, ["oversize_vehicle_not_fit"])
    vehicle_trace = {
        "status": vehicle_result.status.value,
        "vehicle_code": vehicle_result.vehicle_code,
        "vehicle_count": vehicle_result.vehicle_count,
        "floor_columns": vehicle_result.floor_columns,
        "tight_loading": vehicle_result.tight_loading,
        "volume_cbm": vehicle_result.volume_cbm,
        "payload_kg": vehicle_result.payload_kg,
        "placements": vehicle_result.placements,
        "reason_codes": vehicle_result.reason_codes,
        "vehicle_profiles_checked": vehicle_result.vehicle_profiles_checked,
    }
    internal_trace["vehicle"] = vehicle_trace
    # Keep these direct aliases for audit consumers that predate the nested
    # ``vehicle`` object; both shapes contain the same replayable values.
    internal_trace["vehicle_profiles_checked"] = vehicle_result.vehicle_profiles_checked
    internal_trace["vehicle_result"] = vehicle_trace

    # Row invalidity, declaration mismatches and per-unit auto limits all
    # remain hard blocks.  A candidate number is retained for internal audit;
    # the public Zone DTO is responsible for hiding it on manual results.
    # A partial contained-piece check is an explicit audit state, not a reason
    # to stop an otherwise deterministic quote.  All other risks currently
    # emitted by this calculator are hard blocks.
    manual = any(risk not in _SOFT_REVIEW_RISKS for risk in risks)
    note: str | None = None
    if manual:
        note = _build_manual_note(risks)
    return PalletCalculationResult(
        billing_pallets=billing_pallets,
        components=components,
        manual_review_required=manual,
        risk_tags=tuple(risks),
        internal_note=note,
        surcharges=surcharges,
        internal_trace=internal_trace,
    )


def _coerce_rule(
    rule: OversizePalletRuleConfig | Mapping[str, object] | None,
) -> OversizePalletRuleConfig:
    if rule is None:
        return default_oversize_pallet_rule()
    if isinstance(rule, OversizePalletRuleConfig):
        return rule
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

    footprint_surcharge = _ZERO
    long_grace_hit = False
    short_grace_hit = False
    if floor_long <= rule.standard_pallet_length_cm and floor_short <= rule.standard_pallet_width_cm:
        unit_size_pallets = 1
        footprint_band = "standard"
        effective_long = floor_long
        effective_short = floor_short
        long_slots = 1
        short_slots = 1
        area_ratio = floor_long * floor_short / rule.standard_pallet_area_cm2
        area_slots = 1
    elif floor_long <= rule.mild_oversize_length_cm and floor_short <= rule.mild_oversize_width_cm:
        unit_size_pallets = 1
        footprint_band = "mild"
        footprint_surcharge = rule.footprint_surcharge
        effective_long = floor_long
        effective_short = floor_short
        long_slots = 1
        short_slots = 1
        area_ratio = floor_long * floor_short / rule.standard_pallet_area_cm2
        area_slots = 1
    elif floor_long < rule.expansion_trigger_length_cm and floor_short < rule.expansion_trigger_width_cm:
        unit_size_pallets = 1
        footprint_band = "medium"
        footprint_surcharge = rule.medium_oversize_surcharge
        effective_long = floor_long
        effective_short = floor_short
        long_slots = 1
        short_slots = 1
        area_ratio = floor_long * floor_short / rule.standard_pallet_area_cm2
        area_slots = 1
    else:
        footprint_band = "expansion"
        effective_long, long_grace_hit = _effective_axis(
            floor_long,
            rule.standard_pallet_length_cm,
            rule.expansion_grace_cm,
        )
        effective_short, short_grace_hit = _effective_axis(
            floor_short,
            rule.standard_pallet_width_cm,
            rule.expansion_grace_cm,
        )
        long_slots = _ceil_decimal(effective_long / rule.standard_pallet_length_cm)
        short_slots = _ceil_decimal(effective_short / rule.standard_pallet_width_cm)
        area_ratio = effective_long * effective_short / rule.standard_pallet_area_cm2
        area_slots = _area_slots(area_ratio, rule.area_tolerance_ratio)
        unit_size_pallets = max(2, long_slots, short_slots, area_slots)
        if long_grace_hit or short_grace_hit:
            # Two axes in the same line are one footprint category and one fee.
            footprint_surcharge = rule.footprint_surcharge

    high_board_surcharge = _ZERO
    if height > rule.normal_board_height_cm and height <= rule.high_board_height_cm:
        high_board_surcharge = rule.high_board_surcharge

    heavy_surcharge = _ZERO
    if unit.unit_weight_kg > rule.weight_basis_kg and unit.unit_weight_kg <= rule.unit_auto_weight_max_kg:
        heavy_surcharge = rule.heavy_surcharge

    unit_surcharge = footprint_surcharge + high_board_surcharge + heavy_surcharge
    quantity = unit.quantity
    line_size_pallets = unit_size_pallets * quantity
    line_footprint_surcharge = footprint_surcharge * quantity
    line_high_board_surcharge = high_board_surcharge * quantity
    line_heavy_surcharge = heavy_surcharge * quantity
    unit_cbm = length * width * height / _MILLION

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
        "effective_long_cm": effective_long,
        "effective_short_cm": effective_short,
        "long_slots": long_slots,
        "short_slots": short_slots,
        "area_ratio": area_ratio,
        "area_slots": area_slots,
        "unit_size_pallets": unit_size_pallets,
        "line_size_pallets": line_size_pallets,
        "footprint_band": footprint_band,
        "long_grace_hit": long_grace_hit,
        "short_grace_hit": short_grace_hit,
        "boundary_grace_hit": long_grace_hit or short_grace_hit,
        "footprint_surcharge": footprint_surcharge,
        "high_board_surcharge": high_board_surcharge,
        "heavy_surcharge": heavy_surcharge,
        "unit_surcharge": unit_surcharge,
        "line_footprint_surcharge": line_footprint_surcharge,
        "line_high_board_surcharge": line_high_board_surcharge,
        "line_heavy_surcharge": line_heavy_surcharge,
        "line_surcharge": unit_surcharge * quantity,
        "line_weight_kg": unit.unit_weight_kg * quantity,
        "line_volume_cbm": unit_cbm * quantity,
        "weight_over_auto_limit": unit.unit_weight_kg > rule.unit_auto_weight_max_kg,
        "height_over_auto_limit": height > rule.high_board_height_cm,
        "stackability": unit.stackability,
        "max_stack_layers": unit.max_stack_layers,
        "max_top_load_kg": unit.max_top_load_kg,
        "floor_rotation_allowed": unit.floor_rotation_allowed,
    }


def _effective_axis(
    dimension: Decimal,
    pallet_dimension: Decimal,
    grace: Decimal,
) -> tuple[Decimal, bool]:
    completed_slots = int(dimension // pallet_dimension)
    remainder = dimension - Decimal(completed_slots) * pallet_dimension
    if completed_slots >= 1 and _ZERO < remainder <= grace:
        return Decimal(completed_slots) * pallet_dimension, True
    return dimension, False


def _area_slots(area_ratio: Decimal, tolerance_ratio: Decimal) -> int:
    lower_integer = max(1, int(area_ratio))
    if area_ratio <= Decimal(lower_integer) * (Decimal("1") + tolerance_ratio):
        return lower_integer
    return _ceil_decimal(area_ratio)


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
    if "oversize_vehicle_inconclusive" in risks:
        return "车辆排布搜索达到节点上限，需人工确认装车方案。"
    if "oversize_vehicle_not_fit" in risks:
        return "现有车辆档案无法证明装下该批搬运单元，需人工确认车型或拆分方案。"
    if "handling_unit_weight_over_auto_limit" in risks:
        return "单个搬运单元重量超过自动边界，需人工确认装卸设备和承运能力。"
    if "handling_unit_height_over_auto_limit" in risks:
        return "单个搬运单元高度超过自动边界，需人工确认车辆门高和固定方式。"
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
