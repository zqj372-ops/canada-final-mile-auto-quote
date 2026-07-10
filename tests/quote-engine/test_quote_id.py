from packages.quote_engine.quote_id import generate_quote_id


def test_quote_ids_are_sortable_numeric_and_unique() -> None:
    values = {generate_quote_id() for _ in range(1000)}

    assert len(values) == 1000
    assert all(value.isdigit() and len(value) == 31 for value in values)
