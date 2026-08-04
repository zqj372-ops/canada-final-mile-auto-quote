import importlib


def test_0023_customers_is_linear_after_quote_workflow() -> None:
    migration = importlib.import_module("migrations.versions.0023_customers")
    assert migration.revision == "0023_customers"
    assert migration.down_revision == "0022_quote_workflow"
