"""ECB euro foreign exchange reference rates — official, free, no key.

https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip (CSV, every
business day since 1999, published ~16:00 CET). robots.txt only disallows
some language HTML pages, not /stats/eurofxref/. Checked live 2026-10-02.

Used for the DXY replica: all six DXY currencies (EUR, JPY, GBP, CAD, SEK,
CHF) are in it, so the daily DXY history is official data, not a scrape.
Fetched at most every 6 hours (rates change once a day).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import threading
import zipfile

import httpx

HIST_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
CURRENCIES = ("USD", "JPY", "GBP", "CAD", "SEK", "CHF")  # required on a day (the dollar index needs them all)
OPTIONAL = ("AUD", "NZD")  # added when the day has them (FX crosses of the instrument registry)
CACHE_HOURS = 6

_cache: dict[str, object] = {"at": None, "rates": None}
_lock = threading.Lock()


class EcbUnavailableError(RuntimeError):
    pass


def parse_csv(text: str) -> dict[str, dict[str, float]]:
    """date -> {currency: units per 1 EUR}, only days with all DXY currencies."""
    out: dict[str, dict[str, float]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            day = {c: float(row[c]) for c in CURRENCIES}
        except (KeyError, ValueError, TypeError):
            continue
        for c in OPTIONAL:
            try:
                day[c] = float(row[c])
            except (KeyError, ValueError, TypeError):
                pass
        out[row["Date"]] = day
    return out


def fetch_history(now: dt.datetime, client: httpx.Client | None = None) -> dict[str, dict[str, float]]:
    with _lock:
        at, rates = _cache["at"], _cache["rates"]
        if isinstance(at, dt.datetime) and rates and now - at < dt.timedelta(hours=CACHE_HOURS):
            return rates  # type: ignore[return-value]
    owns = client is None
    client = client or httpx.Client(timeout=60.0)
    try:
        resp = client.get(HIST_URL)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            text = z.read(z.namelist()[0]).decode("utf-8")
    except (httpx.HTTPError, zipfile.BadZipFile, KeyError, IndexError) as exc:
        raise EcbUnavailableError(f"kurzy ECB nedostupné: {exc}") from exc
    finally:
        if owns:
            client.close()
    rates = parse_csv(text)
    if len(rates) < 500:
        raise EcbUnavailableError(f"ECB vrátila málo dní ({len(rates)})")
    with _lock:
        _cache["at"], _cache["rates"] = now, rates
    return rates
