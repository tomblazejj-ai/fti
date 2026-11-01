"""Data-quality label of every value the app shows.

LIVE           real-time price from the source (an exchange quote, not a delayed copy)
NEAR_REAL_TIME a few minutes old at most (news feeds, a calendar refreshed hourly)
DELAYED        published with a known delay (daily closes, official daily series)
HISTORICAL     periodic statistics (weekly COT, monthly CPI, quarterly GDP) inside their normal rhythm
STALE          older than the source's normal rhythm allows: the source failed or stopped
UNAVAILABLE    no data at all
PROXY          a stand-in for the real instrument (PAXG token for gold, a crypto exchange's FX quote)

The rule: a value is never shown as LIVE unless it is a live quote, and an old value is never
shown as current — it is STALE with its real date.
"""

from __future__ import annotations

import datetime as dt

LIVE, NRT, DELAYED, HISTORICAL, STALE, UNAVAILABLE, PROXY = (
    "LIVE", "NEAR_REAL_TIME", "DELAYED", "HISTORICAL", "STALE", "UNAVAILABLE", "PROXY")

LABELS_CS = {
    LIVE: "živě",
    NRT: "téměř živě",
    DELAYED: "se zpožděním",
    HISTORICAL: "historická data",
    STALE: "zastaralé",
    UNAVAILABLE: "nedostupné",
    PROXY: "náhrada (proxy)",
}

# rhythm -> (max age for the "fresh" label, max age before STALE, fresh label)
RHYTHMS: dict[str, tuple[dt.timedelta, dt.timedelta, str]] = {
    "tick": (dt.timedelta(minutes=3), dt.timedelta(minutes=30), LIVE),
    "intraday": (dt.timedelta(minutes=20), dt.timedelta(hours=3), NRT),
    "hourly": (dt.timedelta(hours=2), dt.timedelta(hours=8), NRT),
    "daily": (dt.timedelta(days=4), dt.timedelta(days=7), DELAYED),
    "weekly": (dt.timedelta(days=10), dt.timedelta(days=20), HISTORICAL),
    "monthly": (dt.timedelta(days=75), dt.timedelta(days=120), HISTORICAL),
    "quarterly": (dt.timedelta(days=160), dt.timedelta(days=230), HISTORICAL),
}


def parse_time(value) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day, tzinfo=dt.timezone.utc)
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, dt.timezone.utc)
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def classify(as_of, now: dt.datetime, rhythm: str, *, proxy: bool = False, market_open: bool = True) -> dict:
    """{status, label, as_of, age_hours, text} for one value."""
    t = parse_time(as_of)
    if t is None:
        return {"status": UNAVAILABLE, "label": LABELS_CS[UNAVAILABLE], "as_of": None, "age_hours": None,
                "text": "Data nejsou k dispozici."}
    fresh, stale_after, fresh_label = RHYTHMS[rhythm]
    age = now - t
    if not market_open and rhythm in ("tick", "intraday"):
        # a closed market: the last price is the close, not a live quote, but not "broken" either
        stale_after = max(stale_after, dt.timedelta(days=3))
        fresh_label = DELAYED if age > fresh else fresh_label
    if age > stale_after:
        status = STALE
    elif age <= fresh:
        status = fresh_label
    else:
        status = DELAYED if rhythm in ("tick", "intraday", "hourly") else fresh_label
    if proxy and status != STALE:
        status_shown = PROXY
    else:
        status_shown = status
    hours = round(age.total_seconds() / 3600, 1)
    text = {
        STALE: f"Data jsou starší, než je u zdroje obvyklé (stáří {_age_cs(age)}).",
        LIVE: "Živá kotace.",
        NRT: f"Aktualizováno před {_age_cs(age)}.",
        DELAYED: f"Data se zpožděním {_age_cs(age)}.",
        HISTORICAL: f"Poslední zveřejněná hodnota (stáří {_age_cs(age)}).",
    }.get(status, "")
    if proxy:
        text = "Náhradní instrument (proxy), ne skutečný trh. " + text
    return {"status": status_shown, "freshness": status, "label": LABELS_CS[status_shown], "as_of": t.isoformat(),
            "age_hours": hours, "text": text}


def _age_cs(age: dt.timedelta) -> str:
    mins = int(age.total_seconds() // 60)
    if mins < 60:
        return f"{max(mins, 0)} min"
    if mins < 48 * 60:
        return f"{mins // 60} h"
    return f"{mins // 1440} dní"


def worst(statuses: list[str]) -> str:
    """The weakest label of several inputs (for a factor built from more data)."""
    order = [UNAVAILABLE, STALE, PROXY, HISTORICAL, DELAYED, NRT, LIVE]
    present = [s for s in statuses if s]
    if not present:
        return UNAVAILABLE
    return min(present, key=lambda s: order.index(s) if s in order else 0)


def reliability(status: str) -> float:
    """Weight multiplier for the score: stale data counts less, unavailable not at all."""
    return {LIVE: 1.0, NRT: 1.0, DELAYED: 0.95, HISTORICAL: 0.9, PROXY: 0.85, STALE: 0.5, UNAVAILABLE: 0.0}.get(status, 0.0)
