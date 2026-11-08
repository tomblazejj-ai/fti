"""Intermarket context for gold: the markets that usually move with or against it, from FRED (official, free).

For each series: the last value with its date, the change over 5 and 20 observations, and the correlation of
daily changes with XAUUSD over the last 60 common days. A correlation describes how the two moved together —
it is never presented as a cause. A series older than STALE_DAYS is marked stale, not dropped.

The dollar (DXY) has its own block (app/market/dxy.py) and is not repeated here.
"""

from __future__ import annotations

import datetime as dt
import statistics

# (FRED id, label, unit, change in: "abs" = points / percentage points, "pct" = %)
SERIES: list[tuple[str, str, str, str]] = [
    ("VIXCLS", "VIX — volatilita akcií S&P 500 (CBOE)", "body", "abs"),
    ("DGS10", "Výnos 10letých amerických dluhopisů (Treasury)", "%", "abs"),
    ("DFII10", "Reálný výnos 10 let (TIPS)", "%", "abs"),
    ("DCOILWTICO", "Ropa WTI", "$/barel", "pct"),
    ("SP500", "Akciový index S&P 500", "body", "pct"),
]
SERIES_IDS = [s[0] for s in SERIES]
CORR_DAYS = 60
MIN_COMMON = 40
STALE_DAYS = 5


def _changes(closes: dict[str, float]) -> dict[str, float]:
    days = sorted(closes)
    return {d: closes[d] - closes[p] for p, d in zip(days, days[1:])}


def correlation(a: dict[str, float], b: dict[str, float], days: int = CORR_DAYS) -> tuple[float | None, int]:
    """Pearson correlation of daily changes on common dates (last `days`), with the number of days used."""
    ca, cb = _changes(a), _changes(b)
    common = sorted(set(ca) & set(cb))[-days:]
    if len(common) < MIN_COMMON:
        return None, len(common)
    xa, xb = [ca[d] for d in common], [cb[d] for d in common]
    if statistics.pstdev(xa) == 0 or statistics.pstdev(xb) == 0:
        return None, len(common)
    return round(statistics.correlation(xa, xb), 2), len(common)


def _word(r: float | None) -> str:
    if r is None:
        return "nelze spočítat"
    size = "silná" if abs(r) >= 0.6 else "střední" if abs(r) >= 0.3 else "slabá" if abs(r) >= 0.15 else "téměř žádná"
    return size if size == "téměř žádná" else f"{size} {'souběžná' if r > 0 else 'opačná'}"


def build(series: dict[str, dict[str, float]], gold_daily: dict[str, float], now: dt.datetime) -> dict:
    """{items: [...], missing: [...]} — gold_daily = XAUUSD daily closes by ISO date."""
    items, missing = [], []
    for sid, label, unit, mode in SERIES:
        obs = {d: v for d, v in (series.get(sid) or {}).items() if v is not None}
        if len(obs) < 2:
            missing.append(f"{label} ({sid})")
            continue
        days = sorted(obs)
        last, as_of = obs[days[-1]], days[-1]

        def change(n: int) -> float | None:
            if len(days) <= n:
                return None
            prev = obs[days[-1 - n]]
            if mode == "pct":
                return round((last / prev - 1) * 100, 2) if prev else None
            return round(last - prev, 2)

        r, n = correlation(obs, gold_daily)
        age = (now.date() - dt.date.fromisoformat(as_of)).days
        items.append({"id": sid, "label": label, "unit": unit, "last": round(last, 2), "as_of": as_of,
                      "change_5": change(5), "change_20": change(20),
                      "change_unit": "%" if mode == "pct" else "p. b." if unit == "%" else unit,
                      "corr_gold": r, "corr_days": n, "corr_word": _word(r), "stale": age > STALE_DAYS, "age_days": age,
                      "source": f"FRED {sid}"})
    return {"items": items, "missing": missing, "corr_days": CORR_DAYS,
            "note": "Korelace denních změn se zlatem za posledních 60 společných dní — popisuje souběh pohybů, ne příčinu."}
