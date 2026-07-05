import base64
import os


_DEFAULT_SECRET = "local-dev-ai-config-secret"


def encrypt_secret(value: str) -> str:
    payload = _xor(value.encode("utf-8"), _secret_bytes())
    return "xor1:" + base64.urlsafe_b64encode(payload).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value.startswith("xor1:"):
        return value
    raw = base64.urlsafe_b64decode(value[5:].encode("ascii"))
    return _xor(raw, _secret_bytes()).decode("utf-8")


def mask_tail(value: str | None, *, prefix_length: int = 3, tail_length: int = 4) -> str | None:
    if not value:
        return None
    if len(value) <= prefix_length + tail_length:
        return "****"
    return f"{value[:prefix_length]}****{value[-tail_length:]}"


def _secret_bytes() -> bytes:
    secret = os.getenv("AI_CONFIG_SECRET", _DEFAULT_SECRET)
    return secret.encode("utf-8") or _DEFAULT_SECRET.encode("utf-8")


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(data))
