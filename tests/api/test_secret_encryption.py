import base64

import pytest

from apps.api.security.secrets import decrypt_secret, encrypt_secret


def test_secret_encryption_is_authenticated_and_randomized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_CONFIG_SECRET", "unit-test-secret")

    first = encrypt_secret("sk-sensitive-value")
    second = encrypt_secret("sk-sensitive-value")

    assert first.startswith("aesgcm2:")
    assert second.startswith("aesgcm2:")
    assert first != second
    assert decrypt_secret(first) == "sk-sensitive-value"
    assert decrypt_secret(second) == "sk-sensitive-value"


def test_secret_encryption_rejects_tampering(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_CONFIG_SECRET", "unit-test-secret")
    encrypted = encrypt_secret("sk-sensitive-value")
    raw = bytearray(base64.urlsafe_b64decode(encrypted.removeprefix("aesgcm2:")))
    raw[-1] ^= 1
    tampered = "aesgcm2:" + base64.urlsafe_b64encode(raw).decode("ascii")

    with pytest.raises(ValueError, match="authentication failed"):
        decrypt_secret(tampered)


def test_legacy_xor_ciphertext_remains_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_CONFIG_SECRET", "legacy-key")
    plaintext = b"legacy-value"
    key = b"legacy-key"
    payload = bytes(value ^ key[index % len(key)] for index, value in enumerate(plaintext))
    legacy = "xor1:" + base64.urlsafe_b64encode(payload).decode("ascii")

    assert decrypt_secret(legacy) == "legacy-value"
