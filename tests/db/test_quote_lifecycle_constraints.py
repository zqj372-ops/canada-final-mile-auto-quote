from apps.api.db.models import SalesQuoteRecord


def test_sales_quote_customer_link_is_nullable_and_restricts_delete() -> None:
    column = SalesQuoteRecord.__table__.c.customer_id
    assert column.nullable is True
    assert column.foreign_keys
    assert next(iter(column.foreign_keys)).ondelete == "RESTRICT"
