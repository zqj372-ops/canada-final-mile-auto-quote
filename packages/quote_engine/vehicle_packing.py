"""Deterministic vehicle-capacity and floor-packing checks.

The pallet calculator and the public quote DTO deliberately use different
units of measure.  This module works only with the physical handling units
and vehicle profiles, and therefore never turns a vehicle count into extra
billable pallets.  Packing is a bounded, deterministic rectangle search:
when the bound is reached the answer is ``INCONCLUSIVE`` rather than a false
``PROVEN_NOT_FIT``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from itertools import combinations_with_replacement
from typing import Iterable, Mapping, Sequence

from packages.quote_engine.oversize_config import (
    OversizePalletRuleConfig,
    VehicleProfile,
    default_oversize_pallet_rule,
)
from packages.quote_engine.oversize_models import HandlingUnitInput


_MILLION = Decimal("1000000")
_ZERO = Decimal("0")
_BUILTIN_STANDARD_FLOOR_DIMENSIONS = {
    "26_non_cdl": (Decimal("762"), Decimal("243.84")),
    "26_cdl": (Decimal("762"), Decimal("243.84")),
    "53_dry_van": (Decimal("1600.2"), Decimal("250.19")),
}


class PackingStatus(StrEnum):
    """Three-state result used by both a single vehicle and auto selection."""

    FIT = "FIT"
    PROVEN_NOT_FIT = "PROVEN_NOT_FIT"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class VehiclePackingResult:
    """Internal, replayable result of vehicle validation."""

    status: PackingStatus
    vehicle_code: str
    vehicle_count: int
    floor_columns: int
    volume_cbm: Decimal
    payload_kg: Decimal
    tight_loading: bool
    placements: tuple[dict[str, object], ...]
    reason_codes: tuple[str, ...]
    # Candidate details are intentionally optional.  They are useful to the
    # audit layer, while the explicit fields above keep the stable contract
    # small for existing callers.
    vehicle_profiles_checked: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class _PhysicalUnit:
    """One physical handling unit, retaining its source row and ordinal."""

    row_index: int
    unit_index: int
    unit: HandlingUnitInput


@dataclass(frozen=True)
class _FloorColumn:
    """A rectangle on the vehicle floor, possibly containing stacked units."""

    units: tuple[_PhysicalUnit, ...]
    layers: int
    length_cm: Decimal
    width_cm: Decimal
    height_cm: Decimal
    weight_kg: Decimal
    volume_cbm: Decimal
    orientation: str


@dataclass(frozen=True)
class _Layout:
    columns: tuple[_FloorColumn, ...]
    placements: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class _SearchOutcome:
    status: PackingStatus
    layout: _Layout | None
    nodes: int


class _NodeLimitReached(RuntimeError):
    pass


def pack_vehicle(
    handling_units: Sequence[HandlingUnitInput | Mapping[str, object]],
    profile: VehicleProfile,
    *,
    rule: OversizePalletRuleConfig | Mapping[str, object] | None = None,
    total_weight_kg: Decimal | int | float | str | None = None,
    total_volume_cbm: Decimal | int | float | str | None = None,
    payload_kg: Decimal | int | float | str | None = None,
    volume_cbm: Decimal | int | float | str | None = None,
) -> VehiclePackingResult:
    """Validate one vehicle with deterministic 2-D DFS.

    ``total_weight_kg``/``total_volume_cbm`` (and their short aliases) allow
    the pallet calculator to pass tolerance-adjusted order totals.  When they
    are omitted, totals are derived from physical dimensions and unit weights.
    """

    try:
        oversize_rule = _coerce_rule(rule)
    except Exception:
        return _result(
            PackingStatus.INCONCLUSIVE,
            profile,
            vehicle_count=1,
            floor_columns=0,
            volume=_coerce_decimal(
                total_volume_cbm if total_volume_cbm is not None else volume_cbm
            )
            or _ZERO,
            weight=_coerce_decimal(
                total_weight_kg if total_weight_kg is not None else payload_kg
            )
            or _ZERO,
            placements=(),
            reasons=("oversize_rule_invalid",),
        )
    try:
        rows = _coerce_units(handling_units)
    except ValueError:
        return _result(
            PackingStatus.PROVEN_NOT_FIT,
            profile,
            vehicle_count=1,
            floor_columns=0,
            volume=_ZERO,
            weight=_ZERO,
            placements=(),
            reasons=("handling_unit_invalid",),
        )
    selected_weight = _coerce_decimal(
        total_weight_kg if total_weight_kg is not None else payload_kg
    )
    selected_volume = _coerce_decimal(
        total_volume_cbm if total_volume_cbm is not None else volume_cbm
    )
    physical = _expand_units(rows)
    derived_weight = sum((item.unit.unit_weight_kg for item in physical), _ZERO)
    derived_volume = sum(
        (item.unit.length_cm * item.unit.width_cm * item.unit.height_cm / _MILLION for item in physical),
        _ZERO,
    )
    weight = derived_weight if selected_weight is None else selected_weight
    volume = derived_volume if selected_volume is None else selected_volume

    reasons: list[str] = []
    # Dimension failures are checked before aggregate capacity so a shipment
    # that is physically too large keeps the more useful hard reason even when
    # its resulting CBM also exceeds the truck limit.
    if physical:
        for item in physical:
            if item.unit.height_cm > profile.height_cm or not _has_allowed_orientation(item.unit, profile):
                reasons.append("unit_dimensions_exceed_vehicle")
                break
    if weight < _ZERO or not weight.is_finite():
        reasons.append("vehicle_payload_invalid")
    if volume < _ZERO or not volume.is_finite():
        reasons.append("vehicle_volume_invalid")
    if weight > profile.payload_kg:
        reasons.append("vehicle_payload_exceeded")
    if volume > profile.volume_cbm:
        reasons.append("vehicle_volume_exceeded")
    if reasons:
        # A capacity violation is a proof independent of floor search.  Keep
        # the result deterministic and avoid spending nodes on an impossible
        # candidate.
        return _result(
            PackingStatus.PROVEN_NOT_FIT,
            profile,
            vehicle_count=1,
            floor_columns=0,
            volume=volume,
            weight=weight,
            placements=(),
            reasons=reasons,
        )

    if not physical:
        return _result(
            PackingStatus.PROVEN_NOT_FIT,
            profile,
            vehicle_count=1,
            floor_columns=0,
            volume=volume,
            weight=weight,
            placements=(),
            reasons=("handling_units_missing",),
        )

    columns, dimension_reasons = _build_columns(physical, profile, oversize_rule)
    if dimension_reasons:
        return _result(
            PackingStatus.PROVEN_NOT_FIT,
            profile,
            vehicle_count=1,
            floor_columns=0,
            volume=volume,
            weight=weight,
            placements=(),
            reasons=dimension_reasons,
        )

    area = sum((column.length_cm * column.width_cm for column in columns), _ZERO)
    if area > profile.length_cm * profile.width_cm:
        return _result(
            PackingStatus.PROVEN_NOT_FIT,
            profile,
            vehicle_count=1,
            floor_columns=0,
            volume=volume,
            weight=weight,
            placements=(),
            reasons=("vehicle_floor_area_exceeded",),
        )

    limit = oversize_rule.packing_node_limit
    search = _search_layout(columns, profile, limit)
    if search.status is PackingStatus.FIT and search.layout is not None:
        placement_rows = _position_layout(search.layout, profile)
        floor_count = len(search.layout.columns)
        tight = floor_count > profile.common_pallet_limit
        return _result(
            PackingStatus.FIT,
            profile,
            vehicle_count=1,
            floor_columns=floor_count,
            volume=volume,
            weight=weight,
            placements=placement_rows,
            reasons=(),
            tight_loading=tight,
        )
    status = search.status
    reason_codes = ("packing_node_limit",) if status is PackingStatus.INCONCLUSIVE else (
        "vehicle_floor_layout_not_fit",
    )
    return _result(
        status,
        profile,
        vehicle_count=1,
        floor_columns=0,
        volume=volume,
        weight=weight,
        placements=(),
        reasons=reason_codes,
    )


def select_vehicle(
    handling_units: Sequence[HandlingUnitInput | Mapping[str, object]],
    *,
    rule: OversizePalletRuleConfig | Mapping[str, object] | None = None,
    total_weight_kg: Decimal | int | float | str | None = None,
    total_volume_cbm: Decimal | int | float | str | None = None,
    payload_kg: Decimal | int | float | str | None = None,
    volume_cbm: Decimal | int | float | str | None = None,
) -> VehiclePackingResult:
    """Select the smallest stable vehicle plan, up to three vehicles.

    A candidate marked ``INCONCLUSIVE`` is never hidden by trying a larger
    truck or extra trucks.  Only candidates proven impossible can advance to
    the next vehicle/profile combination.
    """

    try:
        oversize_rule = _coerce_rule(rule)
    except Exception:
        return _result(
            PackingStatus.INCONCLUSIVE,
            "",
            vehicle_count=0,
            floor_columns=0,
            volume=_coerce_decimal(
                total_volume_cbm if total_volume_cbm is not None else volume_cbm
            )
            or _ZERO,
            weight=_coerce_decimal(
                total_weight_kg if total_weight_kg is not None else payload_kg
            )
            or _ZERO,
            placements=(),
            reasons=("oversize_rule_invalid",),
        )
    try:
        _coerce_units(handling_units)
    except ValueError:
        return _result(
            PackingStatus.PROVEN_NOT_FIT,
            "",
            vehicle_count=0,
            floor_columns=0,
            volume=_ZERO,
            weight=_ZERO,
            placements=(),
            reasons=("handling_unit_invalid",),
        )
    profiles = tuple(oversize_rule.vehicle_profiles)
    checked: list[dict[str, object]] = []
    one_vehicle_results: list[VehiclePackingResult] = []
    for vehicle in profiles:
        result = pack_vehicle(
            handling_units,
            vehicle,
            rule=oversize_rule,
            total_weight_kg=total_weight_kg,
            total_volume_cbm=total_volume_cbm,
            payload_kg=payload_kg,
            volume_cbm=volume_cbm,
        )
        one_vehicle_results.append(result)
        checked.append(_candidate_trace(result))
        if result.status is PackingStatus.INCONCLUSIVE:
            return _with_checked(result, checked)

    fit = [result for result in one_vehicle_results if result.status is PackingStatus.FIT]
    if fit:
        fit_profiles = [
            profile
            for profile in profiles
            if any(result.vehicle_code == profile.code for result in fit)
        ]
        chosen = min(
            fit,
            key=lambda item: _vehicle_tie_key(item, profiles, price_context=fit_profiles),
        )
        return _with_checked(chosen, checked)

    # A hard per-unit dimension failure cannot be fixed by adding vehicles.
    if any("unit_dimensions_exceed_vehicle" in result.reason_codes for result in one_vehicle_results):
        return _with_checked(
            _result(
                PackingStatus.PROVEN_NOT_FIT,
                _empty_profile_code(profiles),
                vehicle_count=0,
                floor_columns=0,
                volume=_adopted_total(handling_units, total_volume_cbm, volume_cbm, kind="volume"),
                weight=_adopted_total(handling_units, total_weight_kg, payload_kg, kind="weight"),
                placements=(),
                reasons=("unit_dimensions_exceed_vehicle",),
            ),
            checked,
        )

    # Try deterministic multi-vehicle assignments only after every one-truck
    # candidate has been exhaustively proven impossible.  We try combinations
    # of configured profiles, allowing repeated vehicles, and keep at most the
    # configured maximum vehicle count.
    for vehicle_count in range(2, oversize_rule.max_auto_vehicles + 1):
        plans: list[VehiclePackingResult] = []
        for profile_combo in combinations_with_replacement(profiles, vehicle_count):
            plan = _pack_multi_vehicle(
                handling_units,
                profile_combo,
                oversize_rule,
                total_weight_kg=total_weight_kg,
                total_volume_cbm=total_volume_cbm,
                payload_kg=payload_kg,
                volume_cbm=volume_cbm,
            )
            checked.append(_candidate_trace(plan))
            if plan.status is PackingStatus.INCONCLUSIVE:
                return _with_checked(plan, checked)
            if plan.status is PackingStatus.FIT:
                plans.append(plan)
        if plans:
            chosen = min(
                plans,
                key=lambda item: _multi_vehicle_tie_key(
                    item, profiles, price_context=plans
                ),
            )
            return _with_checked(chosen, checked)

    # No combination up to the policy limit was possible.  This is a proven
    # failure once all individual searches completed, and is intentionally not
    # represented as a fourth virtual vehicle.
    reasons = ["max_auto_vehicles_exceeded"]
    return _with_checked(
        _result(
            PackingStatus.PROVEN_NOT_FIT,
            _empty_profile_code(profiles),
            vehicle_count=0,
            floor_columns=0,
            volume=_adopted_total(handling_units, total_volume_cbm, volume_cbm, kind="volume"),
            weight=_adopted_total(handling_units, total_weight_kg, payload_kg, kind="weight"),
            placements=(),
            reasons=reasons,
        ),
        checked,
    )


def _pack_multi_vehicle(
    handling_units: Sequence[HandlingUnitInput | Mapping[str, object]],
    profiles: Sequence[VehicleProfile],
    rule: OversizePalletRuleConfig,
    *,
    total_weight_kg: Decimal | int | float | str | None,
    total_volume_cbm: Decimal | int | float | str | None,
    payload_kg: Decimal | int | float | str | None,
    volume_cbm: Decimal | int | float | str | None,
) -> VehiclePackingResult:
    """Try a stable first-fit assignment for one vehicle-profile tuple."""

    rows = _coerce_units(handling_units)
    physical = _expand_units(rows)
    adopted_weight = _coerce_decimal(
        total_weight_kg if total_weight_kg is not None else payload_kg
    )
    adopted_volume = _coerce_decimal(
        total_volume_cbm if total_volume_cbm is not None else volume_cbm
    )
    derived_weight = sum((item.unit.unit_weight_kg for item in physical), _ZERO)
    derived_volume = sum(
        (
            item.unit.length_cm
            * item.unit.width_cm
            * item.unit.height_cm
            / _MILLION
            for item in physical
        ),
        _ZERO,
    )
    adopted_weight = derived_weight if adopted_weight is None else adopted_weight
    adopted_volume = derived_volume if adopted_volume is None else adopted_volume
    if adopted_weight > sum((profile.payload_kg for profile in profiles), _ZERO):
        return _result(
            PackingStatus.PROVEN_NOT_FIT,
            "+".join(profile.code for profile in profiles),
            vehicle_count=len(profiles),
            floor_columns=0,
            volume=adopted_volume,
            weight=adopted_weight,
            placements=(),
            reasons=("vehicle_payload_exceeded",),
        )
    if adopted_volume > sum((profile.volume_cbm for profile in profiles), _ZERO):
        return _result(
            PackingStatus.PROVEN_NOT_FIT,
            "+".join(profile.code for profile in profiles),
            vehicle_count=len(profiles),
            floor_columns=0,
            volume=adopted_volume,
            weight=adopted_weight,
            placements=(),
            reasons=("vehicle_volume_exceeded",),
        )
    if physical and _all_same_floor_unit(physical):
        capacity = sum(
            (_homogeneous_floor_capacity(physical[0].unit, profile, rule) for profile in profiles),
            0,
        )
        if len(physical) > capacity:
            return _result(
                PackingStatus.PROVEN_NOT_FIT,
                "+".join(profile.code for profile in profiles),
                vehicle_count=len(profiles),
                floor_columns=0,
                volume=adopted_volume,
                weight=adopted_weight,
                placements=(),
                reasons=("vehicle_group_layout_not_fit",),
            )
    # Assigning physical units in the same deterministic order used by DFS
    # avoids dependence on set/dict traversal and keeps repeated calls equal.
    physical = tuple(sorted(physical, key=_physical_sort_key))
    assignments: list[list[_PhysicalUnit]] = [[] for _ in profiles]
    # First-fit is enough for regular pallet batches and avoids an exponential
    # search over symmetric assignments.  Each tentative bucket is validated
    # with the same single-vehicle checker, so no virtual pallet or capacity
    # shortcut is introduced.
    greedy_assignments: list[list[_PhysicalUnit]] = [[] for _ in profiles]
    greedy_failed = False
    greedy_inconclusive = False
    for item in physical:
        placed = False
        for vehicle_index, profile in enumerate(profiles):
            candidate_bucket = greedy_assignments[vehicle_index] + [item]
            trial_result = pack_vehicle(_physical_to_units(candidate_bucket), profile, rule=rule)
            if trial_result.status is PackingStatus.FIT and not _bucket_within_adopted_capacity(
                candidate_bucket,
                physical,
                profile,
                total_weight_kg=adopted_weight,
                total_volume_cbm=adopted_volume,
            ):
                trial_result = _result(
                    PackingStatus.PROVEN_NOT_FIT,
                    profile,
                    vehicle_count=1,
                    floor_columns=trial_result.floor_columns,
                    volume=trial_result.volume_cbm,
                    weight=trial_result.payload_kg,
                    placements=(),
                    reasons=("vehicle_payload_exceeded",),
                )
            if trial_result.status is PackingStatus.FIT:
                greedy_assignments[vehicle_index].append(item)
                placed = True
                break
            if trial_result.status is PackingStatus.INCONCLUSIVE:
                greedy_inconclusive = True
        if not placed:
            greedy_failed = True
            break
    if not greedy_failed:
        active_buckets = [
            (profile, bucket)
            for bucket, profile in zip(greedy_assignments, profiles)
            if bucket
        ]
        allocations = _allocate_bucket_totals(
            active_buckets,
            total_weight_kg=total_weight_kg,
            payload_kg=payload_kg,
            total_volume_cbm=total_volume_cbm,
            volume_cbm=volume_cbm,
        )
        result_rows = [
            pack_vehicle(
                _physical_to_units(bucket),
                profile,
                rule=rule,
                total_weight_kg=allocated_weight,
                total_volume_cbm=allocated_volume,
            )
            for (profile, bucket), (allocated_weight, allocated_volume) in zip(
                active_buckets, allocations
            )
        ]
        if result_rows and all(result.status is PackingStatus.FIT for result in result_rows):
            placement_rows: list[dict[str, object]] = []
            floor_columns = 0
            tight = False
            for result in result_rows:
                placement_rows.extend(result.placements)
                floor_columns += result.floor_columns
                tight = tight or result.tight_loading
            return _result(
                PackingStatus.FIT,
                "+".join(profile.code for profile in profiles),
                vehicle_count=len(profiles),
                floor_columns=floor_columns,
                volume=sum((result.volume_cbm for result in result_rows), _ZERO),
                weight=sum((result.payload_kg for result in result_rows), _ZERO),
                placements=tuple(placement_rows),
                reasons=(),
                tight_loading=tight,
            )
    elif greedy_inconclusive:
        return _result(
            PackingStatus.INCONCLUSIVE,
            "+".join(profile.code for profile in profiles),
            vehicle_count=len(profiles),
            floor_columns=0,
            volume=_adopted_total(handling_units, total_volume_cbm, volume_cbm, kind="volume"),
            weight=_adopted_total(handling_units, total_weight_kg, payload_kg, kind="weight"),
            placements=(),
            reasons=("packing_node_limit",),
        )
    # A bounded backtracking assignment calls pack_vehicle for each complete
    # candidate.  The package is deliberately conservative: if there is no
    # proof within the global node budget, return INCONCLUSIVE.
    node_limit = rule.packing_node_limit
    nodes = 0

    def recurse(index: int) -> tuple[VehiclePackingResult, ...] | None:
        nonlocal nodes
        nodes += 1
        if nodes > node_limit:
            raise _NodeLimitReached
        if index >= len(physical):
            result_rows: list[VehiclePackingResult] = []
            active_buckets = [
                (profile, assigned)
                for profile, assigned in zip(profiles, assignments)
                if assigned
            ]
            allocations = _allocate_bucket_totals(
                active_buckets,
                total_weight_kg=total_weight_kg,
                payload_kg=payload_kg,
                total_volume_cbm=total_volume_cbm,
                volume_cbm=volume_cbm,
            )
            for (profile, assigned), (allocated_weight, allocated_volume) in zip(
                active_buckets, allocations
            ):
                grouped = _physical_to_units(assigned)
                result_rows.append(
                    pack_vehicle(
                        grouped,
                        profile,
                        rule=rule,
                        total_weight_kg=allocated_weight,
                        total_volume_cbm=allocated_volume,
                    )
                )
            if all(result.status is PackingStatus.FIT for result in result_rows):
                return tuple(result_rows)
            if any(result.status is PackingStatus.INCONCLUSIVE for result in result_rows):
                raise _NodeLimitReached
            return None
        item = physical[index]
        # Try every vehicle bucket in stable profile order.  A state key based
        # only on bucket lengths is unsafe here: two buckets with equal counts
        # can contain different footprints and therefore have different future
        # feasibility.  Keep the exhaustive branches and let the node bound
        # provide the deterministic safety valve.
        for vehicle_index, profile in enumerate(profiles):
            assignments[vehicle_index].append(item)
            partial = pack_vehicle(
                _physical_to_units(assignments[vehicle_index]), profile, rule=rule
            )
            if partial.status is PackingStatus.FIT and not _bucket_within_adopted_capacity(
                assignments[vehicle_index],
                physical,
                profile,
                total_weight_kg=adopted_weight,
                total_volume_cbm=adopted_volume,
            ):
                partial = _result(
                    PackingStatus.PROVEN_NOT_FIT,
                    profile,
                    vehicle_count=1,
                    floor_columns=partial.floor_columns,
                    volume=partial.volume_cbm,
                    weight=partial.payload_kg,
                    placements=(),
                    reasons=("vehicle_payload_exceeded",),
                )
            if partial.status is PackingStatus.PROVEN_NOT_FIT:
                assignments[vehicle_index].pop()
                continue
            if partial.status is PackingStatus.INCONCLUSIVE:
                assignments[vehicle_index].pop()
                raise _NodeLimitReached
            result = recurse(index + 1)
            if result is not None:
                return result
            assignments[vehicle_index].pop()
        return None

    try:
        result_rows = recurse(0)
    except _NodeLimitReached:
        return _result(
            PackingStatus.INCONCLUSIVE,
            "+".join(profile.code for profile in profiles),
            vehicle_count=len(profiles),
            floor_columns=0,
            volume=_adopted_total(handling_units, total_volume_cbm, volume_cbm, kind="volume"),
            weight=_adopted_total(handling_units, total_weight_kg, payload_kg, kind="weight"),
            placements=(),
            reasons=("packing_node_limit",),
        )
    if result_rows is None:
        return _result(
            PackingStatus.PROVEN_NOT_FIT,
            "+".join(profile.code for profile in profiles),
            vehicle_count=len(profiles),
            floor_columns=0,
            volume=_adopted_total(handling_units, total_volume_cbm, volume_cbm, kind="volume"),
            weight=_adopted_total(handling_units, total_weight_kg, payload_kg, kind="weight"),
            placements=(),
            reasons=("vehicle_group_layout_not_fit",),
        )
    placement_rows: list[dict[str, object]] = []
    floor_columns = 0
    tight = False
    for result in result_rows:
        placement_rows.extend(result.placements)
        floor_columns += result.floor_columns
        tight = tight or result.tight_loading
    return _result(
        PackingStatus.FIT,
        "+".join(profile.code for profile in profiles),
        vehicle_count=len(profiles),
        floor_columns=floor_columns,
        volume=sum((result.volume_cbm for result in result_rows), _ZERO),
        weight=sum((result.payload_kg for result in result_rows), _ZERO),
        placements=tuple(placement_rows),
        reasons=(),
        tight_loading=tight,
    )


def _allocate_bucket_totals(
    active_buckets: Sequence[tuple[VehicleProfile, Sequence[_PhysicalUnit]]],
    *,
    total_weight_kg: Decimal | int | float | str | None,
    payload_kg: Decimal | int | float | str | None,
    total_volume_cbm: Decimal | int | float | str | None,
    volume_cbm: Decimal | int | float | str | None,
) -> tuple[tuple[Decimal, Decimal], ...]:
    """Allocate adopted order totals across non-empty vehicle buckets.

    The proportional allocation is performed with ``Decimal`` values and the
    final bucket receives the exact remainder, so the per-vehicle values sum
    to the adopted order totals without introducing a rounding discrepancy.
    """

    if not active_buckets:
        return ()
    all_items = [item for _, bucket in active_buckets for item in bucket]
    derived_weight = sum((item.unit.unit_weight_kg for item in all_items), _ZERO)
    derived_volume = sum(
        (
            item.unit.length_cm
            * item.unit.width_cm
            * item.unit.height_cm
            / _MILLION
            for item in all_items
        ),
        _ZERO,
    )
    adopted_weight = _coerce_decimal(
        total_weight_kg if total_weight_kg is not None else payload_kg
    )
    adopted_volume = _coerce_decimal(
        total_volume_cbm if total_volume_cbm is not None else volume_cbm
    )
    adopted_weight = derived_weight if adopted_weight is None else adopted_weight
    adopted_volume = derived_volume if adopted_volume is None else adopted_volume

    bucket_weights = [
        sum((item.unit.unit_weight_kg for item in bucket), _ZERO)
        for _, bucket in active_buckets
    ]
    bucket_volumes = [
        sum(
            (
                item.unit.length_cm
                * item.unit.width_cm
                * item.unit.height_cm
                / _MILLION
                for item in bucket
            ),
            _ZERO,
        )
        for _, bucket in active_buckets
    ]

    allocations: list[tuple[Decimal, Decimal]] = []
    allocated_weight = _ZERO
    allocated_volume = _ZERO
    last_index = len(active_buckets) - 1
    for index, (bucket_weight, bucket_volume) in enumerate(
        zip(bucket_weights, bucket_volumes)
    ):
        if index == last_index:
            weight = adopted_weight - allocated_weight
            volume = adopted_volume - allocated_volume
        else:
            weight = (
                bucket_weight * adopted_weight / derived_weight
                if derived_weight > _ZERO
                else _ZERO
            )
            volume = (
                bucket_volume * adopted_volume / derived_volume
                if derived_volume > _ZERO
                else _ZERO
            )
        allocations.append((weight, volume))
        allocated_weight += weight
        allocated_volume += volume
    return tuple(allocations)


def _bucket_within_adopted_capacity(
    bucket: Sequence[_PhysicalUnit],
    all_items: Sequence[_PhysicalUnit],
    profile: VehicleProfile,
    *,
    total_weight_kg: Decimal,
    total_volume_cbm: Decimal,
) -> bool:
    """Check proportional adopted totals for a tentative bucket."""

    derived_weight = sum((item.unit.unit_weight_kg for item in all_items), _ZERO)
    derived_volume = sum(
        (
            item.unit.length_cm
            * item.unit.width_cm
            * item.unit.height_cm
            / _MILLION
            for item in all_items
        ),
        _ZERO,
    )
    bucket_weight = sum((item.unit.unit_weight_kg for item in bucket), _ZERO)
    bucket_volume = sum(
        (
            item.unit.length_cm
            * item.unit.width_cm
            * item.unit.height_cm
            / _MILLION
            for item in bucket
        ),
        _ZERO,
    )
    allocated_weight = (
        bucket_weight * total_weight_kg / derived_weight
        if derived_weight > _ZERO
        else _ZERO
    )
    allocated_volume = (
        bucket_volume * total_volume_cbm / derived_volume
        if derived_volume > _ZERO
        else _ZERO
    )
    return allocated_weight <= profile.payload_kg and allocated_volume <= profile.volume_cbm


def _all_same_floor_unit(physical: Sequence[_PhysicalUnit]) -> bool:
    first = physical[0].unit
    # The shortcut is valid only for a genuinely homogeneous source row.  In
    # particular, weight and stack constraints affect whether a floor column
    # can be built, so dimensions alone are not enough to prove capacity.
    return all(item.unit == first for item in physical)


def _homogeneous_floor_capacity(
    unit: HandlingUnitInput,
    profile: VehicleProfile,
    rule: OversizePalletRuleConfig,
) -> int:
    """Return a stack-aware upper bound for congruent floor units."""

    if not _has_allowed_orientation(unit, profile):
        return 0
    options = _unit_orientations(unit)
    capacities = [
        int(profile.length_cm // length) * int(profile.width_cm // width)
        for length, width, _ in options
    ]
    floor_capacity = max(capacities, default=0)
    if floor_capacity == 0:
        return 0

    layers = 1
    if (
        unit.stackability == "stackable"
        and unit.max_stack_layers is not None
        and unit.max_top_load_kg is not None
    ):
        layers = min(
            unit.max_stack_layers,
            int(profile.height_cm // unit.height_cm),
            int(rule.high_board_height_cm // unit.height_cm),
        )
        while layers > 1 and (layers - 1) * unit.unit_weight_kg > unit.max_top_load_kg:
            layers -= 1
        layers = max(layers, 1)
    return floor_capacity * layers


def _search_layout(columns: Sequence[_FloorColumn], profile: VehicleProfile, limit: int) -> _SearchOutcome:
    ordered = tuple(sorted(columns, key=_column_sort_key))
    if _fast_standard_pallet_count_failure(ordered, profile):
        return _SearchOutcome(PackingStatus.PROVEN_NOT_FIT, None, 0)
    if _fast_exact_floor_failure(ordered, profile):
        return _SearchOutcome(PackingStatus.PROVEN_NOT_FIT, None, 0)
    # A deterministic bottom-left pass finds the common regular-grid layouts
    # (including 14 standard pallets on a 26-foot floor and 30 on a 53-foot
    # floor) without burning the bounded backtracking budget on symmetric
    # alternatives.  A node bound smaller than one visit per item remains
    # inconclusive, just as the DFS would be.
    if limit >= len(ordered) + 1:
        greedy = _greedy_layout(ordered, profile)
        if greedy is not None:
            return _SearchOutcome(PackingStatus.FIT, greedy, len(ordered) + 1)
    # ``placed`` retains selected orientation dimensions.  The source column
    # itself stores its original dimensions; orientation is a property of a
    # particular layout branch and must therefore be carried here.
    placed: list[tuple[_FloorColumn, Decimal, Decimal, Decimal, Decimal, str]] = []
    nodes = 0

    def recurse(index: int) -> _Layout | None:
        nonlocal nodes
        nodes += 1
        if nodes > limit:
            raise _NodeLimitReached
        if index >= len(ordered):
            placements = tuple(
                {
                    "unit_index": column.units[0].unit_index,
                    "source_row_index": column.units[0].row_index,
                    "x_cm": x,
                    "y_cm": y,
                    "length_cm": length,
                    "width_cm": width,
                    "height_cm": column.height_cm,
                    "unit_quantity": len(column.units),
                    "layers": column.layers,
                    "orientation": orientation,
                }
                for column, x, y, length, width, orientation in placed
            )
            return _Layout(tuple(column for column, _, _, _, _, _ in placed), placements)

        column = ordered[index]
        orientations = _column_orientations(column)
        candidates: list[tuple[Decimal, Decimal, str, Decimal, Decimal]] = []
        # A complete bottom-left candidate set is the Cartesian product of all
        # x and y rectangle boundaries.  The former L-shaped corner set
        # (x+length,y) and (x,y+width) misses valid placements such as a
        # rectangle whose x edge comes from one existing unit while its y edge
        # comes from another.  Include vehicle boundaries and the current
        # rectangle's right/top edge so edge-aligned placements are represented
        # deterministically as well.
        x_boundaries = {Decimal("0"), profile.length_cm}
        y_boundaries = {Decimal("0"), profile.width_cm}
        for existing, x, y, existing_length, existing_width, _ in placed:
            x_boundaries.update((x, x + existing_length))
            y_boundaries.update((y, y + existing_width))
        for length, width, orientation in orientations:
            x_candidates = set(x_boundaries)
            y_candidates = set(y_boundaries)
            x_candidates.add(profile.length_cm - length)
            y_candidates.add(profile.width_cm - width)
            for x in x_candidates:
                for y in y_candidates:
                    if x + length <= profile.length_cm and y + width <= profile.width_cm:
                        if all(
                            not _overlap(
                                x,
                                y,
                                length,
                                width,
                                other_x,
                                other_y,
                                other_length,
                                other_width,
                            )
                            for other, other_x, other_y, other_length, other_width, _ in placed
                        ):
                            candidates.append((y, x, orientation, length, width))
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        # A candidate can be produced more than once when dimensions share
        # corners; dedupe without relying on set iteration order.
        seen: set[tuple[Decimal, Decimal, str]] = set()
        for y, x, orientation, length, width in candidates:
            key = (x, y, orientation)
            if key in seen:
                continue
            seen.add(key)
            placed.append((column, x, y, length, width, orientation))
            layout = recurse(index + 1)
            if layout is not None:
                return layout
            placed.pop()
        return None

    try:
        layout = recurse(0)
    except _NodeLimitReached:
        return _SearchOutcome(PackingStatus.INCONCLUSIVE, None, nodes)
    if layout is None:
        return _SearchOutcome(PackingStatus.PROVEN_NOT_FIT, None, nodes)
    return _SearchOutcome(PackingStatus.FIT, layout, nodes)


def _fast_standard_pallet_count_failure(
    columns: Sequence[_FloorColumn], profile: VehicleProfile
) -> bool:
    """Use the two-grid bound only for the published built-in pallet档案.

    The bound is not valid for arbitrary congruent rectangles: mixed 90-degree
    dominoes can exceed the best single-orientation grid.  Restricting this
    performance shortcut to the exact published standard-pallet dimensions
    and exact built-in vehicle dimensions preserves the 26/53 operational
    proof while leaving custom published profiles to the complete DFS.
    """

    expected = _BUILTIN_STANDARD_FLOOR_DIMENSIONS.get(profile.code)
    if expected is None or (profile.length_cm, profile.width_cm) != expected:
        return False
    if not columns:
        return False
    first = columns[0]
    if any(
        column.length_cm != first.length_cm
        or column.width_cm != first.width_cm
        or column.layers != 1
        for column in columns
    ):
        return False
    unit = first.units[0].unit
    if (
        unit.length_cm != Decimal("121.92")
        or unit.width_cm != Decimal("101.60")
        or not unit.floor_rotation_allowed
    ):
        return False
    long, short = max(first.length_cm, first.width_cm), min(first.length_cm, first.width_cm)
    grid_a = int(profile.length_cm // long) * int(profile.width_cm // short)
    grid_b = int(profile.length_cm // short) * int(profile.width_cm // long)
    return len(columns) > max(grid_a, grid_b)


def _greedy_layout(columns: Sequence[_FloorColumn], profile: VehicleProfile) -> _Layout | None:
    """Try stable bottom-left placements in both orientation preferences."""

    for prefer_rotated in (True, False):
        placed: list[tuple[_FloorColumn, Decimal, Decimal, Decimal, Decimal, str]] = []
        failed = False
        for column in columns:
            orientations = list(_column_orientations(column))
            if prefer_rotated:
                orientations.sort(key=lambda item: (item[2] != "rotated", item[2]))
            else:
                orientations.sort(key=lambda item: (item[2] != "original", item[2]))
            points = {(Decimal("0"), Decimal("0"))}
            for _, x, y, length, width, _ in placed:
                points.add((x + length, y))
                points.add((x, y + width))
            candidates: list[tuple[Decimal, Decimal, str, Decimal, Decimal]] = []
            for length, width, orientation in orientations:
                for x, y in points:
                    if x + length > profile.length_cm or y + width > profile.width_cm:
                        continue
                    if all(
                        not _overlap(x, y, length, width, ox, oy, ol, ow)
                        for _, ox, oy, ol, ow, _ in placed
                    ):
                        candidates.append((y, x, orientation, length, width))
            if not candidates:
                failed = True
                break
            if prefer_rotated:
                candidates.sort(key=lambda item: (item[0], item[1], item[2] != "rotated", item[2]))
            else:
                candidates.sort(key=lambda item: (item[0], item[1], item[2] != "original", item[2]))
            y, x, orientation, length, width = candidates[0]
            placed.append((column, x, y, length, width, orientation))
        if not failed:
            placements = tuple(
                {
                    "unit_index": column.units[0].unit_index,
                    "source_row_index": column.units[0].row_index,
                    "x_cm": x,
                    "y_cm": y,
                    "length_cm": length,
                    "width_cm": width,
                    "height_cm": column.height_cm,
                    "unit_quantity": len(column.units),
                    "layers": column.layers,
                    "orientation": orientation,
                }
                for column, x, y, length, width, orientation in placed
            )
            return _Layout(tuple(column for column, _, _, _, _, _ in placed), placements)
    return None


def _fast_exact_floor_failure(
    columns: Sequence[_FloorColumn], profile: VehicleProfile
) -> bool:
    """Prove a common exact-area case without exploring symmetric branches.

    Fifteen standard pallets on a 26-foot floor are a useful boundary case:
    their total area exactly equals the nominal floor area, so a DFS that
    explores every gap can consume the node budget even though no tiling is
    possible.  When every rectangle is congruent and the area is exact, any
    row-wise tiling must contain at least one full-width row pattern.  If no
    such pattern exists, this is a safe geometric proof for the homogeneous
    case; all other layouts continue through the bounded DFS below.
    """

    expected = _BUILTIN_STANDARD_FLOOR_DIMENSIONS.get(profile.code)
    if expected is None or (profile.length_cm, profile.width_cm) != expected:
        return False
    if not columns:
        return False
    floor_area = profile.length_cm * profile.width_cm
    rectangle_area = columns[0].length_cm * columns[0].width_cm
    if sum((item.length_cm * item.width_cm for item in columns), _ZERO) != floor_area:
        return False
    if any(
        item.length_cm != columns[0].length_cm
        or item.width_cm != columns[0].width_cm
        or item.units[0].unit.floor_rotation_allowed != columns[0].units[0].unit.floor_rotation_allowed
        for item in columns
    ):
        return False
    unit = columns[0].units[0].unit
    if unit.length_cm != Decimal("121.92") or unit.width_cm != Decimal("101.60"):
        return False
    orientations = _unit_orientations(unit)
    row_patterns: list[tuple[int, int]] = []
    # Enumerate bounded counts rather than relying on floating-point division;
    # Decimal arithmetic keeps the equality check exact for published cm data.
    for a in range(0, int(profile.width_cm // orientations[0][1]) + 1):
        for b in range(0, int(profile.width_cm // orientations[-1][1]) + 1):
            if a == 0 and b == 0:
                continue
            width = orientations[0][1] * a + orientations[-1][1] * b
            length = orientations[0][0] * a + orientations[-1][0] * b
            if width == profile.width_cm and length == profile.length_cm:
                row_patterns.append((a, b))
    # No full-floor row can be made from these rectangles.  For an exact-area
    # homogeneous tiling there is no room for a residual gap, so this proves
    # the candidate impossible without consuming the configured search bound.
    return not row_patterns


def _build_columns(
    physical: Sequence[_PhysicalUnit],
    profile: VehicleProfile,
    rule: OversizePalletRuleConfig,
) -> tuple[tuple[_FloorColumn, ...], tuple[str, ...]]:
    columns: list[_FloorColumn] = []
    reasons: list[str] = []
    # Grouping is intentionally restricted to one source row and identical
    # dimensions/weight, as required by the operating rule.
    by_row: dict[int, list[_PhysicalUnit]] = {}
    for item in physical:
        by_row.setdefault(item.row_index, []).append(item)
    for row_index in sorted(by_row):
        row_items = by_row[row_index]
        if not row_items:
            continue
        exemplar = row_items[0].unit
        for item in row_items:
            unit = item.unit
            if unit.height_cm > profile.height_cm:
                reasons.append("unit_dimensions_exceed_vehicle")
                continue
            if not _has_allowed_orientation(unit, profile):
                reasons.append("unit_dimensions_exceed_vehicle")
                continue
        if any(reason == "unit_dimensions_exceed_vehicle" for reason in reasons):
            continue
        stackable = (
            exemplar.stackability == "stackable"
            and exemplar.max_stack_layers is not None
            and exemplar.max_top_load_kg is not None
        )
        if not stackable:
            columns.extend(_single_columns(row_items))
            continue
        # Build as many maximal stacks as possible.  If a maximal stack would
        # exceed the vehicle height, reduce the layer count; if one layer is
        # the only legal option this naturally falls back to unstacked units.
        remaining = list(row_items)
        while remaining:
            bottom = remaining.pop(0)
            max_layers = min(exemplar.max_stack_layers or 1, 1 + len(remaining))
            layers = max_layers
            while layers > 1:
                stack_height = exemplar.height_cm * layers
                above_weight = exemplar.unit_weight_kg * (layers - 1)
                if (
                    stack_height <= profile.height_cm
                    and stack_height <= rule.high_board_height_cm
                    and exemplar.max_top_load_kg is not None
                    and above_weight <= exemplar.max_top_load_kg
                ):
                    break
                layers -= 1
            if layers > 1:
                stacked = tuple([bottom] + remaining[: layers - 1])
                del remaining[: layers - 1]
                columns.append(_make_column(stacked, "original"))
            else:
                columns.append(_make_column((bottom,), "original"))
    return tuple(columns), tuple(dict.fromkeys(reasons))


def _single_columns(items: Sequence[_PhysicalUnit]) -> list[_FloorColumn]:
    return [_make_column((item,), "original") for item in items]


def _make_column(items: tuple[_PhysicalUnit, ...], orientation: str) -> _FloorColumn:
    unit = items[0].unit
    return _FloorColumn(
        units=items,
        layers=len(items),
        length_cm=unit.length_cm,
        width_cm=unit.width_cm,
        height_cm=unit.height_cm * len(items),
        weight_kg=sum((item.unit.unit_weight_kg for item in items), _ZERO),
        volume_cbm=sum(
            (item.unit.length_cm * item.unit.width_cm * item.unit.height_cm / _MILLION for item in items),
            _ZERO,
        ),
        orientation=orientation,
    )


def _position_layout(layout: _Layout, profile: VehicleProfile) -> tuple[dict[str, object], ...]:
    """Return placement rows with actual selected orientation dimensions."""

    # ``_search_layout`` currently stores the selected dimensions directly in
    # placement rows; this hook keeps the output shaping in one place and makes
    # future split-vehicle offsets straightforward.
    return layout.placements


def _column_orientations(column: _FloorColumn) -> tuple[tuple[Decimal, Decimal, str], ...]:
    unit = column.units[0].unit
    options: list[tuple[Decimal, Decimal, str]] = [(unit.length_cm, unit.width_cm, "original")]
    if unit.floor_rotation_allowed and unit.length_cm != unit.width_cm:
        options.append((unit.width_cm, unit.length_cm, "rotated"))
    return tuple(options)


def _has_allowed_orientation(unit: HandlingUnitInput, profile: VehicleProfile) -> bool:
    return any(
        length <= profile.length_cm and width <= profile.width_cm
        for length, width, _ in _unit_orientations(unit)
    )


def _unit_orientations(unit: HandlingUnitInput) -> tuple[tuple[Decimal, Decimal, str], ...]:
    options: list[tuple[Decimal, Decimal, str]] = [(unit.length_cm, unit.width_cm, "original")]
    if unit.floor_rotation_allowed and unit.length_cm != unit.width_cm:
        options.append((unit.width_cm, unit.length_cm, "rotated"))
    return tuple(options)


def _expand_units(rows: Sequence[HandlingUnitInput]) -> tuple[_PhysicalUnit, ...]:
    result: list[_PhysicalUnit] = []
    ordinal = 0
    for row_index, unit in enumerate(rows):
        for _ in range(unit.quantity):
            result.append(_PhysicalUnit(row_index, ordinal, unit))
            ordinal += 1
    return tuple(result)


def _physical_to_units(items: Sequence[_PhysicalUnit]) -> list[HandlingUnitInput]:
    # A multi-vehicle bucket may contain only part of an original homogeneous
    # row.  Reassemble that part into one row so ``pack_vehicle`` can apply the
    # same source-row stacking rules as it does for a single vehicle.
    grouped: dict[int, list[_PhysicalUnit]] = {}
    for item in sorted(items, key=lambda item: (item.row_index, item.unit_index)):
        grouped.setdefault(item.row_index, []).append(item)
    return [
        group[0].unit.model_copy(update={"quantity": len(group)})
        for _row_index, group in sorted(grouped.items())
    ]


def _coerce_units(
    handling_units: Sequence[HandlingUnitInput | Mapping[str, object]],
) -> tuple[HandlingUnitInput, ...]:
    if isinstance(handling_units, (str, bytes)):
        raise ValueError("handling_unit_invalid")
    result: list[HandlingUnitInput] = []
    try:
        iterator = iter(handling_units)
    except TypeError:
        raise ValueError("handling_unit_invalid") from None
    for raw in iterator:
        if isinstance(raw, HandlingUnitInput):
            result.append(raw)
            continue
        if isinstance(raw, Mapping):
            try:
                result.append(HandlingUnitInput.model_validate(raw))
            except Exception:
                raise ValueError("handling_unit_invalid") from None
            continue
        raise ValueError("handling_unit_invalid")
    return tuple(result)


def _coerce_rule(
    rule: OversizePalletRuleConfig | Mapping[str, object] | None,
) -> OversizePalletRuleConfig:
    if rule is None:
        return default_oversize_pallet_rule()
    if isinstance(rule, OversizePalletRuleConfig):
        return rule
    return OversizePalletRuleConfig.model_validate(rule)


def _coerce_decimal(value: Decimal | int | float | str | None) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return decimal if decimal.is_finite() else None


def _adopted_total(
    handling_units: Sequence[HandlingUnitInput | Mapping[str, object]],
    explicit: Decimal | int | float | str | None,
    alias: Decimal | int | float | str | None,
    *,
    kind: str,
) -> Decimal:
    value = _coerce_decimal(explicit if explicit is not None else alias)
    if value is not None:
        return value
    units = _coerce_units(handling_units)
    if kind == "weight":
        return sum((unit.unit_weight_kg * unit.quantity for unit in units), _ZERO)
    return sum(
        (unit.length_cm * unit.width_cm * unit.height_cm * unit.quantity / _MILLION for unit in units),
        _ZERO,
    )


def _physical_sort_key(item: _PhysicalUnit) -> tuple[Decimal, Decimal, Decimal, int, int]:
    unit = item.unit
    area = unit.length_cm * unit.width_cm
    long = max(unit.length_cm, unit.width_cm)
    short = min(unit.length_cm, unit.width_cm)
    return (-area, -long, -short, item.row_index, item.unit_index)


def _column_sort_key(column: _FloorColumn) -> tuple[Decimal, Decimal, Decimal, int, int]:
    area = column.length_cm * column.width_cm
    long = max(column.length_cm, column.width_cm)
    short = min(column.length_cm, column.width_cm)
    first = column.units[0]
    return (-area, -long, -short, first.row_index, first.unit_index)


def _overlap(
    x1: Decimal,
    y1: Decimal,
    l1: Decimal,
    w1: Decimal,
    x2: Decimal,
    y2: Decimal,
    l2: Decimal,
    w2: Decimal,
) -> bool:
    return not (
        x1 + l1 <= x2
        or x2 + l2 <= x1
        or y1 + w1 <= y2
        or y2 + w2 <= y1
    )


def _result(
    status: PackingStatus,
    profile: VehicleProfile | str,
    *,
    vehicle_count: int,
    floor_columns: int,
    volume: Decimal,
    weight: Decimal,
    placements: Sequence[dict[str, object]],
    reasons: Sequence[str],
    tight_loading: bool = False,
) -> VehiclePackingResult:
    code = profile.code if isinstance(profile, VehicleProfile) else str(profile)
    return VehiclePackingResult(
        status=status,
        vehicle_code=code,
        vehicle_count=vehicle_count,
        floor_columns=floor_columns,
        volume_cbm=volume,
        payload_kg=weight,
        tight_loading=tight_loading,
        placements=tuple(placements),
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def _candidate_trace(result: VehiclePackingResult) -> dict[str, object]:
    return {
        "vehicle_code": result.vehicle_code,
        "vehicle_count": result.vehicle_count,
        "status": result.status.value,
        "floor_columns": result.floor_columns,
        "volume_cbm": result.volume_cbm,
        "payload_kg": result.payload_kg,
        "tight_loading": result.tight_loading,
        "reason_codes": result.reason_codes,
    }


def _with_checked(
    result: VehiclePackingResult,
    checked: Sequence[dict[str, object]],
) -> VehiclePackingResult:
    return VehiclePackingResult(
        status=result.status,
        vehicle_code=result.vehicle_code,
        vehicle_count=result.vehicle_count,
        floor_columns=result.floor_columns,
        volume_cbm=result.volume_cbm,
        payload_kg=result.payload_kg,
        tight_loading=result.tight_loading,
        placements=result.placements,
        reason_codes=result.reason_codes,
        vehicle_profiles_checked=tuple(checked),
    )


def _vehicle_tie_key(
    result: VehiclePackingResult,
    profiles: Sequence[VehicleProfile],
    *,
    price_context: Sequence[VehicleProfile] | None = None,
) -> tuple[object, ...]:
    profile = next((item for item in profiles if item.code == result.vehicle_code), None)
    if profile is None:
        return (1, Decimal("Infinity"), Decimal("Infinity"), result.vehicle_code)
    price_profiles = profiles if price_context is None else price_context
    all_prices = all(item.comparable_base_price is not None for item in price_profiles)
    if all_prices:
        return (
            result.vehicle_count,
            profile.comparable_base_price,
            profile.volume_cbm,
            profile.payload_kg,
            profile.code,
        )
    # Missing prices are not a zero-dollar offer.  Skip the price layer
    # entirely and continue with the published capacity/code tie-breaks.
    return (
        result.vehicle_count,
        profile.volume_cbm,
        profile.payload_kg,
        profile.code,
    )


def _multi_vehicle_tie_key(
    result: VehiclePackingResult,
    profiles: Sequence[VehicleProfile],
    *,
    price_context: Sequence[VehiclePackingResult] | None = None,
) -> tuple[object, ...]:
    codes = tuple(sorted(result.vehicle_code.split("+")))
    profile_by_code = {profile.code: profile for profile in profiles}
    selected = [profile_by_code[code] for code in codes if code in profile_by_code]
    context_codes = (
        tuple(
            dict.fromkeys(
                code
                for candidate in price_context
                for code in candidate.vehicle_code.split("+")
            )
        )
        if price_context is not None
        else tuple(profile.code for profile in profiles)
    )
    context_profiles = [
        profile_by_code[code] for code in context_codes if code in profile_by_code
    ]
    all_prices = all(profile.comparable_base_price is not None for profile in context_profiles)
    if all_prices:
        return (
            result.vehicle_count,
            sum((profile.comparable_base_price for profile in selected), _ZERO),
            sum((profile.volume_cbm for profile in selected), _ZERO),
            sum((profile.payload_kg for profile in selected), _ZERO),
            codes,
        )
    return (
        result.vehicle_count,
        sum((profile.volume_cbm for profile in selected), _ZERO),
        sum((profile.payload_kg for profile in selected), _ZERO),
        codes,
    )


def _empty_profile_code(profiles: Sequence[VehicleProfile]) -> str:
    return profiles[0].code if profiles else ""


__all__ = ["PackingStatus", "VehiclePackingResult", "pack_vehicle", "select_vehicle"]
