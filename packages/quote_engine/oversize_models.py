"""Domain models for North-American oversize handling units.

The quote workflow deliberately keeps customer-piece counts separate from
handling-unit quantities.  A handling unit is the smallest physical unit the
carrier will move (for example, one pallet, crate, or bare piece); customer
piece counts are retained only for reconciliation and audit.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class HandlingUnitInput(BaseModel):
    """One homogeneous group of physical handling units.

    ``quantity`` is always the number of handling units.  It is intentionally
    not inferred from ``contained_customer_pieces`` (which is an optional
    order-data reconciliation value).
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        validate_assignment=True,
    )

    quantity: int = Field(
        ge=1,
        validation_alias=AliasChoices("quantity", "handling_unit_quantity"),
    )
    packaging_type: str = Field(
        min_length=1,
        validation_alias=AliasChoices("packaging_type", "packaging"),
    )
    length_cm: Decimal = Field(
        gt=0,
        validation_alias=AliasChoices("length_cm", "length"),
    )
    width_cm: Decimal = Field(
        gt=0,
        validation_alias=AliasChoices("width_cm", "width"),
    )
    height_cm: Decimal = Field(
        gt=0,
        validation_alias=AliasChoices("height_cm", "height"),
    )
    unit_weight_kg: Decimal = Field(
        gt=0,
        validation_alias=AliasChoices(
            "unit_weight_kg",
            "unit_gross_weight",
            "unit_gross_weight_kg",
            "gross_weight_kg",
        ),
    )
    cbm: Decimal | None = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("cbm", "unit_cbm"),
    )
    contained_customer_pieces: int | None = Field(default=None, ge=0)
    stackability: Literal["stackable", "non_stackable", "unknown"] = "unknown"
    max_stack_layers: int | None = Field(default=None, ge=2)
    max_top_load_kg: Decimal | None = Field(default=None, gt=0)
    floor_rotation_allowed: bool = Field(
        default=True,
        validation_alias=AliasChoices("floor_rotation_allowed", "rotation_allowed"),
    )
    source_span: str | None = None

    @model_validator(mode="after")
    def validate_stackability(self) -> "HandlingUnitInput":
        """Require explicit stack constraints when stacking is asserted."""

        if self.stackability == "stackable" and (
            self.max_stack_layers is None or self.max_top_load_kg is None
        ):
            raise ValueError(
                "stackable handling units require max_stack_layers and max_top_load_kg"
            )
        return self

    # Spec-language aliases are properties rather than duplicate stored fields,
    # keeping one stable payload shape while allowing calculator callers to use
    # ``handling_unit_quantity``/``unit_gross_weight_kg`` wording.
    @property
    def handling_unit_quantity(self) -> int:
        return self.quantity

    @property
    def unit_gross_weight_kg(self) -> Decimal:
        return self.unit_weight_kg


__all__ = ["HandlingUnitInput"]
