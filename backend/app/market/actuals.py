"""Actual values of released calendar events from OFFICIAL data (user's rule 2026-11-08: Forex Factory stays the main
calendar; its free export has forecast and previous but no actual, so FTI adds the actual from the publisher's data).

Source: ALFRED/FRED API of the Federal Reserve Bank of St. Louis (free key, already used by FTI) with the value AS IT WAS
PUBLISHED ON THE RELEASE DAY (vintage = the release date in New York), so a later revision never rewrites the actual.
The publishers are the US statistical agencies (BLS, BEA, Census, Department of Labor). Verified live 8. 11. 2026:
  * the vintage of the release day exists in FRED the same day (PAYEMS, UNRATE, CES0500000003 on 6. 11., ICSA on 5. 11.,
    JTSJOL on 3. 11.) and equals BLS's own API to the last digit (NFP 159 293 / 159 128, AHE 38.00 / 37.86, JOLTS 7 523);
  * FTI's arithmetic gives FF's own "previous" of the next release: CPI m/m 0.6 %, core 0.3 %, PPI 1.3 %, core PPI 0.7 %
    (series PPIFES — PPICOR would give 0.6 %), claims 189K.
No actual is ever guessed: before FRED has the release day's vintage the event says "čeká na oficiální data".
Events without a free official source (ISM, University of Michigan, private surveys) get no actual and say why.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import httpx

from app.data import secrets

API = "https://api.stlouisfed.org/fred/series/observations"
VINTAGES_API = "https://api.stlouisfed.org/fred/series/vintagedates"
BLS_API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"  # the publisher itself, keyless (25 queries a day)
RECORD_VERSION = 2
BLS_RETRY_S = 6 * 3600
_bls_failed: dict[str, float] = {}
# FRED id -> BLS id (the same statistic straight from the publisher)
BLS_IDS = {"PAYEMS": "CES0000000001", "UNRATE": "LNS14000000", "CES0500000003": "CES0500000003",
           "JTSJOL": "JTS000000000000000JOL", "PRS85006092": "PRS85006092", "PRS85006112": "PRS85006112",
           "CPIAUCSL": "CUSR0000SA0", "CPILFESL": "CUSR0000SA0L1E", "CPIAUCNS": "CUUR0000SA0", "CPILFENS": "CUUR0000SA0L1E",
           "PPIFIS": "WPSFD4", "PPIFES": "WPSFD49104"}
PUBLISHERS = {"BLS": "U.S. Bureau of Labor Statistics (ministerstvo práce USA)",
              "Department of Labor": "U.S. Department of Labor, Employment and Training Administration",
              "Census/BEA": "U.S. Census Bureau a Bureau of Economic Analysis (ministerstvo obchodu USA)",
              "Census": "U.S. Census Bureau (ministerstvo obchodu USA)", "BEA": "U.S. Bureau of Economic Analysis"}
NOT_AT_PUBLISHER = {"Department of Labor": "dol.gov automatický přístup odmítá (HTTP 403)",
                    "Census/BEA": "Census zveřejňuje zprávu jen jako PDF, BEA API vyžaduje registraci",
                    "Census": "Census zveřejňuje zprávu jen jako PDF", "BEA": "BEA API vyžaduje registraci"}
VIA = "ALFRED/FRED — Federal Reserve Bank of St. Louis (institucionální zprostředkovatel, stav dat ke dni vydání)"
SECONDARY = "Forex Factory — sekundární kalendář (čas, prognóza, původní „minule“)"
NY = ZoneInfo("America/New_York")
WAIT_AFTER_RELEASE = dt.timedelta(minutes=10)  # FRED loads a release within minutes to hours; earlier asks are wasted
LOOKBACK = dt.timedelta(days=14)  # released events this old still get their actual filled in
MAX_REQUESTS_PER_RUN = 12  # FRED allows 120 a minute; FTI asks only for events still missing an actual
_transport: httpx.BaseTransport | None = None  # tests inject a mock
_lock = threading.Lock()
_pending: dict[str, float] = {}  # event key -> monotonic time of the last "not yet in FRED" answer
PENDING_RETRY_S = 20 * 60


@dataclass(frozen=True)
class Spec:
    series: str
    how: str  # level | diff_k | mom | yoy | thousands | millions | billions
    publisher: str
    digits: int = 1
    yoy_series: str | None = None


# Forex Factory title (USD) -> official series. Only mappings verified against FF's own numbers are listed.
SPECS: dict[str, Spec] = {
    "Non-Farm Employment Change": Spec("PAYEMS", "diff_k", "BLS", 0),
    "Unemployment Rate": Spec("UNRATE", "level", "BLS", 1),
    "Average Hourly Earnings m/m": Spec("CES0500000003", "mom", "BLS", 1),
    "Unemployment Claims": Spec("ICSA", "thousands", "Department of Labor", 0),
    "JOLTS Job Openings": Spec("JTSJOL", "millions", "BLS", 2),
    "CPI m/m": Spec("CPIAUCSL", "mom", "BLS", 1),
    "Core CPI m/m": Spec("CPILFESL", "mom", "BLS", 1),
    "CPI y/y": Spec("CPIAUCNS", "yoy", "BLS", 1),
    "Core CPI y/y": Spec("CPILFENS", "yoy", "BLS", 1),
    "PPI m/m": Spec("PPIFIS", "mom", "BLS", 1),
    "Core PPI m/m": Spec("PPIFES", "mom", "BLS", 1),
    "Retail Sales m/m": Spec("RSAFS", "mom", "Census", 1),
    "Core Retail Sales m/m": Spec("RSFSXMV", "mom", "Census", 1),
    "Advance GDP q/q": Spec("A191RL1Q225SBEA", "level", "BEA", 1),
    "Prelim GDP q/q": Spec("A191RL1Q225SBEA", "level", "BEA", 1),
    "Final GDP q/q": Spec("A191RL1Q225SBEA", "level", "BEA", 1),
    "Core PCE Price Index m/m": Spec("PCEPILFE", "mom", "BEA", 1),
    "Trade Balance": Spec("BOPGSTB", "billions", "Census/BEA", 1),
    "Prelim Nonfarm Productivity q/q": Spec("PRS85006092", "level", "BLS", 1),
    "Prelim Unit Labor Costs q/q": Spec("PRS85006112", "level", "BLS", 1),
}
NO_OFFICIAL = {  # FF titles with no free official source — said plainly instead of an empty field
    "ISM Manufacturing PMI": "ISM (soukromá organizace, data nejsou volně ve strojové podobě)",
    "ISM Services PMI": "ISM (soukromá organizace, data nejsou volně ve strojové podobě)",
    "ISM Manufacturing Prices": "ISM (soukromá organizace)",
    "Prelim UoM Consumer Sentiment": "University of Michigan (předběžná data jen na jejich webu, FRED je má až se zpožděním)",
    "Prelim UoM Inflation Expectations": "University of Michigan (předběžná data jen na jejich webu)",
    "ADP Non-Farm Employment Change": "ADP (soukromá firma)",
}


class ActualUnavailable(RuntimeError):
    pass


def key_of(event: dict) -> str:
    return f"actual:{event['title_en']}:{event['datetime'][:16]}"


def release_day(event: dict) -> str:
    return dt.datetime.fromisoformat(event["datetime"]).astimezone(NY).date().isoformat()


def _vintage(series: str, day: str) -> list[tuple[str, float, str]]:
    """[(period, value, vintage start)] of `series` exactly as FRED knew it on `day` (ALFRED real-time period)."""
    key = secrets.get("FRED_API_KEY")
    if not key:
        raise ActualUnavailable("chybí FRED_API_KEY")
    start = (dt.date.fromisoformat(day) - dt.timedelta(days=500)).isoformat()
    try:
        with httpx.Client(timeout=20.0, transport=_transport, headers={"User-Agent": "FTI/1.0 (personal analysis)"}) as c:
            r = c.get(API, params={"series_id": series, "api_key": key, "file_type": "json", "realtime_start": day,
                                   "realtime_end": day, "observation_start": start})
    except httpx.HTTPError as exc:
        raise ActualUnavailable(f"FRED neodpověděl ({type(exc).__name__})") from exc
    if r.status_code != 200:
        raise ActualUnavailable(f"FRED HTTP {r.status_code}")
    out = []
    for o in r.json().get("observations", []):
        try:
            out.append((o["date"], float(o["value"]), o["realtime_start"]))
        except (KeyError, ValueError):
            continue  # "." = no value
    return out


def _vintage_days(series: str, before: str) -> list[str]:
    """The release (vintage) days of `series` before `before`, newest first."""
    key = secrets.get("FRED_API_KEY")
    start = (dt.date.fromisoformat(before) - dt.timedelta(days=200)).isoformat()
    try:
        with httpx.Client(timeout=20.0, transport=_transport, headers={"User-Agent": "FTI/1.0 (personal analysis)"}) as c:
            r = c.get(VINTAGES_API, params={"series_id": series, "api_key": key, "file_type": "json", "realtime_start": start,
                                            "sort_order": "desc", "limit": 20})
    except httpx.HTTPError as exc:
        raise ActualUnavailable(f"FRED neodpověděl ({type(exc).__name__})") from exc
    if r.status_code != 200:
        raise ActualUnavailable(f"FRED HTTP {r.status_code}")
    return [d for d in r.json().get("vintage_dates", []) if d < before]


def _period_label(spec: Spec, period: str) -> str:
    d = dt.date.fromisoformat(period)
    if spec.series == "ICSA":
        return f"týden končící {d.day}. {d.month}. {d.year}"
    if spec.series in ("A191RL1Q225SBEA", "PRS85006092", "PRS85006112"):
        return f"{(d.month - 1) // 3 + 1}. čtvrtletí {d.year}"
    months = ["leden", "únor", "březen", "duben", "květen", "červen", "červenec", "srpen", "září", "říjen", "listopad", "prosinec"]
    return f"{months[d.month - 1]} {d.year}"


def _unit(spec: Spec) -> str:
    return {"diff_k": "tisíce pracovních míst za měsíc (K)", "thousands": "tisíce žádostí (K)", "millions": "miliony volných míst (M)",
            "billions": "miliardy USD (B)", "mom": "% změna proti minulému měsíci", "yoy": "% změna proti loňsku",
            "level": "%"}[spec.how]


def _value(spec: Spec, rows: list[tuple[str, float, str]], i: int) -> float | None:
    if i < 0 or i >= len(rows):
        return None
    v = rows[i][1]
    if spec.how == "level":
        return v
    if spec.how == "thousands":
        return v / 1000
    if spec.how == "millions":
        return v / 1000  # JOLTS is in thousands → millions
    if spec.how == "billions":
        return v / 1000  # trade balance is in millions → billions
    if spec.how in ("diff_k", "mom"):
        if i == 0:
            return None
        prev = rows[i - 1][1]
        return v - prev if spec.how == "diff_k" else (v / prev - 1) * 100
    if spec.how == "yoy":
        period = rows[i][0]
        year_ago = f"{int(period[:4]) - 1:04d}{period[4:]}"
        base = next((r[1] for r in rows if r[0] == year_ago), None)
        return (v / base - 1) * 100 if base else None
    raise ValueError(spec.how)


def fmt(spec: Spec, v: float | None) -> str | None:
    """The value written the way Forex Factory writes it ("165K", "4.1%", "0.4%", "7.52M", "-105.0B")."""
    if v is None:
        return None
    unit = {"diff_k": "K", "thousands": "K", "millions": "M", "billions": "B"}.get(spec.how, "%")
    return f"{round(v, spec.digits):.{spec.digits}f}{unit}"


def official(event: dict) -> dict:
    """The actual of one released event from the release day's official data. Raises ActualUnavailable."""
    spec = SPECS[event["title_en"]]
    day = release_day(event)
    rows = _vintage(spec.series, day)
    if not rows or rows[-1][2] != day:
        raise ActualUnavailable(f"FRED zatím nemá data vydaná {day} (řada {spec.series})")
    actual = _value(spec, rows, len(rows) - 1)
    prev_revised = _value(spec, rows, len(rows) - 2)
    period = rows[-1][0]
    # the previous period as officially published BEFORE this release (vintage of the previous release day) — kept next to
    # its revision in this release (monthly data: the first release; quarterly: its latest revision)
    prev_first, prev_day = None, None
    earlier = _vintage_days(spec.series, day)
    if earlier:
        prev_day = earlier[0]
        old = _vintage(spec.series, prev_day)
        if old and old[-1][0] == rows[-2][0]:
            prev_first = _value(spec, old, len(old) - 1)
    return {"v": RECORD_VERSION, "actual": fmt(spec, actual), "actual_value": round(actual, 4) if actual is not None else None,
            "unit": _unit(spec), "period": period, "period_label": _period_label(spec, period),
            "release_day": day, "release_time_utc": event["datetime"], "release_time_source": SECONDARY,
            "previous_ff": event.get("previous"), "previous_published": fmt(spec, prev_first),
            "previous_published_day": prev_day, "previous_revised": fmt(spec, prev_revised),
            "levels": [[r[0], r[1]] for r in rows[-3:]], "series": spec.series, "publisher": spec.publisher,
            "publisher_name": PUBLISHERS.get(spec.publisher, spec.publisher), "publisher_kind": "oficiální vládní zdroj",
            "via": VIA, "secondary": SECONDARY,
            "verification": {"status": "neověřeno u vydavatele", "reason": NOT_AT_PUBLISHER.get(spec.publisher, "čeká na kontrolu")},
            "source": f"{spec.publisher} přes ALFRED/FRED (stav ke dni vydání {day}, řada {spec.series})"}


