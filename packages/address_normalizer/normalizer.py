from dataclasses import dataclass
import re


POSTAL_RE = re.compile(r"^[A-Z]\d[A-Z]\d[A-Z]\d$")

PROVINCE_ALIASES = {
    "AB": "AB",
    "ALBERTA": "AB",
    "BC": "BC",
    "B.C.": "BC",
    "BRITISH COLUMBIA": "BC",
    "MB": "MB",
    "MANITOBA": "MB",
    "NB": "NB",
    "NEW BRUNSWICK": "NB",
    "NL": "NL",
    "NEWFOUNDLAND": "NL",
    "NEWFOUNDLAND AND LABRADOR": "NL",
    "NS": "NS",
    "NOVA SCOTIA": "NS",
    "NT": "NT",
    "NORTHWEST TERRITORIES": "NT",
    "NU": "NU",
    "NUNAVUT": "NU",
    "ON": "ON",
    "ONTARIO": "ON",
    "PE": "PE",
    "PEI": "PE",
    "PRINCE EDWARD ISLAND": "PE",
    "QC": "QC",
    "QUEBEC": "QC",
    "QUEBEC PROVINCE": "QC",
    "SK": "SK",
    "SASKATCHEWAN": "SK",
    "YT": "YT",
    "YUKON": "YT",
}


@dataclass(frozen=True)
class NormalizedAddress:
    address_line: str | None
    postal_code: str | None
    fsa: str | None
    city: str | None
    province: str | None


def clean_address(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value.strip())
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r",\s*", ", ", cleaned)
    return cleaned or None


def normalize_postal_code(value: str | None) -> str | None:
    if not value:
        return None

    compact = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    if not POSTAL_RE.match(compact):
        return None
    return f"{compact[:3]} {compact[3:]}"


def normalize_city(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value.strip())
    return cleaned.title() if cleaned else None


def normalize_province(value: str | None) -> str | None:
    if not value:
        return None
    key = re.sub(r"\s+", " ", value.strip()).upper()
    return PROVINCE_ALIASES.get(key)


def normalize_address(
    address_line: str | None = None,
    postal_code: str | None = None,
    city: str | None = None,
    province: str | None = None,
) -> NormalizedAddress:
    normalized_postal = normalize_postal_code(postal_code)
    return NormalizedAddress(
        address_line=clean_address(address_line),
        postal_code=normalized_postal,
        fsa=normalized_postal[:3] if normalized_postal else None,
        city=normalize_city(city),
        province=normalize_province(province),
    )

