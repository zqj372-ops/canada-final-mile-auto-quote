import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_DEFAULT_SECRET = "local-dev-ai-config-secret"
_AES_PREFIX = "aesgcm2:"
_LEGACY_XOR_PREFIX = "xor1:"
_ASSOCIATED_DATA = b"canada-final-mile-config-secret-v2"


def encrypt_secret(value: str) -> str:
    nonce = os.urandom(12)
    payload = AESGCM(_encryption_key()).encrypt(nonce, value.encode("utf-8"), _ASSOCIATED_DATA)
    return _AES_PREFIX + base64.urlsafe_b64encode(nonce + payload).decode("ascii")


def decrypt_secret(value: str) -> str:
    if value.startswith(_AES_PREFIX):
        raw = base64.urlsafe_b64decode(value[len(_AES_PREFIX):].encode("ascii"))
        if len(raw) < 13:
            raise ValueError("Invalid encrypted secret payload.")
        nonce, payload = raw[:12], raw[12:]
        try:
            plaintext = AESGCM(_encryption_key()).decrypt(nonce, payload, _ASSOCIATED_DATA)
        except Exception as exc:
            raise ValueError("Encrypted secret authentication failed.") from exc
        return plaintext.decode("utf-8")
    if not value.startswith(_LEGACY_XOR_PREFIX):
        return value
    raw = base64.urlsafe_b64decode(value[len(_LEGACY_XOR_PREFIX):].encode("ascii"))
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


def _encryption_key() -> bytes:
    return hashlib.sha256(_secret_bytes()).digest()


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(data))
