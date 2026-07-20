from packages.address_normalizer import extract_fsa, is_rural_fsa, normalize_postal_code, normalize_province


def test_normalizes_postal_code_and_extracts_fsa() -> None:
    assert normalize_postal_code("v6v1a1") == "V6V 1A1"
    assert extract_fsa("v6v1a1") == "V6V"
    assert extract_fsa("L5T 2X3") == "L5T"


def test_normalizes_province_aliases() -> None:
    assert normalize_province("Ontario") == "ON"
    assert normalize_province("British Columbia") == "BC"
    assert normalize_province("PEI") == "PE"


def test_identifies_rural_fsa_by_zero_in_second_position() -> None:
    assert is_rural_fsa("N0A 1M0") is True
    assert is_rural_fsa("G0S") is True
    assert is_rural_fsa("V3J 0A7") is False
    assert is_rural_fsa("invalid") is False
