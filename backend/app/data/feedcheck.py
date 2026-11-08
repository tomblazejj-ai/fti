"""Long-term cross-check of two independent feeds of the same instrument (XAUUSD: the user's broker
Purple Trading via MT5 against Dukascopy Bank) on identical UTC minute timestamps.

After every market refresh one more finished trading day is compared (oldest-missing first, up to
DAYS back), so the statistics grow over weeks instead of resting on a few sample days. Every outage
of either feed is recorded too. Nothing is filled in: only minutes present in both feeds are compared.
Results live in the database (SeriesCache "feedcheck:<code>") and survive restarts.
"""

from __future__ import annotations

import datetime as dt
import logging
import statistics

from app.data import store

log = logging.getLogger(__name__)

UTC = dt.timezone.utc
DAYS = 120
KEEP = 400


def compare(a: list[tuple], b: list[tuple]) -> dict:
    """OHLC differences (a − b) on identical timestamps; bars are (t, o, h, l, c, ...)."""
    bmap = {r[0]: r for r in b}
    common = [(r, bmap[r[0]]) for r in a if r[0] in bmap]
    out = {"matched": len(common), "only_a": len(a) - len(common), "only_b": len(b) - len(common)}
    for i, k in enumerate("OHLC", start=1):
        d = sorted(abs(x[i] - y[i]) for x, y in common)
        if d:
            out[k] = {"median": round(statistics.median(d), 4), "p95": round(d[int(0.95 * (len(d) - 1))], 4), "max": round(d[-1], 4)}
    if common:
        out["bias"] = round(statistics.fmean(x[4] - y[4] for x, y in common), 4)
    return out


def _load(code: str) -> dict:
    payload, _ = store.cache_get(f"feedcheck:{code}")
    return payload if isinstance(payload, dict) else {"days": {}, "outages": []}


def step(code: str = "XAUUSD", now: dt.datetime | None = None, mt5_range=None, duka_day=None) -> dict | None:
    """Compare one more finished day. Returns that day's result, or None when there is nothing to do."""
    from app.connectors import dukascopy
    from app.data import mt5

    now = now or dt.datetime.now(UTC)
    if not mt5.enabled():
        return None  # MT5 is optional: without it there is no second feed to compare against
    state = _load(code)
    todo = None
    for back in range(1, DAYS + 1):
        day = now.date() - dt.timedelta(days=back)
        if day.weekday() == 5 or day.isoformat() in state["days"]:
            continue
        todo = day
        break
    if todo is None:
        return None
    start = dt.datetime(todo.year, todo.month, todo.day, tzinfo=UTC)
    result: dict = {"day": todo.isoformat(), "checked_at": now.isoformat()}
    try:
        a, _ = (mt5_range or mt5.fetch_range)(code, "M1", start, start + dt.timedelta(days=1) - dt.timedelta(minutes=1))
        a = [r for r in a if start.timestamp() <= r[0] < start.timestamp() + 86400]
    except mt5.Mt5Unavailable as exc:
        state["outages"] = (state["outages"] + [{"at": now.isoformat(), "feed": "MT5", "error": str(exc)[:160]}])[-KEEP:]
        store.cache_put(f"feedcheck:{code}", state, source="FTI feedcheck")
        return None  # terminal closed: try again later, the day stays unchecked
    try:
        b = (duka_day or (lambda d: dukascopy._minute_day(code, d, [1])))(todo)
    except dukascopy.DukascopyUnavailable as exc:
        state["outages"] = (state["outages"] + [{"at": now.isoformat(), "feed": "Dukascopy", "error": str(exc)[:160]}])[-KEEP:]
        store.cache_put(f"feedcheck:{code}", state, source="FTI feedcheck")
        return None
    if b is None:
        return None
    try:  # the downloaded day also belongs to Dukascopy's own history (it used to be compared and then dropped)
        store.save_bars(code, "M1", b, "dukascopy", meta={"feed_symbol": code, "quality": "DELAYED",
                                                       "origin": "Dukascopy Bank (zpožděné kotace)",
                                                       "complete_until": start.timestamp() + 86400})
    except Exception:  # noqa: BLE001 — storing must never break the cross-check
        log.exception("storing the Dukascopy day %s failed", todo)
    result.update(compare(a, b))
    result["coverage_mt5"] = dukascopy.coverage(code, todo, a)["present"] if a else 0
    result["coverage_dukascopy"] = dukascopy.coverage(code, todo, b)["present"] if b else 0
    result["expected"] = len(dukascopy.expected_minutes(code, todo))
    state["days"][todo.isoformat()] = result
    if len(state["days"]) > KEEP:
        for k in sorted(state["days"])[: len(state["days"]) - KEEP]:
            del state["days"][k]
    store.cache_put(f"feedcheck:{code}", state, source="FTI feedcheck")
    return result


def summary(code: str = "XAUUSD") -> dict:
    """What the Data page shows: how many days were compared and how close the feeds are."""
    state = _load(code)
    days = [d for d in state["days"].values() if d.get("matched")]
    med = sorted(d["C"]["median"] for d in days if "C" in d)
    outages = state["outages"]
    return {"code": code, "days_compared": len(days),
            "median_close_diff": round(statistics.median(med), 4) if med else None,
            "worst_day_p95": max((d["C"]["p95"] for d in days if "C" in d), default=None),
            "bias": round(statistics.fmean(d["bias"] for d in days if "bias" in d), 4) if days else None,
            "coverage_mt5_pct": round(100 * sum(d["coverage_mt5"] for d in days) / max(1, sum(d["expected"] for d in days)), 2) if days else None,
            "coverage_dukascopy_pct": round(100 * sum(d["coverage_dukascopy"] for d in days) / max(1, sum(d["expected"] for d in days)), 2) if days else None,
            "outages": {"MT5": sum(o["feed"] == "MT5" for o in outages), "Dukascopy": sum(o["feed"] == "Dukascopy" for o in outages)},
            "last_days": sorted(days, key=lambda d: d["day"])[-10:]}
