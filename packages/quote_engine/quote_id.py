from __future__ import annotations

from datetime import datetime
from itertools import count
from threading import Lock
from zoneinfo import ZoneInfo


_counter = count()
_lock = Lock()
_timezone = ZoneInfo("Asia/Shanghai")


def generate_quote_id() -> str:
    """Return an 8-digit, time-based quote id: DDHHMM + two-digit sequence."""
    now = datetime.now(_timezone)
    with _lock:
        suffix = next(_counter) % 100
    return f"{now:%d%H%M}{suffix:02d}"
