from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DimensionUnit = Literal["mm", "cm", "m", "in"]
WeightUnit = Literal["g", "kg", "lb"]

_DIMENSION_TO_METRES = {
    "mm": Decimal("0.001"),
    "cm": Decimal("0.01"),
    "m": Decimal("1"),
    "in": Decimal("0.0254"),
}
_WEIGHT_TO_KG = {
    "g": Decimal("0.001"),
    "kg": Decimal("1"),
    "lb": Decimal("0.45359237"),
}


class CargoMetricItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    quantity: int = Field(gt=0)
    length: Decimal = Field(gt=0)
    width: Decimal = Field(gt=0)
    height: Decimal = Field(gt=0)
    dimension_unit: DimensionUnit = "cm"
    unit_weight: Decimal | None = Field(default=None, gt=0)
    piece_weights: list[Decimal] = Field(default_factory=list)
    line_total_weight: Decimal | None = Field(default=None, gt=0)
    weight_unit: WeightUnit = "kg"

    @model_validator(mode="after")
    def validate_weight_evidence(self) -> "CargoMetricItem":
        if not self.unit_weight and not self.piece_weights and not self.line_total_weight:
            raise ValueError("at least one weight evidence field is required")
        if self.piece_weights and len(self.piece_weights) != self.quantity:
            raise ValueError("piece_weights length must equal quantity")
        if any(weight <= 0 for weight in self.piece_weights):
            raise ValueError("piece_weights must be positive")
        return self


class CargoMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[dict[str, str | int | list[str]]]
    total_piece_count: int
    total_volume_cbm: Decimal
    total_weight_kg: Decimal
    billing_density_kg_per_cbm: Decimal | None
    max_single_weight_kg: Decimal | None
    declared_total_volume_cbm: Decimal | None
    declared_total_weight_kg: Decimal | None
    blocking_conflicts: list[str]
    formula_version: Literal["cargo-metrics-v1"] = "cargo-metrics-v1"


def _quantize(value: Decimal, places: str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def calculate_cargo_metrics(
    items: list[CargoMetricItem],
    *,
    declared_total_weight_kg: Decimal | None = None,
    declared_total_volume_cbm: Decimal | None = None,
) -> CargoMetrics:
    total_volume = Decimal("0")
    total_weight = Decimal("0")
    max_single: Decimal | None = None
    conflicts: list[str] = []
    normalized_items: list[dict[str, str | int | list[str]]] = []

    for item in items:
        dimension_factor = _DIMENSION_TO_METRES[item.dimension_unit]
        line_volume = (
            item.length * dimension_factor
            * item.width * dimension_factor
            * item.height * dimension_factor
            * item.quantity
        )
        weight_factor = _WEIGHT_TO_KG[item.weight_unit]
        evidence: dict[str, Decimal] = {}
        if item.unit_weight is not None:
            evidence["unit_weight"] = item.unit_weight * weight_factor * item.quantity
        if item.piece_weights:
            evidence["piece_weights"] = sum(item.piece_weights, Decimal("0")) * weight_factor
        if item.line_total_weight is not None:
            evidence["line_total_weight"] = item.line_total_weight * weight_factor

        values = list(evidence.values())
        if any(value != values[0] for value in values[1:]):
            conflicts.append("line_weight_evidence_conflict")
        line_weight = values[0]
        total_volume += line_volume
        total_weight += line_weight

        if item.piece_weights:
            item_max = max(item.piece_weights) * weight_factor
        elif item.unit_weight is not None:
            item_max = item.unit_weight * weight_factor
        elif item.quantity == 1:
            item_max = line_weight
        else:
            item_max = None
            conflicts.append("max_single_weight_unknown")
        if item_max is not None:
            max_single = item_max if max_single is None else max(max_single, item_max)
        normalized_items.append(
            {
                "quantity": item.quantity,
                "volume_cbm": str(_quantize(line_volume, "0.001")),
                "weight_mode": "piece_weights" if item.piece_weights else "unit_weight" if item.unit_weight is not None else "line_total_weight",
                "weight_evidence": list(evidence),
            }
        )

    if not items:
        conflicts.append("cargo_items_incomplete")
    if declared_total_weight_kg is not None and declared_total_weight_kg != total_weight:
        conflicts.append("declared_total_weight_conflict")
    if declared_total_volume_cbm is not None and declared_total_volume_cbm != total_volume:
        conflicts.append("declared_total_volume_conflict")

    public_volume = _quantize(total_volume, "0.001")
    public_weight = _quantize(total_weight, "0.01")
    density = _quantize(total_weight / total_volume, "0.01") if total_volume else None
    return CargoMetrics(
        items=normalized_items,
        total_piece_count=sum(item.quantity for item in items),
        total_volume_cbm=public_volume,
        total_weight_kg=public_weight,
        billing_density_kg_per_cbm=density,
        max_single_weight_kg=_quantize(max_single, "0.01") if max_single is not None else None,
        declared_total_volume_cbm=_quantize(declared_total_volume_cbm, "0.001") if declared_total_volume_cbm is not None else None,
        declared_total_weight_kg=_quantize(declared_total_weight_kg, "0.01") if declared_total_weight_kg is not None else None,
        blocking_conflicts=sorted(set(conflicts)),
    )