def verify_at_publisher(records: dict[str, dict], now: dt.datetime) -> int:
    """The BLS values of `records` checked against BLS's own API in ONE request (the same levels → "ověřeno u vydavatele").
    Done once per record, before the next release can revise the value. Returns the number of records checked."""
    todo = {k: r for k, r in records.items() if r.get("publisher") == "BLS" and BLS_IDS.get(r.get("series"))
            and (r.get("verification") or {}).get("status") != "ověřeno u vydavatele" and r.get("levels")}
    with _lock:
        if not todo or time.monotonic() - _bls_failed.get("bls", -1e9) < BLS_RETRY_S:
            return 0
    ids = sorted({BLS_IDS[r["series"]] for r in todo.values()})
    year = int(max(r["levels"][-1][0] for r in todo.values())[:4])
    try:
        with httpx.Client(timeout=40.0, transport=_transport, headers={"User-Agent": "FTI/1.0 (personal analysis)",
                                                                        "Content-Type": "application/json"}) as c:
            r = c.post(BLS_API, json={"seriesid": ids, "startyear": str(year - 1), "endyear": str(year)})
        body = r.json()
        if r.status_code != 200 or body.get("status") != "REQUEST_SUCCEEDED":
            raise ActualUnavailable(f"BLS: {body.get('status')}")
    except (httpx.HTTPError, ValueError, ActualUnavailable):
        with _lock:
            _bls_failed["bls"] = time.monotonic()
        return 0
    data: dict[str, dict[str, float]] = {}
    for srs in body.get("Results", {}).get("series", []):
        for d in srs.get("data", []):
            per = str(d.get("period", ""))
            if per.startswith("M") and per != "M13":
                date = f"{d['year']}-{per[1:]}-01"
            elif per.startswith("Q") and per != "Q05":
                date = f"{d['year']}-{(int(per[1:]) - 1) * 3 + 1:02d}-01"
            else:
                continue
            try:
                data.setdefault(srs["seriesID"], {})[date] = float(d["value"])
            except (KeyError, ValueError):
                continue
    for rec in todo.values():
        bls = data.get(BLS_IDS[rec["series"]], {})
        pairs = [(per, v, bls.get(per)) for per, v in rec["levels"][-2:]]
        same = all(b is not None and abs(b - v) <= 1e-6 * max(1.0, abs(v)) + 0.005 for _, v, b in pairs)
        rec["verification"] = {"status": "ověřeno u vydavatele" if same else "ROZPOR s vydavatelem",
                               "publisher_api": f"BLS API v1, řada {BLS_IDS[rec['series']]}", "checked_at": now.isoformat(),
                               "compared": [{"period": per, "alfred": v, "bls": b} for per, v, b in pairs]}
    return len(todo)


