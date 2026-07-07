from dataclasses import dataclass
from decimal import Decimal
from math import ceil


FLEXIBLE_PACKAGING = {"编织袋", "柔性包装", "woven bag", "flexible packaging", "bag"}
WOODEN_CRATE = {"木箱", "crate", "wooden crate"}
HARD_LONG_PIECE_THRESHOLD_CM = Decimal("240")


@dataclass(frozen=True)
class PalletCalculationResult:
    billing_pallets: int | None
    components: dict[str, int]
    manual_review_required: bool = False
    risk_tags: tuple[str, ...] = ()
    internal_note: str | None = None


def calculate_billing_pallets(
    *,
    cbm: Decimal,
    weight_kg: Decimal,
    piece_count: int,
    packaging_type: str,
    longest_side_cm: Decimal | None = None,
    explicit_pallet_count: int | None = None,
    is_stackable: bool | None = None,
) -> PalletCalculationResult:
    packaging = packaging_type.strip().lower()
    if packaging in FLEXIBLE_PACKAGING and piece_count >= 50 and is_stackable:
        return PalletCalculationResult(
            billing_pallets=None,
            components={},
            manual_review_required=True,
            risk_tags=("flat_rate_packaging_required",),
            internal_note="Flexible packaging flat-rate mode needs configured package pricing.",
        )

    volume_pallets = max(1, ceil(cbm / Decimal("2"))) if cbm > 0 else 0
    weight_pallets = max(1, ceil(weight_kg / Decimal("500"))) if weight_kg > 0 else 0
    is_long_piece = bool(
        longest_side_cm is not None and longest_side_cm >= HARD_LONG_PIECE_THRESHOLD_CM
    )
    long_piece_pallets = piece_count * 2 if is_long_piece else 0

    wooden_crate_pallets = 0
    if packaging in WOODEN_CRATE:
        wooden_crate_pallets = piece_count * 2 if is_long_piece else piece_count

    explicit = explicit_pallet_count or 0
    components = {
        "volume_pallets": volume_pallets,
        "weight_pallets": weight_pallets,
        "long_piece_pallets": long_piece_pallets,
        "wooden_crate_pallets": wooden_crate_pallets,
        "explicit_pallet_count": explicit,
    }
    billing_pallets = max(components.values())
    if billing_pallets <= 0:
        return PalletCalculationResult(
            billing_pallets=None,
            components=components,
            manual_review_required=True,
            risk_tags=("missing_billable_pallet_basis",),
            internal_note="CBM, weight, or explicit pallet count is required to calculate billing pallets.",
        )

    return PalletCalculationResult(billing_pallets=billing_pallets, components=components)
