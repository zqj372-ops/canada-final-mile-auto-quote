from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.auth import ALL_ROLES, QUOTE_WRITE_ROLES, CurrentActor, require_roles
from apps.api.db.models import Customer
from apps.api.db.repositories.customer_repository import CustomerRepository
from apps.api.db.session import get_db
from apps.api.schemas.customers import CustomerCreate, CustomerUpdate

router = APIRouter(prefix="/customers", tags=["customers"])


def _to_dict(customer, *, possible_duplicate: bool = False) -> dict[str, object]:
    return {"id": customer.id, "name": customer.name, "possible_duplicate": possible_duplicate, "created_at": customer.created_at.isoformat() if customer.created_at else None, "updated_at": customer.updated_at.isoformat() if customer.updated_at else None}


@router.get("")
def list_customers(query: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db), actor: CurrentActor = Depends(require_roles(*ALL_ROLES))) -> dict[str, object]:
    result = CustomerRepository(db).list(actor=actor, query=query, limit=limit, offset=offset)
    return {"records": [_to_dict(customer) for customer in result.records], "total": result.total, "limit": result.limit, "offset": result.offset}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db), actor: CurrentActor = Depends(require_roles(*QUOTE_WRITE_ROLES))) -> dict[str, object]:
    try:
        customer = CustomerRepository(db).create(actor=actor, name=payload.name)
        db.commit()
        return _to_dict(customer, possible_duplicate=bool(getattr(customer, "possible_duplicate", False)))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{customer_id}")
def update_customer(customer_id: int, payload: CustomerUpdate, db: Session = Depends(get_db), actor: CurrentActor = Depends(require_roles(*QUOTE_WRITE_ROLES))) -> dict[str, object]:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    if actor.role == "sales" and customer.created_by_user_id not in {actor.user_id, None}:
        raise HTTPException(status_code=403, detail="Sales users may only edit their own customers.")
    from apps.api.db.repositories.customer_repository import normalize_customer_name
    customer.name = payload.name
    customer.normalized_name = normalize_customer_name(payload.name)
    db.commit()
    return _to_dict(customer)
