from fastapi import FastAPI

from apps.api.routes.imports import router as imports_router
from apps.api.routes.quotes import router as quotes_router


app = FastAPI(
    title="Canada Final Mile Auto Quote API",
    version="0.1.0",
    description="Deterministic quote API for Canada final-mile truck delivery.",
)

app.include_router(quotes_router)
app.include_router(imports_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}

