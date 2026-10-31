"""Official US release calendars (ICS) — the fundamental calendar for gold.

Sources, all public, no account, no key (checked live 2026-10-02):
  - BEA  https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics
         GDP, Personal Income and Outlays (= PCE inflation). Times in UTC.
  - BLS is NOT used: bls.gov answers 403 unless the request carries the
         user's contact e-mail, and the user decided (2026-10-02) that their
         e-mail is never sent anywhere. Do not add an e-mail option back.
         CPI/NFP/PPI/JOLTS dates come from FRED instead (fred_calendar.py).
  - FOMC dates are in app/scoring/xauusd.py (verified from federalreserve.gov).

What is NOT available for free: consensus forecasts. The calendar shows the
previous value (from FRED) and says the forecast is unavailable — never a guess.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import httpx

BEA_URL = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
BASE_UA = "fundamental-trading-intelligence/0.6 (personal economic calendar)"

TZ_ALIASES = {"US-Eastern": "America/New_York", "America/New_York": "America/New_York"}


class CalendarUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class IcsEvent:
    summary: str
    start: dt.datetime  # UTC
    source: str


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _parse_dt(prop: str, value: str, default_tz: str | None) -> dt.datetime | None:
    params = dict(p.split("=", 1) for p in prop.split(";")[1:] if "=" in p)
    value = value.strip()
    try:
        if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
            d = dt.datetime.strptime(value[:8], "%Y%m%d")
            return d.replace(tzinfo=dt.timezone.utc)
        if value.endswith("Z"):
            return dt.datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
        local = dt.datetime.strptime(value, "%Y%m%dT%H%M%S")
        tz = TZ_ALIASES.get(params.get("TZID", "") or (default_tz or ""), None)
        if tz is None:
            return None  # unknown zone: better to drop than to shift a release time
        return local.replace(tzinfo=ZoneInfo(tz)).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def parse_ics(text: str, source: str) -> list[IcsEvent]:
    lines = _unfold(text)
    default_tz = next((ln.split(":", 1)[1].strip() for ln in lines if ln.startswith(("X-WR-TIMEZONE:", "TZID:"))), None)
    events: list[IcsEvent] = []
    cur: dict[str, str] = {}
    in_event = False
    for ln in lines:
        if ln == "BEGIN:VEVENT":
            in_event, cur = True, {}
        elif ln == "END:VEVENT":
            in_event = False
            start = None
            for prop, value in cur.items():
                if prop.split(";")[0] == "DTSTART":
                    start = _parse_dt(prop, value, default_tz)
            summary = cur.get("SUMMARY", "").replace("\\,", ",").replace("\\;", ";").strip()
            if start and summary:
                events.append(IcsEvent(summary, start, source))
        elif in_event and ":" in ln:
            prop, value = ln.split(":", 1)
            key = prop if prop.startswith("DTSTART") else prop.split(";")[0]
            cur[key] = value
    return events


def _get(url: str, ua: str, client: httpx.Client | None) -> str:
    owns = client is None
    client = client or httpx.Client(timeout=25.0)
    try:
        resp = client.get(url, headers={"User-Agent": ua})
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError as exc:
        raise CalendarUnavailableError(str(exc)) from exc
    finally:
        if owns:
            client.close()


def fetch_all(client: httpx.Client | None = None) -> tuple[list[IcsEvent], list[str]]:
    events: list[IcsEvent] = []
    notes: list[str] = []
    try:
        events += parse_ics(_get(BEA_URL, BASE_UA, client), "BEA")
    except CalendarUnavailableError as exc:
        notes.append(f"Kalendář BEA (HDP, PCE) nedostupný: {exc}")
    return events, notes
