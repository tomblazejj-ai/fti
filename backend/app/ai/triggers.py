"""Event-driven AI: after each ingestion cycle FTI compares the new engine overview with the
previous one and asks AI only about what really changed.

  * BIAS of an instrument flipped              → explanation of the change, high priority
  * fundamental score moved by 2 points or more → explanation of the change
  * a new, clearly relevant news item (classifier relevance ≥ 0.5, not a duplicate) → news analysis, at most 2
  * twice a day, before London and before New York → briefing
  * XAU/USD complex analysis (LONG / SHORT / NO TRADE, several AI roles) when its data really changed: BIAS or
    score, the intraday or swing trend turned, the market regime changed (trend / volatility / risk mood / dollar),
    headline risk reached "high", or an important (3/3) calendar event
    was released — at most TRADE_PER_DAY a day (it costs 3 requests)

Off unless the user switches automatic analyses on (Settings → AI). At most MAX_PER_CYCLE requests
per cycle; the guard's daily cap, reserve and pauses apply on top.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select

from app.ai import facts as facts_mod
from app.ai import guard, tasks
from app.data import settings_store

log = logging.getLogger(__name__)
UTC = dt.timezone.utc
MAX_PER_CYCLE = 3
SCORE_STEP = 2
NEWS_MIN_RELEVANCE = 0.5
NEWS_PER_CYCLE = 2
REPORT_HOURS_UTC = (6, 12)  # 7:00 / 13:00 Prague winter time — before London and before New York
TRADE_PER_DAY = 6
TRADE_CODES = ("XAUUSD",)
TRADE_REFRESH_HOURS = 6  # with the market open, an analysis older than this is made again even without a change


def trade_reason(new: dict, old: dict, new_at: dt.datetime, old_at: dt.datetime) -> tuple[str, str] | None:
    """(priority, reason) when the complex analysis of gold should be made again, from two engine payloads."""
    def card(payload):
        return next((m for m in (payload.get("markets") or {}).get("markets", []) if m["code"] == "XAUUSD"), None)

    c_new, c_old = card(new), card(old)
    if c_new and c_old:
        hit = significant(c_new, c_old)
        if hit:
            return hit
    for key, label in (("intraday", "intradenní trend"), ("swing", "swingový trend")):
        a, b = ((old.get("mtf") or {}).get(key) or {}), ((new.get("mtf") or {}).get(key) or {})
        if a.get("direction") and b.get("direction") and a["direction"] != b["direction"]:
            return "normal", f"{label} {a.get('word')} → {b.get('word')}"
    from app.market import regime

    moved = regime.change(new.get("regime"), old.get("regime"))
    if moved:  # the kind of market changed (trend ↔ range, volatility class, risk mood, dollar)
        return "normal", "režim trhu: " + "; ".join(moved)
    if (new.get("headline_risk") or {}).get("level") == 2 and (old.get("headline_risk") or {}).get("level", 0) < 2:
        return "normal", "riziko titulků je vysoké"
    for e in (new.get("calendar") or {}).get("events", []):
        try:
            t = dt.datetime.fromisoformat(e["datetime"])
        except (KeyError, TypeError, ValueError):
            continue
        if (e.get("importance") or 0) >= 3 and old_at < t <= new_at:
            return "normal", f"zveřejněno: {e.get('name')}"
    return None


def significant(now_card: dict, before: dict) -> tuple[str, str] | None:
    """(priority, reason) when the change is worth an AI explanation, else None."""
    if now_card.get("bias") != before.get("bias"):
        return "high", f"BIAS {before.get('bias')} → {now_card.get('bias')}"
    if abs((now_card.get("score10") or 0) - (before.get("score10") or 0)) >= SCORE_STEP:
        return "normal", f"skóre {before.get('score10')} → {now_card.get('score10')}"
    return None


def _last_two(session) -> list:
    from app.models import AnalysisSnapshot, Instrument

    inst = session.scalar(select(Instrument).where(Instrument.code == "XAUUSD"))
    if inst is None:
        return []
    return list(session.scalars(select(AnalysisSnapshot).where(AnalysisSnapshot.instrument_id == inst.id)
                                .order_by(AnalysisSnapshot.computed_at.desc()).limit(2)))


def jobs(session, now: dt.datetime) -> list[dict]:
    from app.models import AnalysisRecord, NewsItem

    snaps = _last_two(session)
    out: list[dict] = []
    if len(snaps) == 2 and (snaps[0].payload or {}).get("markets") and (snaps[1].payload or {}).get("markets"):
        new, old = snaps
        before = {c["code"]: c for c in old.payload["markets"].get("markets", [])}
        for card in new.payload["markets"].get("markets", []):
            prev = before.get(card["code"])
            hit = significant(card, prev) if prev else None
            if hit:
                built = facts_mod.change(card, prev, new.computed_at.isoformat(), old.computed_at.isoformat())
                out.append({"task": "change", "code": card["code"], "priority": hit[0], "reason": f"automaticky: {hit[1]}",
                            "built": built})
        hit = trade_reason(new.payload, old.payload, new.computed_at, old.computed_at)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        made = session.query(AnalysisRecord).filter(AnalysisRecord.kind == "ai_trade", AnalysisRecord.created_at >= today).count()
        if not hit:
            last = session.query(AnalysisRecord).filter(AnalysisRecord.kind == "ai_trade").order_by(AnalysisRecord.created_at.desc()).first()
            last_at = last.created_at.replace(tzinfo=UTC) if last and last.created_at.tzinfo is None else (last.created_at if last else None)
            if last_at is None:
                hit = ("normal", "první analýza")  # none exists yet (a new cloud database): make one even with the market closed
            elif (new.payload.get("market") or {}).get("open") and now - last_at >= dt.timedelta(hours=TRADE_REFRESH_HOURS):
                hit = ("normal", "pravidelná aktualizace (trh otevřený)")
        if hit and made < TRADE_PER_DAY:
            out = [j for j in out if not (j["task"] == "change" and j.get("code") in TRADE_CODES)]  # the analysis explains it
            out.insert(0, {"task": "trade", "code": "XAUUSD", "priority": hit[0], "reason": f"automaticky: {hit[1]}"})
        since = old.computed_at
        items = session.scalars(select(NewsItem).where(NewsItem.fetched_at >= since, NewsItem.duplicate_of_id.is_(None),
                                                       NewsItem.relevance_score >= NEWS_MIN_RELEVANCE)
                                .order_by(NewsItem.relevance_score.desc()).limit(NEWS_PER_CYCLE))
        out += [{"task": "news", "item_id": n.id, "priority": "normal", "reason": "automaticky: důležitá zpráva"} for n in items]
    if now.hour in REPORT_HOURS_UTC:
        slot = now.replace(minute=0, second=0, microsecond=0)
        done = session.scalar(select(AnalysisRecord.id).where(AnalysisRecord.kind == "ai_report", AnalysisRecord.created_at >= slot))
        if not done:
            out.append({"task": "report", "priority": "normal", "reason": "automaticky: briefing"})
    out.sort(key=lambda j: 0 if j["priority"] == "high" else 1)
    return out


def after_cycle(session, now: dt.datetime | None = None) -> list[dict]:
    cfg = settings_store.get("ai", {}) or {}
    # any free provider the user switched on (Gemini first, Groq as backup, or Groq alone) — not only Groq (bug of 9. 11.)
    if cfg.get("provider") not in guard.FREE_PROVIDERS or not cfg.get("auto_analyses"):
        return []
    now = now or dt.datetime.now(UTC)
    results = []
    for job in jobs(session, now)[:MAX_PER_CYCLE]:
        r = tasks.run(session, job["task"], code=job.get("code"), item_id=job.get("item_id"), reason=job["reason"],
                      priority=job["priority"], built=job.get("built"), now=now)
        results.append({"task": job["task"], "code": job.get("code"), "status": r["status"]})
        if r["status"] == "unavailable":
            break  # paused or out of budget: the rest waits for the next cycle
    if results:
        log.info("AI po cyklu: %s", results)
    return results
