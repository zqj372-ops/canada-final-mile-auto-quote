import hashlib
import secrets


API_KEY_PREFIX = "caq_"


def generate_api_key() -> str:
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def verify_api_key(api_key: str, key_hash: str) -> bool:
    return secrets.compare_digest(hash_api_key(api_key), key_hash)


def mask_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 10:
        return "****"
    return f"{api_key[:7]}****{api_key[-4:]}"
