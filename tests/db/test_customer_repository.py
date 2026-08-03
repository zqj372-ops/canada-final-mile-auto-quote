from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.auth import CurrentActor
from apps.api.db.models import Base, SalesQuoteRecord
from apps.api.db.repositories.customer_repository import CustomerRepository


def test_customer_repository_normalizes_names_and_scopes_sales_visibility() -> None:
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    alice = CurrentActor(user_id=1, api_key_id=None, name="Alice", role="sales")
    bob = CurrentActor(user_id=2, api_key_id=None, name="Bob", role="sales")

    with session_factory() as session:
        repository = CustomerRepository(session)
        first = repository.create(actor=alice, name="  Acme  Trading ")
        duplicate = repository.create(actor=bob, name="ＡＣＭＥ   trading")
        session.add(SalesQuoteRecord(customer_id=duplicate.id, actor_user_id=2, actor_name="Bob", actor_role="sales", status="quoted", workflow_status="ready_to_send", quote_id="q-bob", customer_message="", request_json={}, result_json={}))
        session.commit()

        assert first.name == "Acme Trading"
        assert first.normalized_name == "acme trading"
        assert repository.list(actor=alice).records == [first]
        assert repository.list(actor=bob).records == [duplicate]
        assert repository.create(actor=alice, name="ACME Trading").possible_duplicate is True
