"""Background refresh: one ingestion cycle at startup, then every N minutes.

Runs in-process (APScheduler BackgroundScheduler) — no external service,
no cost. Disabled with FTI_DISABLE_SCHEDULER=1 (tests set this so they
never hit the network).
"""

from __future__ import annotations

import datetime as dt
import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

from app.db import SessionLocal
from app.ingestion.run_ingest import compute_and_store_score, refresh_market

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_MINUTES = int(os.getenv("FTI_REFRESH_MINUTES", "30"))
# prices, technicals, trends, DXY and the verdict — between the full cycles
MARKET_REFRESH_MINUTES = int(os.getenv("FTI_MARKET_REFRESH_MINUTES", "5"))

_scheduler: BackgroundScheduler | None = None


def _run_cycle_job() -> None:
    session = SessionLocal()
    try:
        compute_and_store_score(session)
    except Exception:  # noqa: BLE001 — a failed cycle must not kill the scheduler
        logger.exception("Scheduled ingestion cycle failed")
    finally:
        _persist_health(session)
        _ai_after_cycle(session)
        session.close()
        _cloud_sync(light=False)


def _cloud_sync(light: bool) -> None:
    """Variant A: send the results to the user's own Cloudflare Worker (only when set up). Never breaks the job."""
    from app.cloud import sync

    sync.after_cycle(light=light)


def _ai_after_cycle(session) -> None:
    """Event-driven AI (only when the user switched automatic analyses on). Never breaks the cycle."""
    from app.ai import triggers

    try:
        triggers.after_cycle(session)
    except Exception:  # noqa: BLE001 — AI is an overlay: FTI works the same without it
        logger.exception("AI after the cycle failed")
        session.rollback()


def _persist_health(session) -> None:
    from app.data import health

    try:
        health.persist(session)
    except Exception:  # noqa: BLE001 — monitoring must never break the cycle
        logger.exception("Saving source health failed")
        session.rollback()


def _market_job() -> None:
    session = SessionLocal()
    try:
        refresh_market(session)
    finally:
        _persist_health(session)
        session.close()
        _cloud_sync(light=True)
        _collect_history()
        _feed_check()


def _collect_history() -> None:
    """Keep the Dukascopy history of XAUUSD growing even while MT5 is the feed shown. Never breaks the job."""
    from app.data import bars

    try:
        bars.collect_history()
    except Exception:  # noqa: BLE001 — collecting a second provider's history must never disturb the data refresh
        logger.exception("Collecting provider history failed")


def _feed_check() -> None:
    """One more day of the long-term MT5 × Dukascopy comparison (only when MT5 is on). Never breaks the job."""
    from app.data import feedcheck

    try:
        feedcheck.step()
    except Exception:  # noqa: BLE001 — a cross-check must never disturb the data refresh
        logger.exception("Feed cross-check failed")


def start() -> None:
    global _scheduler
    if os.getenv("FTI_DISABLE_SCHEDULER") == "1" or _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _run_cycle_job,
        "interval",
        minutes=REFRESH_INTERVAL_MINUTES,
        next_run_time=dt.datetime.now(dt.timezone.utc),  # first cycle right away, in the background
        max_instances=1,
        coalesce=True,
        # After the PC wakes from sleep the run is overdue; APScheduler's default
        # 1 s grace would silently skip it and leave old data up until the next slot.
        misfire_grace_time=None,
        id="ingestion_cycle",
    )
    _scheduler.add_job(
        _market_job,
        "interval",
        minutes=MARKET_REFRESH_MINUTES,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
        id="market_refresh",
    )
    _scheduler.start()


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def next_run_at() -> dt.datetime | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job("ingestion_cycle")
    return job.next_run_time if job else None
