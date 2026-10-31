"""Rate-decision days of the four central banks behind our instruments.

Copied from the official calendars on 2026-10-31 (each says the dates may still move;
refresh the list when a new year is published — never guess future dates):
  * Fed  — federalreserve.gov/monetarypolicy/fomccalendars.htm (decision on day 2, 14:00 New York)
  * ECB  — ecb.europa.eu/press/calendars/mgcgc (monetary policy meetings, decision on day 2, 14:15 Frankfurt)
  * BoE  — bankofengland.co.uk/monetary-policy/upcoming-mpc-dates (12:00 London)
  * BoJ  — boj.or.jp/en/mopo/mpmsche_minu (decision on day 2, no fixed time — usually around noon Tokyo)
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

MEETINGS: dict[str, dict] = {
    "USD": {"bank": "Fed", "name": "Rozhodnutí Fedu o sazbách", "tz": "America/New_York", "time": (14, 0),
            "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            "dates": ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28",
                      "2026-12-09", "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15",
                      "2027-10-27", "2027-12-08"]},
    "EUR": {"bank": "ECB", "name": "Rozhodnutí ECB o sazbách", "tz": "Europe/Berlin", "time": (14, 15),
            "url": "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html",
            "dates": ["2026-10-29", "2026-12-17", "2027-02-04", "2027-03-18", "2027-04-29", "2027-06-10", "2027-07-22",
                      "2027-09-09", "2027-10-28", "2027-12-16"]},
    "GBP": {"bank": "BoE", "name": "Rozhodnutí Bank of England o sazbách", "tz": "Europe/London", "time": (12, 0),
            "url": "https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates",
            "dates": ["2026-09-17", "2026-11-05", "2026-12-17", "2027-02-04", "2027-03-18", "2027-04-29", "2027-06-17",
                      "2027-07-29", "2027-09-16", "2027-11-04", "2027-12-16"]},
    "JPY": {"bank": "BoJ", "name": "Rozhodnutí Bank of Japan o sazbách", "tz": "Asia/Tokyo", "time": None,
            "url": "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm",
            "dates": ["2026-10-30", "2026-12-18", "2027-01-22", "2027-03-18", "2027-04-28", "2027-06-11", "2027-07-22",
                      "2027-09-22", "2027-10-29"]},
}


def upcoming(currencies: set[str], now: dt.datetime, days: int = 45) -> list[dict]:
    """Decision days in the next `days` days, as calendar events."""
    out = []
    for cur, m in MEETINGS.items():
        if cur not in currencies:
            continue
        tz = ZoneInfo(m["tz"])
        for d in m["dates"]:
            day = dt.date.fromisoformat(d)
            if m["time"]:
                start = dt.datetime.combine(day, dt.time(*m["time"]), tz).astimezone(dt.timezone.utc)
            else:
                start = dt.datetime.combine(day, dt.time(12, 0), tz).astimezone(dt.timezone.utc)
            if now - dt.timedelta(hours=2) <= start <= now + dt.timedelta(days=days):
                out.append({"datetime": start.isoformat(), "timed": bool(m["time"]), "currency": cur, "title_cs": m["name"],
                            "title_en": f"{m['bank']} rate decision", "impact": 3, "forecast": None, "previous": None,
                            "source": f"{m['bank']} (oficiální kalendář)", "url": m["url"]})
    return out
