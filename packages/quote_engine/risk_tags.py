from packages.address_normalizer import is_rural_fsa


RURAL_FSA_SECONDARY_CONFIRMATION_TAG = "rural_fsa_secondary_confirmation"


def rural_fsa_risk_tags(postal_code: str | None) -> list[str]:
    if is_rural_fsa(postal_code):
        return [RURAL_FSA_SECONDARY_CONFIRMATION_TAG]
    return []
