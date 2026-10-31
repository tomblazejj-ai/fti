"""Narodowy Bank Polski — official daily gold price since 2 January 2013.

Free public API for programmers (api.nbp.pl), no key, no registration. NBP publishes
the price of 1 g of gold in PLN every business day; with NBP's USD/PLN mid rate of the
same day it converts to USD per troy ounce. Checked live 2026-10-17: 16. 10. 2026 →
519,85 PLN/g ÷ 3,8827 PLN/USD × 31,1035 = 4 164 $/oz (spot ~4 160 $).

Used for the DAILY seasonality windows (the strategy compares e.g. "11. 9. – 9. 10."
over the last 5–10 years). Kraken PAXG has only ~2 years of daily candles and the
World Bank only monthly averages.

API limits: at most 93 days per gold request and 367 days per exchange-rate request.
The converted history is kept in backend/cache/nbp_gold_usd.json, so after the first
download (~70 small requests, about half a minute) only the newest days are fetched,
at most once every 12 hours.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
from pathlib import Path

import httpx

from app.config import BACKEND_DIR

GOLD_URL = "https://api.nbp.pl/api/cenyzlota/{a}/{b}/"
USD_URL = "https://api.nbp.pl/api/exchangerates/rates/a/usd/{a}/{b}/"
START = dt.date(2013, 1, 2)
TROY_OUNCE_G = 31.1034768
GOLD_CHUNK_DAYS = 93
USD_CHUNK_DAYS = 367
REFRESH_HOURS = 12
REFETCH_DAYS = 7  # the newest week is always fetched again (late corrections)
CACHE_FILE = BACKEND_DIR / "cache" / "nbp_gold_usd.json"

_lock = threading.Lock()
_mem: dict[str, object] = {"at": None, "data": None}


class NbpUnavailableError(RuntimeError):
    pass


def _get(client: httpx.Client, url: str) -> list | dict | None:
    resp = client.get(url, params={"format": "json"}, headers={"Accept": "application/json"})
    if resp.status_code == 404:  # NBP answers 404 for a range without any business day
        return None
    resp.raise_for_status()
    return resp.json()


def _chunks(a: dt.date, b: dt.date, days: int):
    while a <= b:
        e = min(b, a + dt.timedelta(days=days - 1))
        yield a, e
        a = e + dt.timedelta(days=1)


def fetch_range(a: dt.date, b: dt.date, client: httpx.Client, sleep_fn=time.sleep) -> dict[str, float]:
    """USD per troy ounce for every NBP business day in [a, b]."""
    gold: dict[str, float] = {}
    usd: dict[str, float] = {}
    for x, y in _chunks(a, b, GOLD_CHUNK_DAYS):
        rows = _get(client, GOLD_URL.format(a=x.isoformat(), b=y.isoformat())) or []
        for r in rows:
            gold[r["data"]] = float(r["cena"])
        sleep_fn(0.25)
    for x, y in _chunks(a, b, USD_CHUNK_DAYS):
        body = _get(client, USD_URL.format(a=x.isoformat(), b=y.isoformat())) or {}
        for r in body.get("rates", []) if isinstance(body, dict) else []:
            usd[r["effectiveDate"]] = float(r["mid"])
        sleep_fn(0.25)
    return {d: round(g * TROY_OUNCE_G / usd[d], 2) for d, g in gold.items() if usd.get(d)}


def _load(path: Path) -> dict[str, float]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in data.get("prices", {}).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def fetch_gold_usd(now: dt.datetime, client: httpx.Client | None = None, sleep_fn=time.sleep,
                   cache_file: Path = CACHE_FILE) -> dict[str, float]:
    """{"YYYY-MM-DD": USD per ounce} since 2013, oldest first. Raises NbpUnavailableError
    only when there is nothing at all (no cache and no answer)."""
    with _lock:
        at, data = _mem["at"], _mem["data"]
        if isinstance(at, dt.datetime) and data and now - at < dt.timedelta(hours=REFRESH_HOURS):
            return data  # type: ignore[return-value]
    prices = _load(cache_file)
    today = now.date()
    start = START if not prices else max(START, dt.date.fromisoformat(max(prices)) - dt.timedelta(days=REFETCH_DAYS))
    owns = client is None
    client = client or httpx.Client(timeout=30.0, follow_redirects=True)
    try:
        prices.update(fetch_range(start, today, client, sleep_fn))
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        if not prices:
            raise NbpUnavailableError(f"API NBP neodpovídá: {exc}") from exc
    finally:
        if owns:
            client.close()
    if len(prices) < 250:
        raise NbpUnavailableError("NBP vrátila málo dní historie")
    prices = dict(sorted(prices.items()))
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"source": "api.nbp.pl", "unit": "USD/oz", "prices": prices}), encoding="utf-8")
    except OSError:
        pass  # the history still works from memory
    with _lock:
        _mem["at"], _mem["data"] = now, prices
    return prices
