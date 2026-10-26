from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.auth import CurrentActor, require_roles
from apps.api.db.models import QuoteSkillGrant, SalesQuoteRecord, User
from apps.api.db.session import get_db
from apps.api.services.quote_skill_service import (
    CODE_TTL_SECONDS, authenticate_grant, bind_grant, create_grant,
    public_grant, public_record, quote_for_skill,
)


def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/quote-skill", tags=["quote-skill"], dependencies=[Depends(no_store)])


class AuthorizeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(default="我的 AI 助手", min_length=1, max_length=128)
    username: str | None = Field(default=None, min_length=1, max_length=128)


class BindRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    code: str = Field(min_length=1, max_length=128)


class QuoteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    message: str = Field(min_length=1, max_length=12000)


def target_user(db, actor, username):
    if username is not None:
        if actor.role != "admin":
            raise HTTPException(403, "只有管理员可以为其他账号签发或管理授权。")
        user = db.scalar(select(User).where(User.username == username.strip().lower()))
    else:
        user = db.get(User, actor.user_id) if actor.user_id is not None else None
    if user is None:
        raise HTTPException(404, "请指定已有的报价账号，或使用个人账号登录。")
    return user


def skill_identity(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    scheme, _, credential = (authorization or "").partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(401, "请先使用授权码绑定 Skill。")
    return authenticate_grant(db, credential)


@router.post("/authorizations", status_code=201)
def issue_authorization(payload: AuthorizeRequest, db: Session = Depends(get_db),
                        actor: CurrentActor = Depends(require_roles("admin", "sales"))):
    user = target_user(db, actor, payload.username)
    grant, code = create_grant(db, user, payload.name)
    return {**public_grant(grant), "username": user.username, "authorization_code": code,
            "expires_in_seconds": CODE_TTL_SECONDS}


@router.get("/authorizations")
def list_authorizations(username: str | None = Query(default=None, max_length=128),
                        db: Session = Depends(get_db),
                        actor: CurrentActor = Depends(require_roles("admin", "sales"))):
    user = target_user(db, actor, username)
    return [public_grant(g) for g in db.scalars(select(QuoteSkillGrant).where(
        QuoteSkillGrant.user_id == user.id).order_by(QuoteSkillGrant.id.desc()))]


@router.delete("/authorizations/{grant_id}", status_code=204)
def revoke_authorization(grant_id: int, db: Session = Depends(get_db),
                         actor: CurrentActor = Depends(require_roles("admin", "sales"))):
    grant = db.get(QuoteSkillGrant, grant_id)
    if grant is None or (actor.role != "admin" and grant.user_id != actor.user_id):
        raise HTTPException(404, "授权不存在。")
    grant.enabled = False
    db.commit()


@router.post("/bind")
def bind(payload: BindRequest, db: Session = Depends(get_db)):
    grant, user, credential = bind_grant(db, payload.code)
    return {"credential": credential, "expires_at": grant.credential_expires_at,
            "username": user.username, "display_name": user.display_name}


@router.get("/me")
def me(identity=Depends(skill_identity)):
    grant, user = identity
    return {"username": user.username, "display_name": user.display_name, "device_name": grant.name,
            "expires_at": grant.credential_expires_at, "capabilities": ["quote", "own_records", "unbind"]}


@router.delete("/binding", status_code=204)
def unbind(db: Session = Depends(get_db), identity=Depends(skill_identity)):
    grant, _ = identity
    grant.enabled = False
    db.commit()


@router.post("/quotes")
def quote(payload: QuoteRequest, db: Session = Depends(get_db), identity=Depends(skill_identity)):
    _, user = identity
    return quote_for_skill(db, user, payload.message)


@router.get("/records")
def records(limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
            db: Session = Depends(get_db), identity=Depends(skill_identity)):
    _, user = identity
    rows = db.scalars(select(SalesQuoteRecord).where(
        SalesQuoteRecord.scope_kind == "legacy", SalesQuoteRecord.actor_user_id == user.id,
    ).order_by(SalesQuoteRecord.id.desc()).offset(offset).limit(limit))
    return [public_record(row) for row in rows]


@router.get("/records/{quote_code}")
def record(quote_code: str, db: Session = Depends(get_db), identity=Depends(skill_identity)):
    _, user = identity
    if len(quote_code) != 8 or not quote_code.isascii() or not quote_code.isdigit():
        raise HTTPException(404, "报价记录不存在。")
    row = db.scalar(select(SalesQuoteRecord).where(
        SalesQuoteRecord.id == int(quote_code) - 10_000_000,
        SalesQuoteRecord.scope_kind == "legacy", SalesQuoteRecord.actor_user_id == user.id,
    ))
    if row is None or row.result_json.get("quote_code") != quote_code:
        raise HTTPException(404, "报价记录不存在。")
    return public_record(row)
