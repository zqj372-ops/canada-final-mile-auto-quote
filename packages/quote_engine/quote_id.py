from __future__ import annotations

import secrets
from os import getpid
from threading import Lock
from time import time_ns


_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_TIMESTAMP_LENGTH = 9
_RANDOM_LENGTH = 6
_RANDOM_LIMIT = 1 << (_RANDOM_LENGTH * 5)
_lock = Lock()
_last_timestamp_ms = -1
_last_random = -1
_last_pid = getpid()


def _encode_base32(value: int, length: int) -> str:
    encoded = ["0"] * length
    for index in range(length - 1, -1, -1):
        encoded[index] = _ALPHABET[value & 31]
        value >>= 5
    if value:
        raise ValueError("value does not fit in the requested quote id segment")
    return "".join(encoded)


def generate_quote_id() -> str:
    """Return a compact, time-ordered 15-character quote id.

    The Crockford Base32 alphabet avoids ambiguous letters. A 45-bit
    millisecond timestamp keeps ids sortable, while the 30-bit suffix is
    randomized per process and incremented for same-millisecond calls.
    """

    global _last_pid, _last_random, _last_timestamp_ms

    timestamp_ms = time_ns() // 1_000_000
    process_id = getpid()
    with _lock:
        if process_id != _last_pid:
            _last_pid = process_id
            _last_timestamp_ms = -1
            _last_random = -1

        if timestamp_ms > _last_timestamp_ms:
            random_part = secrets.randbelow(_RANDOM_LIMIT)
        elif _last_random + 1 < _RANDOM_LIMIT:
            timestamp_ms = _last_timestamp_ms
            random_part = _last_random + 1
        else:
            timestamp_ms = _last_timestamp_ms + 1
            random_part = secrets.randbelow(_RANDOM_LIMIT)

        _last_timestamp_ms = timestamp_ms
        _last_random = random_part

    return _encode_base32(timestamp_ms, _TIMESTAMP_LENGTH) + _encode_base32(random_part, _RANDOM_LENGTH)
