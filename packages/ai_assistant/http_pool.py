"""Bounded HTTP clients, isolated by endpoint, credential and timeout."""
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from threading import Lock

import httpx


@dataclass
class _Entry:
    client: httpx.Client
    users: int = 0


_lock = Lock()
_clients: OrderedDict[tuple[str, str, int], _Entry] = OrderedDict()
_MAX_CLIENTS = 16


@contextmanager
def model_http_client(base_url: str, credential: str, timeout: int):
    key = (base_url.rstrip("/"), hashlib.sha256(credential.encode()).hexdigest(), timeout)
    with _lock:
        entry = _clients.get(key)
        if entry is None:
            if len(_clients) >= _MAX_CLIENTS:
                idle = next((item for item, value in _clients.items() if value.users == 0), None)
                if idle is None:
                    raise RuntimeError("Model connection pool is busy; retry later.")
                _clients.pop(idle).client.close()
            entry = _Entry(httpx.Client(timeout=timeout, limits=httpx.Limits(max_connections=8, max_keepalive_connections=4)))
            _clients[key] = entry
        _clients.move_to_end(key)
        entry.users += 1
    try:
        yield entry.client
    finally:
        with _lock:
            entry.users -= 1


def close_model_http_clients() -> None:
    """Close idle clients after application requests have drained."""
    with _lock:
        for key in list(_clients):
            if _clients[key].users == 0:
                _clients.pop(key).client.close()
