"""Headline risk: unexpected news that is NOT in the calendar —
political statements (tariff threats), war/attacks/sanctions, big bankruptcies, sudden
central-bank moves, crises. Reaction is instant and often exaggerated; liquidity disappears,
gaps and false breaks happen.

What the app can see without paid feeds:
  * matching headlines in the last hours of the news feed (keyword rules below)
  * an abnormal price candle (M15 range far above its usual size) — the market reacting
  * the approaching weekend close (weekend news can open the market with a gap)
"""

from __future__ import annotations

import datetime as dt
import re
import statistics
from zoneinfo import ZoneInfo

from app.connectors.kraken import Candle

NEW_YORK = ZoneInfo("America/New_York")
LOOKBACK_HOURS = 12
CLUSTER_HOURS = 3  # several matching headlines from different sources within 3 h = a developing story
SPIKE_FACTOR = 3.0  # last M15 range vs. median of the previous day

TOPICS: list[tuple[str, str]] = [
    (r"\btrade wars?\b|\bobchodní\w* válk|\btariffs?\b|\bcla\b|\bclo\b|\bclům\b|\bcly\b", "Cla a obchodní válka"),
    (r"\bsanction|\bsankc", "Sankce"),
    (r"\b(war|invasion|invades?|missiles?|airstrikes?|military strikes?)\b|\bválk|\binvaz|\braket|\bútok", "Válka / útok"),
    (r"\b(defaults?|bankrupt\w*|insolven\w*|bank run|bank failure|collapse[sd]?)\b|\bbankrot|\bkrach", "Bankrot / krize"),
    (r"\bemergency (rate|meeting|cut|hike)|\bmimořádn\w* (zasedání|snížení|zvýšení)", "Mimořádný krok centrální banky"),
    (r"\btrump\w*\b.{0,60}\b(tariff|threat\w*|warn\w*|sanction\w*|fire[sd]?|ban\w*|attack\w*|strikes?)\b", "Prohlášení Trumpa"),
    (r"\b(pandemic|outbreak|lockdown)\b|\bpandemi", "Pandemie"),
    (r"\bterror\w*|\bteror", "Terorismus"),
    (r"\b(coup|martial law)\b|\bpřevrat|\bstanné právo", "Převrat"),
    (r"\bdowngrade[sd]?\b|\bsnížil\w* rating", "Snížení ratingu"),
    (r"\bgovernment shutdown\b|\bshutdown\b", "Shutdown vlády"),
]
_COMPILED = [(re.compile(p, re.IGNORECASE), name) for p, name in TOPICS]


def classify(text: str) -> str | None:
    for rx, name in _COMPILED:
        if rx.search(text):
            return name
    return None


def _spike(m15: list[Candle]) -> dict | None:
    if len(m15) < 98:
        return None
    done = m15[:-1]  # the last candle is still forming
    ranges = [c.high - c.low for c in done[-97:-1]]
    usual = statistics.median(ranges) or 0.0
    last = done[-1]
    rng = last.high - last.low
    if usual and rng >= SPIKE_FACTOR * usual:
        return {"time": last.time.isoformat(), "range": round(rng, 2), "usual": round(usual, 2), "factor": round(rng / usual, 1),
                "direction": "up" if last.close >= last.open else "down"}
    return None


def build(headlines: list[dict], m15: list[Candle], market: dict, now: dt.datetime) -> dict:
    items = []
    seen: set[str] = set()
    cutoff = now - dt.timedelta(hours=LOOKBACK_HOURS)
    for h in headlines:
        try:
            t = dt.datetime.fromisoformat(h["published_at"])
        except (KeyError, ValueError):
            continue
        if t < cutoff:
            continue
        topic = classify(f"{h.get('title_en') or ''} {h.get('title') or ''}")
        key = re.sub(r"[^a-z0-9]+", "", (h.get("title_en") or h.get("title") or "").lower())[:60]
        if topic and key not in seen:
            seen.add(key)
            items.append({**{k: h.get(k) for k in ("title", "source", "url", "published_at", "translated")}, "topic": topic})
    items.sort(key=lambda x: x["published_at"], reverse=True)
    spike = _spike(m15) if market.get("open") else None

    weekend = None
    if market.get("open") and market.get("weekly_close") and market.get("closes_at"):
        closes = dt.datetime.fromisoformat(market["closes_at"])
        hours = (closes - now).total_seconds() / 3600
        if hours <= 6:
            weekend = {"closes_at": market["closes_at"], "hours": round(hours, 1),
                       "text": "Blíží se víkendové uzavření trhu — víkendové zprávy umí otevřít trh s gapem."}

    recent = [i for i in items if dt.datetime.fromisoformat(i["published_at"]) >= now - dt.timedelta(hours=CLUSTER_HOURS)]
    cluster = len(recent) >= 3 and len({i["source"] for i in recent}) >= 2
    level = 2 if spike or cluster else 1 if items or weekend else 0
    word = ["nízké", "zvýšené", "vysoké"][level]
    return {
        "level": level,
        "word": word,
        "items": items[:8],
        "spike": spike,
        "weekend": weekend,
        "hours": LOOKBACK_HOURS,
        "cluster": cluster,
        "note": ("Zprávy vybírá filtr podle klíčových slov — ne každá je skutečný šok. Vysoké riziko hlásíme jen při "
                 "neobvykle velké svíčce nebo když o stejném tématu píše víc zdrojů během 3 hodin."),
        "advice": [],
    }
