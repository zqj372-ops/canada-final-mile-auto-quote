from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import APIKey
from apps.api.security.api_keys import generate_api_key, hash_api_key, mask_api_key


ALLOWED_API_KEY_ROLES = {"admin", "operator", "sales", "viewer"}


class APIKeyRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_key(
        self,
        *,
        name: str,
        role: str,
        enabled: bool = True,
    ) -> tuple[APIKey, str]:
        if role not in ALLOWED_API_KEY_ROLES:
            raise ValueError(f"Unsupported API key role: {role}")
        plain_key = generate_api_key()
        record = APIKey(
            name=name,
            key_hash=hash_api_key(plain_key),
            role=role,
            enabled=enabled,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record, plain_key

    def list_keys(self) -> list[APIKey]:
        return list(self.session.scalars(select(APIKey).order_by(APIKey.created_at.desc(), APIKey.id.desc())))

    def get_key(self, key_id: int) -> APIKey | None:
        return self.session.get(APIKey, key_id)

    def update_key(
        self,
        key_id: int,
        *,
        name: str | None = None,
        role: str | None = None,
        enabled: bool | None = None,
    ) -> APIKey | None:
        record = self.get_key(key_id)
        if record is None:
            return None
        if role is not None and role not in ALLOWED_API_KEY_ROLES:
            raise ValueError(f"Unsupported API key role: {role}")
        if name is not None:
            record.name = name
        if role is not None:
            record.role = role
        if enabled is not None:
            record.enabled = enabled
        self.session.commit()
        self.session.refresh(record)
        return record

    def authenticate(self, api_key: str) -> APIKey | None:
        record = self.session.scalars(
            select(APIKey).where(APIKey.key_hash == hash_api_key(api_key), APIKey.enabled.is_(True))
        ).first()
        if record is None:
            return None
        record.last_used_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(record)
        return record

    def to_public_dict(self, record: APIKey, *, plain_key: str | None = None) -> dict[str, object]:
        body: dict[str, object] = {
            "id": record.id,
            "name": record.name,
            "masked_api_key": mask_api_key(plain_key),
            "role": record.role,
            "enabled": record.enabled,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            "last_used_at": record.last_used_at.isoformat() if record.last_used_at else None,
        }
        if plain_key is not None:
            body["api_key"] = plain_key
        return body