def _num(text: str | None) -> float | None:
    if not text:
        return None
    t = text.strip().rstrip("%KMBT").replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def enrich(events: list[dict], now: dt.datetime, get=None, put=None) -> dict:
    """Adds actual / actual_source / revised previous to every released FF event that has an official source; stored
    once found (the release-day value never changes). Returns a summary {filled, from_cache, pending, requests, errors}."""
    from app.data import store

    get = get or (lambda k: store.cache_get(k)[0])
    put = put or (lambda k, v: store.cache_put(k, v, "alfred"))
    summary = {"filled": 0, "from_cache": 0, "pending": 0, "requests": 0, "errors": [], "no_official": 0}
    verified: dict[str, dict] = {}
    later_previous = {}  # FF's "previous" of the NEXT release of the same event = the actual it saw published
    for e in sorted(events, key=lambda e: e["datetime"]):
        if e.get("currency") == "USD" and e.get("previous"):
            later_previous.setdefault(e["title_en"], []).append((e["datetime"], e["previous"]))
    for e in events:
        if e.get("currency") != "USD" or e.get("source") != "ForexFactory":
            continue
        when = dt.datetime.fromisoformat(e["datetime"])
        if when > now - WAIT_AFTER_RELEASE or when < now - LOOKBACK:
            continue
        title = e["title_en"]
        if title in NO_OFFICIAL:
            e["actual_note"] = f"Skutečnost: bez volného oficiálního zdroje — {NO_OFFICIAL[title]}."
            summary["no_official"] += 1
            continue
        if title not in SPECS:
            continue
        k = key_of(e)
        rec = get(k)
        if isinstance(rec, dict) and rec.get("actual") and rec.get("v", 1) < RECORD_VERSION \
                and summary["requests"] < MAX_REQUESTS_PER_RUN:
            summary["requests"] += 1
            try:  # an older record gets the new fields; the old version stays in its history, nothing is deleted
                new = official(e)
                new["found_at"] = rec.get("found_at")
                new["upgraded_at"] = now.isoformat()
                new["history"] = [{k2: v2 for k2, v2 in rec.items() if k2 != "history"}] + list(rec.get("history") or [])
                if _num(new["actual"]) != _num(rec["actual"]):
                    new["verification"] = {"status": "ROZPOR s dříve uloženou hodnotou",
                                           "reason": f"dříve {rec['actual']}, teď {new['actual']}"}
                rec = new
                put(k, rec)
                summary["upgraded"] = summary.get("upgraded", 0) + 1
            except ActualUnavailable as exc:
                summary["errors"].append(f"{title}: {exc}")
        if isinstance(rec, dict) and rec.get("actual"):
            summary["from_cache"] += 1
        else:
            with _lock:
                last = _pending.get(k)
            if last and time.monotonic() - last < PENDING_RETRY_S:
                summary["pending"] += 1
                e["actual_note"] = "Skutečnost: čeká na oficiální data."
                continue
            if summary["requests"] >= MAX_REQUESTS_PER_RUN:
                continue
            summary["requests"] += 1
            try:
                rec = official(e)
            except ActualUnavailable as exc:
                with _lock:
                    _pending[k] = time.monotonic()
                summary["pending"] += 1
                summary["errors"].append(f"{title}: {exc}")
                e["actual_note"] = "Skutečnost: čeká na oficiální data."
                continue
            rec["found_at"] = now.isoformat()
            put(k, rec)
            summary["filled"] += 1
        nxt = next((p for d, p in later_previous.get(title, []) if d > e["datetime"]), None)
        if nxt is not None:  # FF's own "previous" of the next release — an independent check of FTI's number
            e["actual_check"] = {"ff_next_previous": nxt, "agrees": _num(nxt) == _num(rec["actual"])}
            summary.setdefault("checked", []).append({"title": title, "fti": rec["actual"], "ff_next_previous": nxt,
                                                      "agrees": e["actual_check"]["agrees"]})
        verified[k] = rec
        e["actual"] = rec["actual"]
        e["actual_status"] = (rec.get("verification") or {}).get("status", "neověřeno u vydavatele")
        e["actual_source"] = f"{rec['source']} — {e['actual_status']}"
        e["actual_period"] = rec["period"]
        if rec.get("previous_revised") and _num(rec["previous_revised"]) != _num(e.get("previous")):
            e["previous_revised"] = rec["previous_revised"]
        f, a = _num(e.get("forecast")), _num(rec["actual"])
        if f is not None and a is not None:
            e["surprise"] = round(a - f, 4)
    checked = verify_at_publisher(verified, now)
    if checked:  # the verdict is stored with the record (and shown) — never claimed without the publisher's numbers
        for k, rec in verified.items():
            put(k, rec)
        for e in events:
            rec = verified.get(key_of(e)) if e.get("actual") else None
            if rec:
                e["actual_status"] = rec["verification"]["status"]
                e["actual_source"] = f"{rec['source']} — {e['actual_status']}"
        summary["verified_at_publisher"] = checked
    summary["status"] = {k.split(":")[1]: (r.get("verification") or {}).get("status") for k, r in verified.items()}
    return summary
