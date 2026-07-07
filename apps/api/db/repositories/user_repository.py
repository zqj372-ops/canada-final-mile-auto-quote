from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import User
from apps.api.security.passwords import hash_password, verify_password


ALLOWED_USER_ROLES = {"admin", "operator", "sales", "viewer"}


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_user(
        self,
        *,
        username: str,
        password: str,
        display_name: str | None = None,
        role: str = "sales",
        enabled: bool = True,
    ) -> User:
        if role not in ALLOWED_USER_ROLES:
            raise ValueError(f"Unsupported user role: {role}")
        record = User(
            username=username.strip().lower(),
            display_name=(display_name or username).strip(),
            password_hash=hash_password(password),
            role=role,
            enabled=enabled,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_users(self) -> list[User]:
        return list(self.session.scalars(select(User).order_by(User.created_at.desc(), User.id.desc())))

    def get_user(self, user_id: int) -> User | None:
        return self.session.get(User, user_id)

    def get_by_username(self, username: str) -> User | None:
        return self.session.scalars(select(User).where(User.username == username.strip().lower())).first()

    def authenticate(self, username: str, password: str) -> User | None:
        record = self.get_by_username(username)
        if record is None or not record.enabled:
            return None
        if not verify_password(password, record.password_hash):
            return None
        record.last_login_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(record)
        return record

    def update_user(
        self,
        user_id: int,
        *,
        display_name: str | None = None,
        role: str | None = None,
        enabled: bool | None = None,
        password: str | None = None,
    ) -> User | None:
        record = self.get_user(user_id)
        if record is None:
            return None
        if role is not None:
            if role not in ALLOWED_USER_ROLES:
                raise ValueError(f"Unsupported user role: {role}")
            record.role = role
        if display_name is not None:
            record.display_name = display_name
        if enabled is not None:
            record.enabled = enabled
        if password is not None:
            record.password_hash = hash_password(password)
        self.session.commit()
        self.session.refresh(record)
        return record

    def to_public_dict(self, record: User) -> dict[str, object]:
        return {
            "id": record.id,
            "username": record.username,
            "display_name": record.display_name,
            "role": record.role,
            "enabled": record.enabled,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            "last_login_at": record.last_login_at.isoformat() if record.last_login_at else None,
        }
