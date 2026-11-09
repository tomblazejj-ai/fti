"""Read-only endpoints the frontend dashboard is built on.

Rule for everything here: only return what is stored or verifiably known.
Instruments without an engine come back as status "coming_soon" with no
score fields at all — there is nothing for a client to accidentally render.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import scheduler
from app.db import get_session
from app.ingestion import run_ingest
from app.market import market_status
from app.instruments import INSTRUMENTS, INSTRUMENTS_BY_CODE, PRIMARY_HORIZON, XAUUSD_FACTOR_TO_PILLAR
from app.models import (AnalysisSnapshot, Instrument, MacroObservation, MacroSeries, NewsItem, ScoreHistoryEntry, ScoreSnapshot,
                        TraScorePoint)
from app.news.grouping import group_into_events
from app.scoring.xauusd import FOMC_DECISION_DATES_2026, SUPPORTED_HORIZONS

router = APIRouter(tags=["dashboard"])

FOMC_SOURCE_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"


def upcoming_events(today: dt.date) -> list[dict]:
    """Only events whose date is verified from an official source. Time is
    null on purpose: the Fed calendar page lists dates, not release times,
    and we don't fill in a time we haven't sourced.
    """
    return [
        {
            "date": d,
            "time": None,
            "event": "Rozhodnutí FOMC o sazbách",
            "importance": "vysoký",
            "importance_basis": "Přímo ovlivňuje pilíř Fed (váha 20 ze 100 v modelu XAUUSD).",
            "instruments": ["XAUUSD"],
            "factor": "fed",
            "source_url": FOMC_SOURCE_URL,
        }
        for d in FOMC_DECISION_DATES_2026
        if dt.date.fromisoformat(d) >= today
    ]


def _latest_snapshots(session: Session, instrument_id: int, horizon: str, limit: int) -> list[ScoreSnapshot]:
    return list(
        session.scalars(
            select(ScoreSnapshot)
            .where(ScoreSnapshot.instrument_id == instrument_id, ScoreSnapshot.horizon == horizon)
            .order_by(ScoreSnapshot.computed_at.desc())
            .limit(limit)
        )
    )


def _coverage(pillar_breakdown: dict) -> dict:
    counts = {"ok": 0, "partial": 0, "unavailable": 0}
    backed = 0
    for p in pillar_breakdown.values():
        counts[p["data_quality"]] = counts.get(p["data_quality"], 0) + 1
        # same rule as PillarResult.has_evidence
        if p["data_quality"] == "ok" or (p["data_quality"] == "partial" and abs(p["points"]) >= 0.05):
            backed += 1
    return {**counts, "backed": backed, "total": len(pillar_breakdown)}


def _main_driver(pillar_breakdown: dict) -> dict | None:
    candidates = [(name, p) for name, p in pillar_breakdown.items() if p["data_quality"] != "unavailable" and abs(p["points"]) >= 0.05]
    if not candidates:
        return None
    name, p = max(candidates, key=lambda item: abs(item[1]["points"]))
    return {"pillar": name, "impact": p["impact"], "points": p["points"], "reason": p["reasons"][0] if p["reasons"] else ""}


def _live_summary(session: Session, code: str) -> dict:
    instrument = session.scalar(select(Instrument).where(Instrument.code == code))
    if instrument is None:
        return {"computed": False}
    latest_two = _latest_snapshots(session, instrument.id, PRIMARY_HORIZON, 2)
    if not latest_two:
        return {"computed": False}
    latest = latest_two[0]
    previous = latest_two[1] if len(latest_two) > 1 else None
    horizons = []
    for h in SUPPORTED_HORIZONS:
        snaps = _latest_snapshots(session, instrument.id, h, 1)
        if snaps:
            horizons.append({"horizon": h, "bias": snaps[0].bias, "direction": snaps[0].direction, "score": snaps[0].score})
    events = upcoming_events(dt.date.today())
    analysis = _latest_analysis(session, instrument.id)
    calendar = (analysis.payload.get("calendar") or {}) if analysis else {}
    next_high = calendar.get("next_high")
    if next_high:
        # the official calendar knows CPI/NFP/PCE/GDP too, not just FOMC
        events = [{
            "date": next_high["date"], "time": next_high["time"], "event": next_high["name"],
            "importance": "vysoký", "importance_basis": next_high["impact"], "instruments": ["XAUUSD"],
            "factor": None, "source_url": None,
        }]
    return {
        "computed": True,
        "computed_at": latest.computed_at,
        "primary_horizon": PRIMARY_HORIZON,
        "bias": latest.bias,
        "direction": latest.direction,
        "score": latest.score,
        "score_change": (latest.score - previous.score) if previous else None,
        "previous_computed_at": previous.computed_at if previous else None,
        "main_driver": _main_driver(latest.pillar_breakdown),
        "data_coverage": _coverage(latest.pillar_breakdown),
        "horizons": horizons,
        "next_event": events[0] if events else None,
        "verdict": _verdict_brief(analysis),
        "mtf": _mtf_brief(analysis),
        "dxy": _dxy_brief(analysis),
    }


def _latest_analysis(session: Session, instrument_id: int) -> AnalysisSnapshot | None:
    return session.scalar(
        select(AnalysisSnapshot)
        .where(AnalysisSnapshot.instrument_id == instrument_id)
        .order_by(AnalysisSnapshot.computed_at.desc())
    )


def _verdict_brief(analysis: AnalysisSnapshot | None) -> dict | None:
    if analysis is None:
        return None
    v = analysis.payload.get("verdict") or {}
    t = analysis.payload.get("technical") or {}
    return {
        "action": v.get("action"),
        "headline": v.get("headline"),
        "direction_text": v.get("direction_text"),
        "action_text": v.get("action_text"),
        "summary": v.get("summary"),
        "confidence": v.get("confidence"),
        "trend": t.get("trend"),
        "trend_label": t.get("trend_label"),
        "change_20d": (t.get("changes") or {}).get("20d"),
    }


def _dxy_brief(analysis: AnalysisSnapshot | None) -> dict | None:
    d = (analysis.payload.get("dxy") if analysis else None) or None
    if not d:
        return None
    return {"price": d.get("price"), "swing": (d.get("trends") or {}).get("swing"),
            "corr60": ((d.get("correlation") or {}).get("d60") or {}).get("value"),
            "effect_on_gold": d.get("effect_on_gold"), "text": d.get("text")}


def _mtf_brief(analysis: AnalysisSnapshot | None) -> dict | None:
    m = (analysis.payload.get("mtf") if analysis else None) or None
    if not m:
        return None
    return {
        "price": m.get("price"),
        "price_time": m.get("price_time"),
        "timeframes": [{"tf": t["tf"], "direction": t["direction"], "word": t["word"]} for t in m.get("timeframes", [])],
        "intraday": m.get("intraday"),
        "swing": m.get("swing"),
        "overall": m.get("overall"),
    }


@router.get("/instruments/{code}/analysis")
def get_analysis(code: str, session: Session = Depends(get_session)):
    code = code.upper()
    instrument = session.scalar(select(Instrument).where(Instrument.code == code))
    analysis = _latest_analysis(session, instrument.id) if instrument else None
    if analysis is None:
        raise HTTPException(status_code=404, detail="Souhrn, trend a korelace zatím nejsou spočítané.")
    return {"computed_at": analysis.computed_at, **analysis.payload}


@router.get("/dashboard")
def dashboard(session: Session = Depends(get_session)):
    out = []
    for info in INSTRUMENTS:
        entry = {"code": info.code, "name": info.name, "asset_class": info.asset_class, "status": info.status}
        if info.status == "live":
            entry["summary"] = _live_summary(session, info.code)
        out.append(entry)
    return {"instruments": out, "status": status()}


@router.get("/status")
def status():
    cycle = run_ingest.LAST_CYCLE
    return {
        "last_cycle_started_at": cycle["started_at"],
        "last_cycle_finished_at": cycle["finished_at"],
        "cycle_running": cycle["running"],
        "last_cycle_error": cycle["error"],
        "last_cycle_warnings": cycle["warnings"],
        "next_scheduled_run_at": scheduler.next_run_at(),
        "refresh_interval_minutes": scheduler.REFRESH_INTERVAL_MINUTES,
    }


@router.get("/events/upcoming")
def get_upcoming_events():
    return {
        "events": upcoming_events(dt.date.today()),
        "coverage_note": (
            "Zatím jsou napojené jen termíny rozhodnutí FOMC (ověřené z federalreserve.gov). "
            "Kalendáře zveřejnění CPI, NFP, PCE a HDP zatím napojené nejsou."
        ),
    }


@router.get("/instruments/{code}/news")
def get_news(code: str, limit: int = 30, session: Session = Depends(get_session)):
    code = code.upper()
    if INSTRUMENTS_BY_CODE.get(code) is None or INSTRUMENTS_BY_CODE[code].status != "live":
        raise HTTPException(status_code=404, detail=f"News pro {code} zatím nejsou k dispozici.")
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=run_ingest.NEWS_LOOKBACK_DAYS)
    items = list(session.scalars(select(NewsItem).where(NewsItem.published_at >= cutoff)))
    events = group_into_events(items, XAUUSD_FACTOR_TO_PILLAR, code)
    return {"events": events[:limit], "total_events": len(events)}


@router.get("/instruments/{code}/history/{entry_id}")
def get_history_entry(code: str, entry_id: int, session: Session = Depends(get_session)):
    code = code.upper()
    entry = session.get(ScoreHistoryEntry, entry_id)
    instrument = session.scalar(select(Instrument).where(Instrument.code == code))
    if entry is None or instrument is None or entry.instrument_id != instrument.id:
        raise HTTPException(status_code=404, detail="Záznam historie nenalezen.")

    news = []
    if entry.related_news_ids:
        for n in session.scalars(select(NewsItem).where(NewsItem.id.in_(entry.related_news_ids))):
            news.append({
                "id": n.id, "title": n.title, "source": n.source, "url": n.url or None,
                "published_at": n.published_at, "time_basis": n.time_basis, "factor_tags": n.factor_tags, "sentiment_scores": n.sentiment_scores,
            })
    observations = []
    if entry.related_observation_ids:
        rows = session.execute(
            select(MacroObservation, MacroSeries)
            .join(MacroSeries, MacroObservation.series_id == MacroSeries.id)
            .where(MacroObservation.id.in_(entry.related_observation_ids))
        )
        for obs, series in rows:
            observations.append({
                "id": obs.id, "source": series.source, "series": series.external_id, "label": series.label,
                "unit": series.unit, "period": obs.period, "actual": obs.actual, "previous": obs.previous,
                "source_url": obs.source_url,
            })

    return {
        "id": entry.id,
        "changed_at": entry.changed_at,
        "horizon": entry.horizon,
        "old_score": entry.old_score,
        "new_score": entry.new_score,
        "old_bias": entry.old_bias,
        "new_bias": entry.new_bias,
        "reason": entry.reason,
        "pillar_deltas": entry.pillar_deltas,
        "news": news,
        "observations": observations,
    }


# ---------------------------------------------------------------- live quotes
# Short in-memory caches: the UI polls every ~60 s, Kraken is asked at most
# once per TTL no matter how many windows are open.
_live_cache: dict[str, tuple[float, object]] = {}
TICKER_TTL, CANDLE_TTL = 30.0, 60.0


def _cached(key: str, ttl: float, fn):
    import time

    hit = _live_cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    value = fn()
    _live_cache[key] = (time.monotonic(), value)
    return value


@router.get("/tickers")
def get_tickers(session: Session = Depends(get_session)):
    from app.data import prices

    def build():
        out, missing = [], []
        for code in prices.TICKER_CODES:
            q = prices.quote(code)
            if not q.get("available"):
                missing.append({"symbol": code, "label": q.get("symbol", code), "market": q.get("market"),
                                "reason": " ".join(q.get("notes") or [])[:200]})
                continue
            lq = q["last_quote"]
            out.append({"symbol": code, "label": q["symbol"], "price": round(q["price"], q["digits"]), "digits": q["digits"],
                        "change_pct": q["change_pct"], "source": q["source"], "provider": q["provider"],
                        "live": bool(lq.get("tradable_now")), "as_of": lq.get("time"), "quote_time_cs": lq.get("time_cs"),
                        "market": q["market"], "proxy": q["proxy"], "kind_cs": q["kind_cs"], "quality": q["quality"],
                        "reference": q["reference"], "time_verified": bool(lq.get("time_verified")), "itype_cs": q["itype_cs"],
                        "indicative": bool(q.get("indicative"))})
        return out, missing

    live, unavailable = build()  # no separate cache: the ticker shows exactly the quote every other module shows
    live = [dict(q) for q in live]
    error = None
    instrument = session.scalar(select(Instrument).where(Instrument.code == "XAUUSD"))
    analysis = _latest_analysis(session, instrument.id) if instrument else None
    daily = []
    for m in ((analysis.payload.get("markets") or {}).get("markets") or []) if analysis else []:
        p = m.get("price") or {}
        if p and not p.get("live") and p.get("value") is not None:
            daily.append({"symbol": m["code"], "label": m["name"], "price": round(p["value"], m["digits"] if m["digits"] < 4 else 4),
                          "digits": m["digits"] if m["digits"] < 4 else 4, "change_pct": p.get("change_pct"), "source": p.get("source"),
                          "live": False, "as_of": (p.get("as_of") or "")[:10]})
    now = dt.datetime.now(dt.timezone.utc)
    market = market_status.status(now)
    from app.data import market_hours, universe

    paxg = next((q["price"] for q in live if q["symbol"] == "PAXGUSD"), None)
    check = _cached("price_check", 60.0, lambda: _price_check(paxg))
    weekend = None  # the old "weekend gap" read PAXG as if it were spot gold — removed (user's spec 2026-11-01)
    return {"live": live, "daily": [], "unavailable": unavailable, "error": error, "fetched_at": now, "market": market,
            "price_check": check, "weekend": weekend}


def _price_check(paxg: float | None) -> dict:
    from app.connectors import bullionvault, kraken

    try:
        bv = bullionvault.fetch_gold_usd()["mid"]
    except bullionvault.BullionVaultUnavailableError:
        bv = None
    try:
        xaut = kraken.fetch_last({"XAUTUSD": "XAUTUSD"}).get("XAUTUSD")
    except kraken.KrakenUnavailableError:
        xaut = None
    return market_status.price_check(paxg, bv, xaut)


def _weekend_gap(paxg_now: float | None) -> dict | None:
    """While spot is shut, PAXG keeps trading — its move hints at the opening gap."""
    from app.connectors import kraken

    try:
        hourly = _cached("candles:H1", CANDLE_TTL, lambda: kraken.fetch_ohlc(kraken.TIMEFRAMES["H1"]))
    except kraken.KrakenUnavailableError:
        return None
    if not hourly or not paxg_now:
        return None
    last = hourly[-1]  # weekend candles are filtered out → this is the last spot-hours bar
    return {"spot_close": last.close, "spot_close_time": (last.time + dt.timedelta(hours=1)).isoformat(),
            "paxg_now": paxg_now, "change_pct": round((paxg_now / last.close - 1) * 100, 2)}


def _fixings():
    from app.connectors import ecb
    from app.market import dxy

    return _cached("ecb", 3600.0, lambda: dxy._JpySek(ecb.fetch_history(dt.datetime.now(dt.timezone.utc))))


def _live_dxy() -> dict | None:
    """DXY now: Kraken EUR/GBP/CAD/CHF + ECB JPY/SEK (see app/market/dxy.py)."""
    from app.connectors import ecb, kraken
    from app.market import dxy

    def compute():
        fix = _fixings()
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        now_val = dxy.live_quote(kraken.fetch_last(kraken.DXY_PAIRS), fix, today)
        daily = _cached("dxy_d1", 900.0, lambda: dxy.fetch_candles(fix, {"D1": 1440})[0].get("D1", []))
        prev = daily[-2].close if len(daily) >= 2 else None
        return {"symbol": "DXY", "label": "DXY", "price": round(now_val, 3), "digits": 3,
                "change_pct": round((now_val / prev - 1) * 100, 2) if prev else None, "source": "Kraken + ECB", "live": True}

    try:
        return _cached("dxy_live", TICKER_TTL, compute)
    except (kraken.KrakenUnavailableError, ecb.EcbUnavailableError, TypeError):
        return None


@router.get("/instruments/{code}/candles")
def get_candles(code: str, tf: str = "H1"):
    """OHLC bars of ONE instrument from its own feeds (app/data/bars.py) with provenance and the
    data-quality label. XAUUSD never gets PAXG data: without an XAUUSD feed it is unavailable."""
    from app.data import bars as bars_mod, universe

    code, tf = code.upper(), tf.upper()
    if code == "DXY":
        return _dxy_candles(tf)
    if universe.get(code) is None:
        raise HTTPException(status_code=404, detail="Tento instrument FTI nezná.")
    if tf not in universe.TF_MINUTES:
        raise HTTPException(status_code=400, detail=f"Neznámý timeframe {tf}.")
    bs = bars_mod.get_bars(code, tf)
    info = bs.describe()
    if not bs.ok:
        raise HTTPException(status_code=503, detail=" ".join(bs.notes) or "Data nejsou k dispozici.")
    rows = _chart_rows(bs.bars[-600:])
    return {"tf": tf, "code": code, "source": bs.source, "provider": bs.provider, "candles": rows, "days": _day_labels(rows, tf),
            "line_only": bs.close_only,
            "quality": bs.quality, "proxy": bs.proxy, "notes": bs.notes, "instrument": info["instrument"], "kind": bs.kind,
            "market": bs.market, "last_quote": bs.last_quote,
            "kind_cs": info["kind_cs"], "volume_note": bs.meta.get("volume"), "fetched_at": dt.datetime.now(dt.timezone.utc)}


def _day_labels(rows: list[list], tf: str) -> list[str] | None:
    """The trading day of each daily / weekly candle (YYYY-MM-DD). A broker candle starts at 17:00 New York the evening
    before, so the local time of its start would show the previous date; a week is named by its Monday."""
    if tf not in ("D1", "W1"):
        return None
    from app.data.market_hours import trading_date

    out = []
    for r in rows:
        d = trading_date(r[0])
        if tf == "W1" and d.weekday() == 6:  # a week starting Saturday 17:00 New York: its trading date is Sunday
            d += dt.timedelta(days=1)
        out.append(d.isoformat())
    return out


def _chart_rows(bars: list) -> list[list]:
    """[t, o, h, l, c, ema20, ema50] for the chart."""
    from app.analysis import indicators

    closes = [b[4] for b in bars]
    e20, e50 = indicators.ema(closes, 20), indicators.ema(closes, 50)
    return [[int(b[0]), b[1], b[2], b[3], b[4], round(e20[i], 6) if e20[i] is not None else None,
             round(e50[i], 6) if e50[i] is not None else None] for i, b in enumerate(bars)]


def _dxy_candles(tf: str):
    """The dollar index rebuilt from its ICE formula: Kraken FX quotes + ECB fixings (JPY, SEK)."""
    from app.connectors import ecb, kraken
    from app.market import dxy
    from app.data import quality

    if tf not in kraken.TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"DXY je jen pro {', '.join(kraken.TIMEFRAMES)}.")

    def build():
        out, errors = dxy.fetch_candles(_fixings(), {tf: kraken.TIMEFRAMES[tf]}, sleep_fn=lambda s: None)
        if tf not in out:
            raise kraken.KrakenUnavailableError("; ".join(errors) or "žádné svíčky")
        return out[tf]

    try:
        candles = _cached(f"dxy:{tf}", CANDLE_TTL, build)
    except (kraken.KrakenUnavailableError, ecb.EcbUnavailableError) as exc:
        raise HTTPException(status_code=503, detail=f"DXY se teď nepodařilo spočítat: {exc}") from exc
    bars = [(int(c.time.timestamp()), c.open, c.high, c.low, c.close, None) for c in candles]
    now = dt.datetime.now(dt.timezone.utc)
    return {"tf": tf, "code": "DXY", "source": "DXY přepočet podle vzorce ICE: Kraken (EUR, GBP, CAD, CHF) + ECB (JPY, SEK)",
            "provider": "calc", "candles": _chart_rows(bars), "line_only": False,
            "quality": quality.classify(candles[-1].time if candles else None, now, "intraday", proxy=True), "proxy": True,
            "notes": ["Přepočet indexu z kotací měn, ne kotace futures DXY na ICE."], "instrument": None,
            "kind": "calculated", "kind_cs": "vypočtený index", "volume_note": None, "fetched_at": now}


TRA_CODES = {"XAUUSD": "XAUUSD", "DXY": "USD", "USD": "USD"}
TRA_FULL_DETAIL_HOURS = 48


@router.get("/instruments/{code}/tra-history")
def get_tra_history(code: str, days: int = 365, session: Session = Depends(get_session)):
    """Score history for the "Score history" chart. Long ranges come back as one point per day
    (the last one of the day) plus every point of the last two days."""
    inst = TRA_CODES.get(code.upper())
    if inst is None:
        raise HTTPException(status_code=404, detail="Historie skóre je jen pro XAUUSD a DXY.")
    days = max(1, min(days, 1500))
    now = dt.datetime.now(dt.timezone.utc)
    rows = list(session.scalars(
        select(TraScorePoint).where(TraScorePoint.instrument == inst, TraScorePoint.computed_at >= now - dt.timedelta(days=days))
        .order_by(TraScorePoint.computed_at)
    ))
    if days > 7:
        recent = now - dt.timedelta(hours=TRA_FULL_DETAIL_HOURS)
        per_day: dict[dt.date, TraScorePoint] = {}
        for r in rows:
            if r.computed_at < recent:
                per_day[r.computed_at.date()] = r
        rows = list(per_day.values()) + [r for r in rows if r.computed_at >= recent]
    return {
        "instrument": code.upper(),
        "points": [{"t": r.computed_at.isoformat(), "total": r.total, "source": r.source} for r in rows],
        "backfill_note": "Body „rekonstrukce“ jsou dopočítané zpětně z historických dat se zpožděním, s jakým data vycházejí; "
                         "body „živě“ ukládá aplikace průběžně.",
    }



def _latest_payload(session: Session) -> dict:
    instrument = session.scalar(select(Instrument).where(Instrument.code == "XAUUSD"))
    analysis = _latest_analysis(session, instrument.id) if instrument else None
    if analysis is None:
        raise HTTPException(status_code=404, detail="Přehled trhů se ještě počítá.")
    return {"computed_at": analysis.computed_at, **analysis.payload}


@router.get("/markets")
def get_markets(session: Session = Depends(get_session)):
    """The market overview: score −10…+10, bias, arguments, what to watch, retail — every instrument."""
    payload = _latest_payload(session)
    view = payload.get("markets")
    if not view:
        raise HTTPException(status_code=404, detail="Přehled trhů se ještě počítá.")
    return {**view, "market": payload.get("market"), "computed_at": payload["computed_at"]}


@router.get("/markets/{code}")
def get_market(code: str, session: Session = Depends(get_session)):
    payload = _latest_payload(session)
    card = next((m for m in (payload.get("markets") or {}).get("markets", []) if m["code"] == code.upper()), None)
    if card is None:
        raise HTTPException(status_code=404, detail="Tento trh v přehledu není.")
    return {**card, "computed_at": payload["computed_at"]}


@router.get("/regime")
def get_regime(code: str = "XAUUSD", session: Session = Depends(get_session)):
    """The market regime of gold (Ú2): trend × range, volatility, risk mood, dollar, real yields and the intermarket
    relationships — deterministic, every input with its source and time. Context, not a vote in the verdict."""
    if code.upper() != "XAUUSD":
        raise HTTPException(status_code=404, detail="Režim trhu je zatím jen pro XAU/USD.")
    payload = _latest_payload(session)
    rg = payload.get("regime")
    if not rg:
        raise HTTPException(status_code=404, detail="Režim trhu se ještě počítá — přijde s nejbližším výpočtem FTI.")
    return {**rg, "computed_at": payload["computed_at"]}


@router.get("/calendar")
def get_calendar(session: Session = Depends(get_session)):
    payload = _latest_payload(session)
    return {**(payload.get("calendar_all") or {"events": []}), "computed_at": payload["computed_at"]}
