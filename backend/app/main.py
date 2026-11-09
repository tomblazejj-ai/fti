from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import scheduler
from app.ai.redact import install_log_filter
from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_fti import router as fti_router
from app.api.routes_instruments import router as instruments_router
from app.db import init_db

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
install_log_filter()  # no API key can ever end up in a log, whatever logs it


def _load_health() -> None:
    from app.data import health
    from app.db import SessionLocal

    session = SessionLocal()
    try:
        health.load(session)
    except Exception:  # noqa: BLE001 — monitoring history is optional
        pass
    finally:
        session.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    _load_health()
    scheduler.start()
    live = _start_live()
    yield
    if live:
        from app.live import runner

        runner.stop()
    scheduler.shutdown()


def _start_live() -> bool:
    """The LIVE engine runs only when the user switched it on (settings live.enabled) — it writes ticks and candles."""
    import os

    from app.data import settings_store

    if os.environ.get("FTI_DISABLE_LIVE") or not (settings_store.get("live", {}) or {}).get("enabled"):
        return False
    try:
        from app.live import runner

        runner.start()
        return True
    except Exception:  # noqa: BLE001 — the live terminal must never stop the app
        import logging

        logging.getLogger(__name__).exception("LIVE engine failed to start")
        return False


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

from app.api.routes_live import router as live_router  # noqa: E402
from app.api.routes_ctrader import router as ctrader_router  # noqa: E402

app.include_router(live_router)
app.include_router(ctrader_router)
app.include_router(fti_router)
app.include_router(instruments_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


class _Frontend(StaticFiles):
    """The page itself (index.html) is always revalidated, so a new build shows at the next open (8. 11.: the window kept
    an old index.html without the Intermarket card); the hashed scripts and styles may stay cached."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if (resp.media_type or "").startswith("text/html"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp


if FRONTEND_DIST.is_dir():
    app.mount("/", _Frontend(directory=FRONTEND_DIST, html=True), name="frontend")
