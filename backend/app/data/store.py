"""Persistent storage of the data layer: price-bar history and the last good answer of each
source (so an outage shows the last data with their real date, labelled STALE)."""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db import SessionLocal

log = logging.getLogger(__name__)
KEEP_DAYS = {"M1": 45, "M5": 120}  # finer bars are pruned, coarser kept for good


def save_bars(code: str, tf: str, bars: list[tuple], source: str, session=None, meta: dict | None = None) -> int:
    """Store one provider's bars in its OWN history (market_bars): a bar of another provider at the same time
    is never touched. Closed bars are final; the forming bar is updated until it closes."""
    from app.data.migrations import PROVIDER_META, TF_SECONDS
    from app.models import MarketBar

    if not bars or not source:
        return 0
    meta = meta or {}
    own = session is None
    session = session or SessionLocal()
    now = dt.datetime.now(dt.timezone.utc)
    ptype, vkind, delay = PROVIDER_META.get(source, (None, None, None))
    span = TF_SECONDS.get(tf, 0)
    # a delayed source (Dukascopy) says up to when its data are complete: a bar ending later is still forming
    final_until = min(now.timestamp(), meta["complete_until"]) if meta.get("complete_until") else now.timestamp()
    try:
        rows = [{"code": code, "provider": source, "feed_symbol": meta.get("feed_symbol") or "", "tf": tf, "t": int(b[0]),
                 "o": b[1], "h": b[2], "l": b[3], "c": b[4], "v": (b[5] if len(b) > 5 and vkind else None),
                 "volume_kind": vkind, "price_type": meta.get("price_type") or ptype, "closed": int(b[0]) + span <= final_until,
                 "quality": meta.get("quality"), "delay_s": delay, "received_at": now, "origin": (meta.get("origin") or "")[:120]}
                for b in bars]
        updatable = ("o", "h", "l", "c", "v", "closed", "quality", "received_at", "feed_symbol", "origin", "volume_kind",
                     "price_type", "delay_s")
        if session.bind.dialect.name == "sqlite":
            for i in range(0, len(rows), 500):
                stmt = sqlite_insert(MarketBar).values(rows[i:i + 500])
                # a closed bar delivered again with the same OHLC keeps its first receipt time and origin (provenance);
                # it is updated only while it is forming or when the provider really revised it
                stmt = stmt.on_conflict_do_update(
                    index_elements=["code", "provider", "tf", "t"], set_={k: stmt.excluded[k] for k in updatable},
                    where=or_(MarketBar.closed.is_(False), MarketBar.o != stmt.excluded.o, MarketBar.h != stmt.excluded.h,
                              MarketBar.l != stmt.excluded.l, MarketBar.c != stmt.excluded.c))
                session.execute(stmt)
        else:  # other databases: simple merge on the provider's own key
            for r in rows:
                old = session.scalar(select(MarketBar).where(MarketBar.code == code, MarketBar.provider == source,
                                                             MarketBar.tf == tf, MarketBar.t == r["t"]))
                session.add(MarketBar(**r)) if old is None else [setattr(old, k, r[k]) for k in updatable]
        keep = KEEP_DAYS.get(tf)
        if keep:  # finer bars are kept for a limited time — per provider, never across providers
            cutoff = int((now - dt.timedelta(days=keep)).timestamp())
            session.execute(delete(MarketBar).where(MarketBar.code == code, MarketBar.provider == source, MarketBar.tf == tf,
                                                    MarketBar.t < cutoff))
        session.commit()
        return len(rows)
    finally:
        if own:
            session.close()


def load_bars(code: str, tf: str, provider: str, since: int | None = None, session=None, with_meta: bool = False) -> list:
    """One provider's stored history (e.g. for a backtest on a chosen source), oldest first."""
    from app.models import MarketBar

    own = session is None
    session = session or SessionLocal()
    try:
        q = select(MarketBar).where(MarketBar.code == code, MarketBar.tf == tf, MarketBar.provider == provider)
        if since is not None:
            q = q.where(MarketBar.t >= since)
        rows = session.scalars(q.order_by(MarketBar.t)).all()
        if with_meta:
            return [{"t": r.t, "o": r.o, "h": r.h, "l": r.l, "c": r.c, "v": r.v, "volume_kind": r.volume_kind,
                     "price_type": r.price_type, "closed": r.closed, "quality": r.quality, "delay_s": r.delay_s,
                     "received_at": r.received_at.isoformat(), "feed_symbol": r.feed_symbol, "origin": r.origin} for r in rows]
        return [(r.t, r.o, r.h, r.l, r.c, r.v) for r in rows]
    finally:
        if own:
            session.close()


def bar_sources(code: str, tf: str, session=None) -> list[str]:
    """Providers that have stored history for this instrument and timeframe."""
    from app.models import MarketBar

    own = session is None
    session = session or SessionLocal()
    try:
        return sorted({p for (p,) in session.execute(select(MarketBar.provider).where(MarketBar.code == code, MarketBar.tf == tf).distinct())})
    finally:
        if own:
            session.close()


def gaps(code: str, provider: str, tf: str, start: int, end: int, session=None) -> list[tuple[int, int]]:
    """Missing intraday bars of one provider while the market was open (by FTI's trading calendar), as
    (first missing bar start, number of missing bars). Computed on read — nothing is ever filled in."""
    from app.data import market_hours, universe
    from app.data.migrations import TF_SECONDS

    span = TF_SECONDS[tf]
    if span > 3600:
        raise ValueError("Mezery se počítají pro M1–H1; denní a delší svíčky závisí na kalendáři burzy.")
    inst = universe.get(code)
    have = {b[0] for b in load_bars(code, tf, provider, since=start, session=session) if b[0] <= end}
    out, run_start, run_len = [], None, 0
    for t in range(start - start % span, end + 1, span):
        expected = market_hours.state(inst, dt.datetime.fromtimestamp(t, dt.timezone.utc)).get("state") == market_hours.OPEN
        if expected and t not in have:
            run_start = t if run_start is None else run_start
            run_len += 1
        elif run_start is not None:
            out.append((run_start, run_len))
            run_start, run_len = None, 0
    if run_start is not None:
        out.append((run_start, run_len))
    return out


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
