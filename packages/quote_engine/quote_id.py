from __future__ import annotations

import secrets
from time import time_ns


def generate_quote_id() -> str:
    """Return a time-ordered numeric id with a cross-process random suffix."""
    return f"{time_ns():019d}{secrets.randbelow(1_000_000_000_000):012d}"
