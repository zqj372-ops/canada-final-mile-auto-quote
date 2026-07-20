from packages.quote_engine.quote_id import generate_quote_id


def test_quote_ids_are_compact_sortable_and_unique() -> None:
    values = [generate_quote_id() for _ in range(10_000)]

    assert len(set(values)) == len(values)
    assert values == sorted(values)
    assert all(len(value) == 15 for value in values)
    assert all(set(value) <= set("0123456789ABCDEFGHJKMNPQRSTVWXYZ") for value in values)
