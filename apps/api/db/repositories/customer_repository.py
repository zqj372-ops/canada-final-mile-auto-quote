from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from apps.api.auth import CurrentActor
from apps.api.db.models import Customer, SalesQuoteRecord


def normalize_customer_name(name: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", name).strip()).casefold()


@dataclass(frozen=True)
class CustomerListResult:
    records: list[Customer]
    total: int
    limit: int
    offset: int


class CustomerRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, *, actor: CurrentActor, name: str) -> Customer:
        cleaned = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", name).strip())
        if not cleaned:
            raise ValueError("Customer name is required")
        duplicate = self.session.scalar(select(func.count(Customer.id)).where(Customer.normalized_name == normalize_customer_name(cleaned))) > 0
        record = Customer(name=cleaned, normalized_name=normalize_customer_name(cleaned), created_by_user_id=actor.user_id)
        self.session.add(record)
        self.session.flush()
        setattr(record, "possible_duplicate", duplicate)
        return record

    def list(self, *, actor: CurrentActor, query: str | None = None, limit: int = 50, offset: int = 0) -> CustomerListResult:
        statement = select(Customer)
        if actor.role == "sales":
            owned_quote = exists(select(SalesQuoteRecord.id).where(SalesQuoteRecord.customer_id == Customer.id, SalesQuoteRecord.actor_user_id == actor.user_id))
            statement = statement.where(or_(Customer.created_by_user_id == actor.user_id, owned_quote))
        if query and query.strip():
            statement = statement.where(Customer.normalized_name.contains(normalize_customer_name(query)))
        total = self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        records = list(self.session.scalars(statement.order_by(Customer.name, Customer.id).offset(max(offset, 0)).limit(max(1, min(limit, 100)))))
        return CustomerListResult(records=records, total=total, limit=max(1, min(limit, 100)), offset=max(offset, 0))

