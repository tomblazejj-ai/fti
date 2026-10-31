"""US release dates (CPI, NFP, PPI, JOLTS, retail sales, jobless claims, GDP,
PCE) from FRED's public release calendar — no key, no account, no e-mail.

Page: https://fred.stlouisfed.org/releases/calendar?rid=<id>&y=<year>
Checked live 2026-10-02: robots.txt allows /releases/calendar for all agents
(Crawl-delay: 1, respected), and the page states "times are US Central Time".
FRED's firewall resets connections for unknown custom User-Agent strings, so
we send httpx's honest default ("python-httpx/…") like the FRED CSV connector
does — no browser disguise, no personal data.
BLS's own calendar is not used: it demands the user's e-mail, which the app
never sends. If FRED changes the page layout the parser finds nothing and the
calendar says the dates are unavailable — it never invents a date.

The schedule changes rarely, so it is fetched at most every 12 hours.
"""

from __future__ import annotations

import datetime as dt
import re
import threading
import time
from zoneinfo import ZoneInfo

import httpx

from app.connectors.calendar_ics import CalendarUnavailableError, IcsEvent

URL = "https://fred.stlouisfed.org/releases/calendar"
CENTRAL = ZoneInfo("America/Chicago")
SECONDS_BETWEEN_REQUESTS = 1.1
CACHE_HOURS = 12

# FRED release id -> what it is (key used by app/market/econ_calendar.py)
RELEASES: dict[int, str] = {
    10: "cpi",
    50: "nfp",
    46: "ppi",
    192: "jolts",
    9: "retail",
    180: "claims",
    53: "gdp",
    54: "pce",
}

_DATE_RE = re.compile(r'font-weight:\s*bold;">\s*[A-Za-z]+day\s+([A-Za-z]+ \d{1,2}, \d{4})\s*</span>')
_TIME_RE = re.compile(r"(\d{1,2}:\d{2}\s*[ap]m)", re.IGNORECASE)
_RELEASE_RE = re.compile(r'href="/release\?rid=(\d+)">([^<]+)</a>')

_cache: dict[str, object] = {"at": None, "events": []}
_lock = threading.Lock()


def parse(html: str) -> list[tuple[int, str, dt.datetime]]:
    """(rid, name, start UTC) for every release row on the page."""
    tokens = sorted(
        [(m.start(), "date", m) for m in _DATE_RE.finditer(html)]
        + [(m.start(), "time", m) for m in _TIME_RE.finditer(html)]
        + [(m.start(), "rel", m) for m in _RELEASE_RE.finditer(html)],
        key=lambda t: t[0],
    )
    out = []
    day: dt.date | None = None
    clock: dt.time | None = None
    for _, kind, m in tokens:
        if kind == "date":
            day = dt.datetime.strptime(m.group(1), "%B %d, %Y").date()
            clock = None
        elif kind == "time":
            clock = dt.datetime.strptime(m.group(1).replace(" ", "").lower(), "%I:%M%p").time()
        elif kind == "rel" and day is not None:
            local = dt.datetime.combine(day, clock or dt.time(0, 0), tzinfo=CENTRAL)
            out.append((int(m.group(1)), m.group(2).strip(), local.astimezone(dt.timezone.utc) if clock else
                        dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc)))
            clock = None
    return out


def fetch(now: dt.datetime, client: httpx.Client | None = None, sleep_fn=time.sleep) -> tuple[list[IcsEvent], list[str]]:
    with _lock:
        at = _cache["at"]
        if isinstance(at, dt.datetime) and now - at < dt.timedelta(hours=CACHE_HOURS) and _cache["events"]:
            return list(_cache["events"]), []  # type: ignore[arg-type]

    years = [now.year] + ([now.year + 1] if now.month >= 11 else [])
    owns = client is None
    client = client or httpx.Client(timeout=25.0)
    events: list[IcsEvent] = []
    failed: list[str] = []
    try:
        first = True
        for rid in RELEASES:
            for year in years:
                if not first:
                    sleep_fn(SECONDS_BETWEEN_REQUESTS)
                first = False
                try:
                    resp = client.get(URL, params={"rid": rid, "y": year})
                    resp.raise_for_status()
                    for got_rid, name, start in parse(resp.text):
                        if got_rid == rid:
                            events.append(IcsEvent(f"fred:{RELEASES[rid]}|{name}", start, "FRED"))
                except (httpx.HTTPError, ValueError) as exc:
                    failed.append(f"{rid}: {exc}")
    finally:
        if owns:
            client.close()

    notes = [f"Kalendář FRED částečně nedostupný ({len(failed)} dotazů selhalo)."] if failed else []
    if not events:
        raise CalendarUnavailableError("; ".join(failed) or "stránka neobsahuje žádné termíny (změnil se formát?)")
    with _lock:
        _cache["at"], _cache["events"] = now, list(events)
    return events, notes
