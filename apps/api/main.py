import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routes.ai_configs import router as ai_configs_router
from apps.api.routes.imports import router as imports_router
from apps.api.routes.quotes import router as quotes_router
from apps.api.routes.wecom_configs import router as wecom_configs_router


app = FastAPI(
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
app.include_router(imports_router)
app.include_router(ai_configs_router)
app.include_router(wecom_configs_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}
