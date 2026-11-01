"""FRED (Federal Reserve Bank of St. Louis) connector.

Two access paths, both free:
  1. Keyless (default): FRED's public CSV download endpoint
     `fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES>` — the same file the
     "Download" button on every series page serves. Verified live
     2026-09-28; robots.txt does not disallow it for generic clients and asks
     for `Crawl-delay: 1`, which we respect (CSV_MIN_SECONDS_BETWEEN_REQUESTS).
     No registration, no key.
  2. The official JSON API, used whenever FRED_API_KEY is set (backend/.env or the environment;
     free key after registration at fred.stlouisfed.org — the reliable path).
Every request is retried; when FRED still fails, the same statistic is taken from its official
publisher where one is free and keyless (BLS, US Treasury, CBOE, EIA — see official_alt.py) and
labelled as such in LAST_SOURCE. PCE and GDP have no keyless copy (BEA needs a key).

Attribution requirement (shown in the frontend footer): "Source: FRED®,
Federal Reserve Bank of St. Louis." All series used here are US-government
public-domain data (Fed Board, BLS, BEA, Treasury).

Series used for XAUUSD (see ARCHITECTURE.md section 5):
  DFII10   - 10-Year Treasury Inflation-Indexed Security, real yield (daily)
  DTWEXBGS - Trade Weighted U.S. Dollar Index: Broad (daily)
  DFEDTARU - Federal Funds Target Range, upper bound (daily)
  CPILFESL - Core CPI (monthly)
  PCEPILFE - Core PCE price index (monthly)
  GDPC1    - Real GDP (quarterly)
  UNRATE   - Unemployment rate (monthly)
  PAYEMS   - Total nonfarm payrolls (monthly)
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import time

import httpx

from app.data import secrets

FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
CSV_MIN_SECONDS_BETWEEN_REQUESTS = 1.0  # FRED robots.txt: Crawl-delay: 1
CSV_HISTORY_DAYS = 800  # YoY on a monthly series needs 14+ months; quarterly annualized growth needs 3 quarters
API_OBSERVATION_LIMIT = 200

_last_csv_request_at: float | None = None
RETRIES = 2  # a failed request is tried again after 2 s and 5 s
# series id -> where its last data really came from ("FRED API", "FRED CSV", "BLS (záloha za FRED)", …)
LAST_SOURCE: dict[str, str] = {}


class FredUnavailableError(RuntimeError):
    pass


def _parse_value(raw: str | None) -> float | None:
    if raw is None or raw.strip() in ("", "."):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _valid_only(observations: list[dict]) -> list[dict]:
    valid = [o for o in observations if o["value"] is not None]
    if len(valid) < 2:
        raise FredUnavailableError(f"FRED vrátil méně než 2 platná pozorování ({len(valid)}).")
    return valid


def _throttle(sleep_fn) -> None:
    global _last_csv_request_at
    if _last_csv_request_at is not None:
        elapsed = time.monotonic() - _last_csv_request_at
        if elapsed < CSV_MIN_SECONDS_BETWEEN_REQUESTS:
            sleep_fn(CSV_MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
    _last_csv_request_at = time.monotonic()


def _fetch_via_csv(series_id: str, client: httpx.Client, sleep_fn, history_days: int = CSV_HISTORY_DAYS) -> list[dict]:
    _throttle(sleep_fn)
    start = (dt.date.today() - dt.timedelta(days=history_days)).isoformat()
    resp = client.get(FRED_CSV_URL, params={"id": series_id, "cosd": start})
    resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    header = next(reader, None)
    if not header or len(header) < 2 or header[1].strip() != series_id:
        raise FredUnavailableError(f"FRED CSV pro {series_id} má neočekávanou hlavičku: {header}")
    return [{"date": row[0], "value": _parse_value(row[1])} for row in reader if len(row) >= 2]


def _fetch_via_api(series_id: str, client: httpx.Client) -> list[dict]:
    params = {
        "series_id": series_id,
        "api_key": secrets.get("FRED_API_KEY"),
        "file_type": "json",
        "sort_order": "desc",
        "limit": API_OBSERVATION_LIMIT,
    }
    resp = client.get(FRED_API_URL, params=params)
    resp.raise_for_status()
    observations = resp.json().get("observations", [])
    return [{"date": o.get("date"), "value": _parse_value(o.get("value"))} for o in reversed(observations)]


def fetch_observations(series_id: str, client: httpx.Client | None = None, sleep_fn=time.sleep,
                       history_days: int = CSV_HISTORY_DAYS) -> list[dict]:
    """Return recent valid observations for a series, oldest first.

    Each dict: {date, value}. Missing values (FRED "." or empty) are
    dropped. Turning raw levels into the number a trader actually reads
    (YoY %, monthly change, ...) happens in app/ingestion/transforms.py.
    Raises FredUnavailableError on any failure — never fabricates data.
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=20.0, follow_redirects=True)
    use_api = bool(secrets.get("FRED_API_KEY"))
    error: Exception | None = None
    try:
        for attempt in range(RETRIES + 1):
            try:
                if use_api:
                    observations = _fetch_via_api(series_id, client)
                else:
                    observations = _fetch_via_csv(series_id, client, sleep_fn, history_days)
                valid = _valid_only(observations)
                LAST_SOURCE[series_id] = "FRED API" if use_api else "FRED (veřejné CSV)"
                return valid
            except (httpx.HTTPError, ValueError, FredUnavailableError) as exc:
                error = exc
                if attempt < RETRIES:
                    sleep_fn(2 + 3 * attempt)
    finally:
        if owns_client:
            client.close()
    alt = _official_fallback(series_id, history_days)
    if alt is not None:
        return alt
    raise FredUnavailableError(f"FRED nedostupný pro {series_id}: {error}") from error


def _official_fallback(series_id: str, history_days: int) -> list[dict] | None:
    """The same statistic straight from its official publisher when FRED fails (BLS, Treasury,
    CBOE, EIA). Returns None when there is no keyless official copy (PCE, GDP: BEA needs a key)."""
    from app.connectors import official_alt

    try:
        if series_id in official_alt.BLS_SERIES:
            data, name = official_alt.bls_all().get(series_id), "BLS (záloha za FRED)"
        elif series_id in official_alt.TREASURY_SERIES:
            data, name = official_alt.treasury(series_id, years=max(2, history_days // 365 + 1)), "US Treasury (záloha za FRED)"
        elif series_id == "VIXCLS":
            data, name = official_alt.vix_closes(), "CBOE (záloha za FRED)"
        elif series_id in ("DCOILWTICO", "DCOILBRENTEU", "DHHNGSP"):
            eia_id = {"DCOILWTICO": "RWTC", "DCOILBRENTEU": "RBRTE", "DHHNGSP": "RNGWHHD"}[series_id]
            data, name = official_alt.eia_daily(eia_id), "EIA (záloha za FRED)"
        else:
            return None
    except official_alt.OfficialUnavailable:
        return None
    if not data:
        return None
    start = (dt.date.today() - dt.timedelta(days=history_days)).isoformat()
    rows = [{"date": d, "value": v} for d, v in sorted(data.items()) if d >= start]
    if len(rows) < 2:
        return None
    LAST_SOURCE[series_id] = name
    return rows
