from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import Base, QuoteAuditLog, SalesQuoteRecord
from apps.api.services.audit_service import get_quote_error_summary, list_quote_audits


def test_audit_dicts_include_latest_requester_from_sales_record() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with SessionLocal() as session:
        session.add(
            QuoteAuditLog(
                quote_id="quote-requester",
                request_json={"postal_code": "T5T 4B2"},
                result_json={"source_type": "manual_required"},
                source_type="manual_required",
                postal_code="T5T 4B2",
                postal_prefix="T5T",
                city="Edmonton",
                province="AB",
                origin="calgary",
                zone=9,
                billing_pallets=1,
                base_price_usd=None,
                total_price_usd=Decimal("0.00"),
                manual_review_required=True,
                risk_tags=["zone_price_disabled"],
            )
        )
        session.add(
            SalesQuoteRecord(
                quote_id="quote-requester",
                actor_user_id=7,
                actor_api_key_id=None,
                actor_name="Alice Sales",
                actor_role="sales",
                status="manual_required",
                customer_message="20627 93Ave NW, Edmonton, AB, T5T 4B2",
                customer_reply=None,
                request_json={},
                result_json={},
            )
        )
        session.commit()

        audit = list_quote_audits(session, limit=1)[0]
        summary = get_quote_error_summary(session, limit=1)

    assert audit["actor_user_id"] == 7
    assert audit["actor_name"] == "Alice Sales"
    assert audit["actor_role"] == "sales"
    assert summary["recent_audits"][0]["actor_name"] == "Alice Sales"
