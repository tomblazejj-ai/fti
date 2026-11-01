"""Persistent storage of the data layer: price-bar history and the last good answer of each
source (so an outage shows the last data with their real date, labelled STALE)."""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db import SessionLocal

log = logging.getLogger(__name__)
KEEP_DAYS = {"M1": 45, "M5": 120}  # finer bars are pruned, coarser kept for good


def save_bars(code: str, tf: str, bars: list[tuple], source: str, session=None) -> int:
    from app.models import PriceBar

    if not bars:
        return 0
    own = session is None
    session = session or SessionLocal()
    try:
        rows = [{"code": code, "tf": tf, "t": int(b[0]), "o": b[1], "h": b[2], "l": b[3], "c": b[4],
                 "v": b[5] if len(b) > 5 else None, "source": source} for b in bars]
        if session.bind.dialect.name == "sqlite":
            for i in range(0, len(rows), 500):
                stmt = sqlite_insert(PriceBar).values(rows[i:i + 500])
                stmt = stmt.on_conflict_do_update(index_elements=["code", "tf", "t"],
                                                  set_={k: stmt.excluded[k] for k in ("o", "h", "l", "c", "v", "source")})
                session.execute(stmt)
        else:  # other databases: simple merge
            for r in rows:
                session.merge(PriceBar(**r))
        keep = KEEP_DAYS.get(tf)
        if keep:
            cutoff = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=keep)).timestamp())
            session.execute(delete(PriceBar).where(PriceBar.code == code, PriceBar.tf == tf, PriceBar.t < cutoff))
        session.commit()
        return len(rows)
    finally:
        if own:
            session.close()


def load_bars(code: str, tf: str, since: int | None = None, session=None) -> list[tuple]:
    from app.models import PriceBar

    own = session is None
    session = session or SessionLocal()
    try:
        q = select(PriceBar).where(PriceBar.code == code, PriceBar.tf == tf)
        if since is not None:
            q = q.where(PriceBar.t >= since)
        return [(r.t, r.o, r.h, r.l, r.c, r.v) for r in session.scalars(q.order_by(PriceBar.t))]
    finally:
        if own:
            session.close()


def bar_sources(code: str, tf: str, session=None) -> list[str]:
    from app.models import PriceBar

    own = session is None
    session = session or SessionLocal()
    try:
        return sorted({s for (s,) in session.execute(select(PriceBar.source).where(PriceBar.code == code, PriceBar.tf == tf).distinct())})
    finally:
        if own:
            session.close()


def cache_put(key: str, payload, source: str = "", session=None) -> None:
    from app.models import SeriesCache

    own = session is None
    session = session or SessionLocal()
    try:
        row = session.get(SeriesCache, key) or SeriesCache(key=key)
        row.payload = payload
        row.source = source
        row.fetched_at = dt.datetime.now(dt.timezone.utc)
        session.add(row)
        session.commit()
    except Exception:  # noqa: BLE001 — a cache write must never break the data flow
        log.exception("cache_put %s failed", key)
        session.rollback()
    finally:
        if own:
            session.close()


def cache_get(key: str, session=None):
    """(payload, fetched_at) of the last good answer, or (None, None)."""
    from app.models import SeriesCache

    own = session is None
    session = session or SessionLocal()
    try:
        row = session.get(SeriesCache, key)
        return (row.payload, row.fetched_at) if row else (None, None)
    except Exception:  # noqa: BLE001
        log.exception("cache_get %s failed", key)
        return None, None
    finally:
        if own:
            session.close()
