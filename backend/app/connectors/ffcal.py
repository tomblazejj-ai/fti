"""Economic calendar for all major currencies — the ForexFactory calendar export.

ForexFactory offers "This week" exports of its calendar (XML/CSV/JSON) on the calendar
page; the JSON lives at nfs.faireconomy.media (robots.txt allows everything, checked
2026-10-31). Each event has the currency, the time (New York, with offset), the impact
(High / Medium / Low / Holiday) and — unlike the official US calendars — the market
consensus ("forecast") and the previous value. Only the CURRENT week (Sun–Sat) exists;
there is no "next week" file, so later weeks come from app/market/central_banks.py and
the US release calendars.

Fetched at most once an hour (their CDN caches 60 s; we stay far below that). Every
event seen is kept in backend/cache/ff_events.json for 60 days, so the history of
values builds up over time.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
from pathlib import Path

import httpx

from app.config import BACKEND_DIR

URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CACHE_FILE = BACKEND_DIR / "cache" / "ff_events.json"
REFRESH_MINUTES = 60
KEEP_DAYS = 60
IMPACT = {"High": 3, "Medium": 2, "Low": 1, "Holiday": 0}
CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CAD", "AUD", "NZD", "CHF", "CNY"}

_lock = threading.Lock()
_mem: dict[str, object] = {"at": None, "events": None}


class CalendarFeedUnavailableError(RuntimeError):
    pass


# The usual release names in Czech; anything else goes through the local translator.
CZ_NAMES: list[tuple[str, str]] = [
    (r"^Federal Funds Rate$", "Sazba Fedu (rozhodnutí FOMC)"),
    (r"^FOMC Statement$", "Prohlášení FOMC"),
    (r"^FOMC Press Conference$", "Tisková konference Fedu"),
    (r"^FOMC Meeting Minutes$", "Zápis z jednání FOMC"),
    (r"^Main Refinancing Rate$", "Sazba ECB"),
    (r"^ECB Press Conference$", "Tisková konference ECB"),
    (r"^Official Bank Rate$", "Sazba Bank of England"),
    (r"^BOJ Policy Rate$", "Sazba Bank of Japan"),
    (r"^BOJ Press Conference$", "Tisková konference BoJ"),
    (r"^BOJ Outlook Report$", "Výhled BoJ"),
    (r"^Monetary Policy Statement$", "Měnověpolitické prohlášení"),
    (r"^Monetary Policy Summary$", "Shrnutí měnové politiky"),
    (r"^Non-Farm Employment Change$", "Nová pracovní místa NFP"),
    (r"^ADP Non-Farm Employment Change$", "Zaměstnanost ADP"),
    (r"^Unemployment Rate$", "Nezaměstnanost"),
    (r"^Unemployment Claims$", "Žádosti o podporu v nezaměstnanosti"),
    (r"^Claimant Count Change$", "Žádosti o podporu (UK)"),
    (r"^Average Hourly Earnings m/m$", "Hodinové mzdy m/m"),
    (r"^Average Earnings Index 3m/y$", "Mzdy 3m/r (UK)"),
    (r"^JOLTS Job Openings$", "Volná pracovní místa JOLTS"),
    (r"^Core PCE Price Index m/m$", "Jádrová inflace PCE m/m"),
    (r"^Core CPI m/m$", "Jádrová inflace CPI m/m"),
    (r"^Core CPI y/y$", "Jádrová inflace CPI r/r"),
    (r"^CPI m/m$", "Inflace CPI m/m"),
    (r"^CPI y/y$", "Inflace CPI r/r"),
    (r"^CPI Flash Estimate y/y$", "Předběžná inflace r/r"),
    (r"^Core CPI Flash Estimate y/y$", "Předběžná jádrová inflace r/r"),
    (r"^Tokyo Core CPI y/y$", "Jádrová inflace Tokio r/r"),
    (r"^National Core CPI y/y$", "Jádrová inflace Japonsko r/r"),
    (r"^German Prelim CPI m/m$", "Předběžná inflace Německo m/m"),
    (r"^PPI m/m$", "Ceny výrobců PPI m/m"),
    (r"^Core PPI m/m$", "Jádrové ceny výrobců m/m"),
    (r"^Advance GDP q/q$", "HDP – první odhad q/q"),
    (r"^Prelim GDP q/q$", "HDP – předběžný q/q"),
    (r"^Flash GDP q/q$", "HDP – rychlý odhad q/q"),
    (r"^GDP q/q$", "HDP q/q"),
    (r"^GDP m/m$", "HDP m/m"),
    (r"^Final GDP q/q$", "HDP – finální q/q"),
    (r"^Retail Sales m/m$", "Maloobchodní tržby m/m"),
    (r"^Core Retail Sales m/m$", "Jádrové maloobchodní tržby m/m"),
    (r"^ISM Manufacturing PMI$", "ISM PMI průmysl"),
    (r"^ISM Services PMI$", "ISM PMI služby"),
    (r"^Flash Manufacturing PMI$", "Předběžné PMI průmysl"),
    (r"^Flash Services PMI$", "Předběžné PMI služby"),
    (r"^Manufacturing PMI$", "PMI průmysl"),
    (r"^Services PMI$", "PMI služby"),
    (r"^CB Consumer Confidence$", "Spotřebitelská důvěra (CB)"),
    (r"^Prelim UoM Consumer Sentiment$", "Spotřebitelský sentiment Michigan"),
    (r"^Crude Oil Inventories$", "Zásoby ropy (EIA)"),
    (r"^Trade Balance$", "Obchodní bilance"),
    (r"^Bank Holiday$", "Svátek — trh zavřený"),
    (r"^German ifo Business Climate$", "Index ifo (Německo)"),
    (r"^German ZEW Economic Sentiment$", "ZEW sentiment (Německo)"),
    (r"^Annual Budget Release$", "Rozpočet vlády"),
    (r"^Tankan Manufacturing Index$", "Tankan průmysl"),
]
_CZ = [(re.compile(p), cz) for p, cz in CZ_NAMES]
_SPEAKS = re.compile(r"^(.*) Speaks$")


BASE_CZ = {
    "CPI": "Inflace CPI", "Core CPI": "Jádrová inflace CPI", "PPI": "Ceny výrobců PPI", "Core PPI": "Jádrové ceny výrobců",
    "GDP": "HDP", "Retail Sales": "Maloobchodní tržby", "Core Retail Sales": "Jádrové maloobchodní tržby",
    "Unemployment Rate": "Nezaměstnanost", "Unemployment Change": "Změna nezaměstnanosti", "Employment Change": "Změna zaměstnanosti",
    "Industrial Production": "Průmyslová výroba", "Housing Starts": "Zahájené stavby domů", "Building Permits": "Stavební povolení",
    "Building Approvals": "Stavební povolení", "Trade Balance": "Obchodní bilance", "Current Account": "Běžný účet",
    "Consumer Confidence": "Spotřebitelská důvěra", "Business Confidence": "Podniková důvěra", "Manufacturing PMI": "PMI průmysl",
    "Services PMI": "PMI služby", "Non-Manufacturing PMI": "PMI mimo průmysl", "Chicago PMI": "PMI Chicago",
    "Composite PMI": "Souhrnné PMI", "Consumer Spending": "Spotřebitelské výdaje", "Import Prices": "Dovozní ceny",
    "Export Prices": "Vývozní ceny", "Pending Home Sales": "Rozjednané prodeje domů", "Existing Home Sales": "Prodeje starších domů",
    "New Home Sales": "Prodeje nových domů", "Durable Goods Orders": "Objednávky zboží dlouhodobé spotřeby",
    "Core Durable Goods Orders": "Jádrové objednávky zboží dl. spotřeby", "Factory Orders": "Tovární objednávky",
    "Personal Spending": "Osobní výdaje", "Personal Income": "Osobní příjmy", "Employment Cost Index": "Náklady práce ECI",
    "Empire State Manufacturing Index": "Empire State (průmysl New York)", "Philly Fed Manufacturing Index": "Philly Fed (průmysl)",
    "Wage Price Index": "Index mezd", "Average Earnings Index": "Index mezd", "Claimant Count Change": "Žádosti o podporu",
    "Money Supply": "Peněžní zásoba", "M3 Money Supply": "Peněžní zásoba M3", "Private Loans": "Úvěry soukromému sektoru",
    "Spending": "Výdaje", "Prelim Industrial Production": "Průmyslová výroba (předběžně)", "Household Spending": "Výdaje domácností",
    "Consumer Inflation Expectations": "Inflační očekávání spotřebitelů", "Inflation Expectations": "Inflační očekávání",
    "Natural Gas Storage": "Zásoby zemního plynu", "Crude Oil Inventories": "Zásoby ropy (EIA)",
    "ADP Non-Farm Employment Change": "Zaměstnanost ADP", "Non-Farm Employment Change": "Nová pracovní místa NFP",
    "Revised UoM Consumer Sentiment": "Spotřebitelský sentiment Michigan (revize)", "Final Manufacturing PMI": "PMI průmysl (finální)",
    "Final Services PMI": "PMI služby (finální)", "Flash Manufacturing PMI": "PMI průmysl (předběžně)",
    "Flash Services PMI": "PMI služby (předběžně)", "JOLTS Job Openings": "Volná pracovní místa JOLTS",
}
PREFIX_CZ = {"German": "Německo", "French": "Francie", "Italian": "Itálie", "Spanish": "Španělsko", "Tokyo": "Tokio",
             "National": "Japonsko", "Prelim": "předběžně", "Flash": "rychlý odhad", "Final": "finální", "Revised": "revize",
             "Advance": "první odhad"}
SUFFIX_CZ = {"y/y": "r/r", "m/m": "m/m", "q/q": "q/q", "3m/y": "3m/r", "w/w": "t/t"}


def _compose(title: str) -> str | None:
    words = title.split()
    suffix = SUFFIX_CZ.get(words[-1]) if words else None
    if suffix:
        words = words[:-1]
    notes = []
    while words and words[0] in PREFIX_CZ:
        notes.append(PREFIX_CZ[words.pop(0)])
    base = BASE_CZ.get(" ".join(words))
    if not base:
        return None
    return f"{base}{' ' + suffix if suffix else ''}{' (' + ', '.join(notes) + ')' if notes else ''}"


def czech_title(title: str) -> str | None:
    for rx, cz in _CZ:
        if rx.search(title):
            return cz
    m = _SPEAKS.match(title)
    if m:
        return f"Projev: {m.group(1)}"
    return _compose(title)


def parse(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        try:
            t = dt.datetime.fromisoformat(r["date"])
        except (KeyError, ValueError):
            continue
        cur = (r.get("country") or "").upper()
        if cur not in CURRENCIES:
            continue
        out.append({
            "datetime": t.astimezone(dt.timezone.utc).isoformat(),
            "currency": cur,
            "title_en": r.get("title", "").strip(),
            "impact": IMPACT.get(r.get("impact", ""), 1),
            "forecast": (r.get("forecast") or "").strip() or None,
            "previous": (r.get("previous") or "").strip() or None,
            "source": "ForexFactory",
        })
    return out


def _load(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("events", [])
    except (OSError, ValueError, AttributeError):
        return []


def fetch_week(now: dt.datetime, client: httpx.Client | None = None, cache_file: Path = CACHE_FILE) -> list[dict]:
    """Events of this week plus everything kept from the last 60 days, oldest first."""
    with _lock:
        at, events = _mem["at"], _mem["events"]
        if isinstance(at, dt.datetime) and events is not None and now - at < dt.timedelta(minutes=REFRESH_MINUTES):
            return events  # type: ignore[return-value]
    kept = {(e["datetime"], e["currency"], e["title_en"]): e for e in _load(cache_file)}
    owns = client is None
    client = client or httpx.Client(timeout=30.0, headers={"User-Agent": "Mozilla/5.0 (compatible; fundamental-trading-intelligence/0.8)"})
    error = None
    try:
        resp = client.get(URL)
        resp.raise_for_status()
        fresh = parse(resp.json())
        for e in fresh:
            kept[(e["datetime"], e["currency"], e["title_en"])] = e
    except (httpx.HTTPError, ValueError) as exc:
        error = exc
    finally:
        if owns:
            client.close()
    if error and not kept:
        raise CalendarFeedUnavailableError(f"Kalendář ForexFactory nedostupný: {error}")
    cutoff = (now - dt.timedelta(days=KEEP_DAYS)).isoformat()
    events = sorted((e for e in kept.values() if e["datetime"] >= cutoff), key=lambda e: e["datetime"])
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"source": URL, "events": events}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    with _lock:
        _mem["at"], _mem["events"] = (now if not error else now - dt.timedelta(minutes=REFRESH_MINUTES - 10)), events
    return events
