"""Run an isolated local demo; no production DB, models, notifications or prices.

Run with .venv/bin/python scripts/run_workbench_preview.py.
Disposable fixture accounts: preview / preview (sales), reviewer / preview
(admin). Local loopback only.
"""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = tempfile.TemporaryDirectory(prefix="quote-workbench-preview-")
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{runtime.name}/preview.db"
os.environ["DEV_AUTH_DISABLED"] = "false"
os.environ["HERMES_CONTEXT_WORKER_ENABLED"] = "true"
os.environ["AUTH_TOKEN_SECRET"] = secrets.token_urlsafe(48)

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import uvicorn
from apps.api.db.models import Base, PostalCodeCityLookup, ZoneLookupRule, ZonePriceMatrix
from apps.api.db.repositories.user_repository import UserRepository
from apps.api.db.repositories.quote_rule_config_repository import QuoteRuleConfigRepository
from packages.quote_engine.workbench_config import QuoteWorkbenchConfig

engine = create_engine(os.environ["DATABASE_URL"])
Base.metadata.create_all(engine)
with Session(engine) as db:
    UserRepository(db).create_user(username="preview", password="preview", display_name="本地演示 · 测试价格", role="sales")
    UserRepository(db).create_user(username="reviewer", password="preview", display_name="本地审核 · 测试数据", role="admin")
    db.add(PostalCodeCityLookup(postal_code="L4K 2N2", preferred_city="Concord", province="ON", source="local_fixture"))
    db.add(ZoneLookupRule(postal_prefix="L4K", city="CONCORD", province="ON", origin="toronto", zone=2, note="Local fixture only"))
    for pallets in range(1, 9):
        db.add(ZonePriceMatrix(origin="toronto", zone=2, billing_pallets=pallets, base_price_usd=100 + 10 * pallets, source="local_fixture", last_updated="2026-10-12"))
    db.commit()
    config = QuoteWorkbenchConfig(sample_input="数量: 2托盘\n尺寸: 120x100x150 cm\n总重: 800 kg\n地址: 8888 Keele St\n城市: Concord\n省份: ON\n邮编: L4K 2N2\n地址类型: 商业地址\n尾板: 是\n手叉车: 否\n预约: 否")
    QuoteRuleConfigRepository(db).save_workbench_config(config)

if __name__ == "__main__":
    uvicorn.run("apps.api.main:app", host="127.0.0.1", port=8801)
