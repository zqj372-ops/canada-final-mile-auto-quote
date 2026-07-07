import base64
import hashlib
import secrets


_PBKDF2_PREFIX = "pbkdf2_sha256"
_DEFAULT_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _DEFAULT_ITERATIONS)
    return ":".join(
        [
            _PBKDF2_PREFIX,
            str(_DEFAULT_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        prefix, iterations_value, salt_value, digest_value = password_hash.split(":", 3)
        if prefix != _PBKDF2_PREFIX:
            return False
        iterations = int(iterations_value)
        salt = base64.urlsafe_b64decode(salt_value.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_value.encode("ascii"))
    except Exception:
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return secrets.compare_digest(actual, expected)
