"""FRED (Federal Reserve Bank of St. Louis) connector.

Two access paths, both free:
  1. Keyless (default): FRED's public CSV download endpoint
     `fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES>` — the same file the
     "Download" button on every series page serves. Verified live
     2026-09-28; robots.txt does not disallow it for generic clients and asks
     for `Crawl-delay: 1`, which we respect (CSV_MIN_SECONDS_BETWEEN_REQUESTS).
     No registration, no key.
  2. Optional: the official JSON API, used only if FRED_API_KEY is set.

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

from app.config import settings

FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
CSV_MIN_SECONDS_BETWEEN_REQUESTS = 1.0  # FRED robots.txt: Crawl-delay: 1
CSV_HISTORY_DAYS = 800  # YoY on a monthly series needs 14+ months; quarterly annualized growth needs 3 quarters
API_OBSERVATION_LIMIT = 200

_last_csv_request_at: float | None = None


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
        "api_key": settings.fred_api_key,
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
    try:
        if settings.fred_api_key:
            observations = _fetch_via_api(series_id, client)
        else:
            observations = _fetch_via_csv(series_id, client, sleep_fn, history_days)
    except httpx.HTTPError as exc:
        raise FredUnavailableError(f"FRED nedostupný pro {series_id}: {exc}") from exc
    except ValueError as exc:
        raise FredUnavailableError(f"FRED vrátil neplatná data pro {series_id}: {exc}") from exc
    finally:
        if owns_client:
            client.close()
    return _valid_only(observations)
