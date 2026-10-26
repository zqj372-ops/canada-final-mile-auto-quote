import os
from contextlib import asynccontextmanager

from packages.ai_assistant.http_pool import close_model_http_clients

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routes.ai_configs import router as ai_configs_router
from apps.api.routes.ai_quotes import router as ai_quotes_router
from apps.api.routes.customs import router as customs_router
from apps.api.routes.schedules import router as schedules_router
from apps.api.routes.api_keys import router as api_keys_router
from apps.api.routes.auth import router as auth_router
from apps.api.routes.audit import router as audit_router
from apps.api.routes.email_configs import router as email_configs_router
from apps.api.routes.hermes_diagnostics import router as hermes_diagnostics_router
from apps.api.routes.hermes_learning import router as hermes_learning_router
from apps.api.routes.imports import router as imports_router
from apps.api.routes.manual_tasks import router as manual_tasks_router
from apps.api.routes.maps import router as maps_router
from apps.api.routes.quote_configs import router as quote_configs_router
from apps.api.routes.quote_skill import router as quote_skill_router
from apps.api.routes.quotes import router as quotes_router
from apps.api.routes.sales_records import router as sales_records_router
from apps.api.routes.search_configs import router as search_configs_router
from apps.api.routes.users import router as users_router
from apps.api.routes.wecom_configs import router as wecom_configs_router



@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = None
    if os.getenv("HERMES_CONTEXT_WORKER_ENABLED", "false").lower() in {"1", "true", "yes"}:
        from apps.api.services.diagnostic_context_worker import start_context_worker
        worker = start_context_worker()
    yield
    if worker:
        stop, thread = worker
        stop.set()
        thread.join(timeout=5)
    close_model_http_clients()


app = FastAPI(
    lifespan=lifespan,
    title="Canada Final Mile Auto Quote API",
    version="0.1.0",
    description="Deterministic quote API for Canada final-mile truck delivery.",
)

cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(quotes_router)
app.include_router(ai_quotes_router)
app.include_router(customs_router)
app.include_router(schedules_router)
app.include_router(sales_records_router)
app.include_router(auth_router)
app.include_router(manual_tasks_router)
app.include_router(audit_router)
app.include_router(hermes_diagnostics_router)
app.include_router(hermes_learning_router)
app.include_router(maps_router)
app.include_router(imports_router)
app.include_router(quote_configs_router)
app.include_router(quote_skill_router)
app.include_router(ai_configs_router)
app.include_router(search_configs_router)
app.include_router(email_configs_router)
app.include_router(wecom_configs_router)
app.include_router(api_keys_router)
app.include_router(users_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}
