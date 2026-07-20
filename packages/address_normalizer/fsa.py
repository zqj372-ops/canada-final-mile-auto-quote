import re

from packages.address_normalizer.normalizer import normalize_postal_code


FSA_RE = re.compile(r"^[A-Z]\d[A-Z]$")


def extract_fsa(value: str | None) -> str | None:
    if not value:
        return None

    normalized = normalize_postal_code(value)
    if normalized:
        return normalized[:3]

    compact = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    if FSA_RE.match(compact):
        return compact
    return None


def is_valid_fsa(value: str | None) -> bool:
    return bool(value and FSA_RE.match(value.upper()))


def is_rural_fsa(value: str | None) -> bool:
    """Return whether a Canadian postal code/FSA identifies a rural area."""
    fsa = extract_fsa(value)
    return bool(fsa and fsa[1] == "0")
