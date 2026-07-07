import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any


_DEFAULT_TOKEN_SECRET = "local-dev-auth-token-secret"
DEFAULT_TOKEN_TTL_SECONDS = 60 * 60 * 12


class TokenError(ValueError):
    pass


def create_access_token(payload: dict[str, Any], *, expires_in_seconds: int = DEFAULT_TOKEN_TTL_SECONDS) -> str:
    now = int(time.time())
    body = {
        **payload,
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    encoded_body = _b64url(json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _sign(encoded_body)
    return f"{encoded_body}.{signature}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        encoded_body, signature = token.split(".", 1)
    except ValueError as exc:
        raise TokenError("Invalid token format.") from exc
    if not hmac.compare_digest(_sign(encoded_body), signature):
        raise TokenError("Invalid token signature.")
    try:
        payload = json.loads(_b64url_decode(encoded_body).decode("utf-8"))
    except Exception as exc:
        raise TokenError("Invalid token payload.") from exc
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        raise TokenError("Token expired.")
    return payload


def _sign(encoded_body: str) -> str:
    digest = hmac.new(_secret_bytes(), encoded_body.encode("ascii"), hashlib.sha256).digest()
    return _b64url(digest)


def _secret_bytes() -> bytes:
    secret = os.getenv("AUTH_TOKEN_SECRET", _DEFAULT_TOKEN_SECRET)
    return secret.encode("utf-8") or _DEFAULT_TOKEN_SECRET.encode("utf-8")


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))
