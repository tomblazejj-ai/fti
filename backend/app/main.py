from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import scheduler
from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_instruments import router as instruments_router
from app.db import init_db

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="FTI – Financial Trading Intelligence API",
    description=(
        "Data zdarma z FRED (keyless CSV), CFTC, oficiálních RSS centrálních bank "
        "a GDELT. Žádné placené API, žádné registrace. Viz ARCHITECTURE.md."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # Vite dev server. In production the frontend is served by this same
    # process (below), so no cross-origin requests happen at all. A future
    # native mobile app doesn't send an Origin header and isn't affected.
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(instruments_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
