from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.auth import ADMIN_ROLES, require_roles
from apps.api.db.models import SearchApiConfig as SearchApiConfigRecord
from apps.api.db.repositories.search_api_config_repository import SearchApiConfigRepository
from apps.api.db.session import get_db
from packages.search.tavily_client import TavilySearchClient, TavilySearchConfig


router = APIRouter(
    prefix="/search-configs",
    tags=["search-configs"],
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)


class SearchApiConfigCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    provider: str = Field(default="tavily")
    base_url: str | None = None
    api_key: str = Field(min_length=1)
    purpose: str = Field(default="general")
    enabled: bool = True
    is_default: bool = False


class SearchApiConfigUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    purpose: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None


@router.get("")
def list_search_configs(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    repository = SearchApiConfigRepository(db)
    return [repository.to_public_dict(record) for record in repository.list_configs()]


@router.post("", status_code=201)
def create_search_config(payload: SearchApiConfigCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = SearchApiConfigRepository(db)
    try:
        record = repository.create_config(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return repository.to_public_dict(record)


@router.patch("/{config_id}")
def update_search_config(
    config_id: int,
    payload: SearchApiConfigUpdate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    repository = SearchApiConfigRepository(db)
    try:
        record = repository.update_config(config_id, **payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Search API config not found.")
    return repository.to_public_dict(record)


@router.delete("/{config_id}")
def delete_search_config(config_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    repository = SearchApiConfigRepository(db)
    if not repository.delete_config(config_id):
        raise HTTPException(status_code=404, detail="Search API config not found.")
    return {"deleted": True}


@router.post("/{config_id}/set-default")
def set_default_search_config(config_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = SearchApiConfigRepository(db)
    record = repository.set_default_config(config_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Search API config not found.")
    return repository.to_public_dict(record)


@router.post("/{config_id}/test")
def test_search_config(config_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = SearchApiConfigRepository(db)
    record = _get_record_or_404(repository, config_id)
    if record.provider != "tavily":
        raise HTTPException(status_code=400, detail="Only tavily search test is supported.")

    started = perf_counter()
    response = TavilySearchClient(
        TavilySearchConfig(
            api_key=repository.decrypt_api_key(record),
            base_url=record.base_url or "https://api.tavily.com",
        )
    ).search("Canada final mile delivery address verification", max_results=1)
    latency_ms = response.latency_ms or int((perf_counter() - started) * 1000)
    return {
        "success": response.error is None,
        "error": response.error,
        "latency_ms": latency_ms,
        "result_count": len(response.results),
        "preview": response.results[0].title[:120] if response.results else None,
    }


def _get_record_or_404(repository: SearchApiConfigRepository, config_id: int) -> SearchApiConfigRecord:
    record = repository.get_config(config_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Search API config not found.")
    return record
