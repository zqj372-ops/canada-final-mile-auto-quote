"""Shared API scope gate and atomic, persistent per-principal/global budget."""
import hashlib
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import time

from fastapi import HTTPException
from packages.ai_assistant.quote_scope import RATE_REPLY, SCOPE_REPLY, DETAILS_REPLY, scope_decision


def require_quote_scope(message: str, *, has_draft: bool = False):
    decision = scope_decision(message, has_draft=has_draft)
    if decision == "help":
        raise HTTPException(status_code=422, detail=DETAILS_REPLY, headers={"X-Quote-Error-Code": "quote_details_required"})
    if decision != "quote":
        raise HTTPException(status_code=422, detail=SCOPE_REPLY, headers={"X-Quote-Error-Code": "quote_scope_only"})


def reserve_api_quote(actor):
    # Both routes and all tokens for one user share the budget; each API key
    # has its own principal, also subject to the global budget. No
    # IP-based identity: a reverse proxy must not merge or reset user quotas.
    identity = f"user:{actor.user_id}" if actor.user_id is not None else f"key:{actor.api_key_id}"
    principal = hashlib.sha256(identity.encode()).hexdigest()
    path = Path(os.getenv("QUOTE_ADMISSION_DB", "outputs/quote_admission.sqlite3"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=5)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS requests (principal TEXT NOT NULL, created REAL NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS requests_created ON requests(created)")
            db.execute("BEGIN IMMEDIATE")
            now = time.time()
            db.execute("DELETE FROM requests WHERE created <= ?", (now - 3600,))
            for seconds, per_user, total in ((60, 10, 30), (3600, 120, 300)):
                row = db.execute("SELECT count(*),coalesce(sum(principal=?),0) FROM requests WHERE created>?", (principal, now-seconds)).fetchone()
                if row[0] >= total or row[1] >= per_user:
                    raise HTTPException(429, detail=RATE_REPLY, headers={"Retry-After": str(seconds), "X-Quote-Error-Code": "quote_rate_limited"})
            db.execute("INSERT INTO requests VALUES (?,?)", (principal, now))
    except (OSError, sqlite3.Error):
        raise HTTPException(503, detail="询价服务暂时不可用，请稍后再试。", headers={"X-Quote-Error-Code": "quote_admission_unavailable"}) from None
