"""Is the spot gold market open right now, and do our price sources agree?

Spot XAUUSD trades Sunday 18:00 – Friday 17:00 New York time with a daily
one-hour pause 17:00–18:00 (what OANDA/most brokers follow). Exchange
holidays are not modelled — the UI says "obvykle".
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
PRAGUE = ZoneInfo("Europe/Prague")
MAX_SOURCE_GAP_PCT = 0.5  # beyond this the price sources disagree → warn


def _state(ny: dt.datetime) -> str | None:
    wd, h = ny.weekday(), ny.hour  # Mon=0 … Sun=6
    if (wd == 4 and h >= 17) or wd == 5 or (wd == 6 and h < 18):
        return "víkend"
    if wd in (0, 1, 2, 3) and h == 17:
        return "denní pauza"
    return None


def status(now: dt.datetime) -> dict:
    ny = now.astimezone(NEW_YORK)
    reason = _state(ny)
    if reason is None:
        # next close: today 17:00 NY (Fri = weekly close)
        close = ny.replace(hour=17, minute=0, second=0, microsecond=0)
        if close <= ny:
            close += dt.timedelta(days=1)
        return {"open": True, "reason": None, "next_open": None, "closes_at": close.astimezone(dt.timezone.utc).isoformat(),
                "weekly_close": ny.weekday() == 4}
    t = ny.replace(minute=0, second=0, microsecond=0)
    while _state(t) is not None:
        t += dt.timedelta(hours=1)
    return {"open": False, "reason": reason, "next_open": t.astimezone(dt.timezone.utc).isoformat(), "closes_at": None,
            "weekly_close": False}


def price_check(paxg: float | None, bullionvault: float | None, xaut: float | None) -> dict:
    """How far apart the independent gold quotes are (PAXG is what the charts use)."""
    quotes = {k: v for k, v in (("PAXG (Kraken)", paxg), ("BullionVault (fyzické zlato, Londýn)", bullionvault),
                                 ("XAUT (Kraken)", xaut)) if v}
    if len(quotes) < 2 or not paxg:
        return {"quotes": quotes, "max_gap_pct": None, "ok": None,
                "text": "Cenu teď nelze porovnat s druhým zdrojem."}
    gaps = {k: round((v / paxg - 1) * 100, 2) for k, v in quotes.items()}
    worst = max(abs(g) for g in gaps.values())
    ok = worst <= MAX_SOURCE_GAP_PCT
    ref = bullionvault or xaut
    text = (f"Zdroje se shodují (největší rozdíl {worst:.2f} %).".replace(".", ",", 1) if ok else
            f"Pozor: zdroje se rozcházejí o {worst:.2f} % — cena PAXG teď nemusí přesně odpovídat spotu.".replace(".", ",", 1))
    return {"quotes": quotes, "gaps_pct": gaps, "max_gap_pct": worst, "ok": ok, "text": text,
            "paxg_vs_physical": round((paxg / ref - 1) * 100, 2) if ref else None}
