"""Kraken public market data — gold price in USD on every timeframe.

Why PAXG: no free, keyless and legal source serves intraday XAUUSD spot
(Stooq: robots disallow + anti-bot; LBMA JSON: blocked for scripts; Binance
API host: robots.txt "Disallow: /"). PAX Gold (PAXG) is a token backed 1:1 by
one fine troy ounce of LBMA gold, redeemable for the bar, so it tracks spot
gold. Checked live 2026-10-02 09:09 UTC: spot XAU/USD 4182,56 vs. PAXG
4187,51 (+0,12 %). Kraken's public REST API is documented, needs no account
or key; we ask once per timeframe per cycle, far below its ~1 req/s limit.

PAXG trades 24/7, spot gold does not. Candles from the spot market's weekly
close (Fri 17:00 New York) to its reopen (Sun 18:00 New York) are dropped, so
weekends don't create fake trends the trader's XAUUSD chart doesn't have.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import httpx

OHLC_URL = "https://api.kraken.com/0/public/OHLC"
PAIR = "PAXGUSD"
USER_AGENT = "fundamental-trading-intelligence/0.6 (personal market overview)"
SECONDS_BETWEEN_REQUESTS = 1.0
NEW_YORK = ZoneInfo("America/New_York")

# label -> Kraken interval in minutes (Kraken returns up to 720 candles)
TIMEFRAMES: dict[str, int] = {"M15": 15, "H1": 60, "H4": 240, "D1": 1440, "W1": 10080}


class KrakenUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class Candle:
    time: dt.datetime  # candle open, UTC
    open: float
    high: float
    low: float
    close: float


def spot_market_closed(t: dt.datetime) -> bool:
    """True inside spot gold's weekend break (Fri 17:00 – Sun 18:00 New York)."""
    ny = t.astimezone(NEW_YORK)
    wd, hour = ny.weekday(), ny.hour  # Mon=0 … Sun=6
    return (wd == 4 and hour >= 17) or wd == 5 or (wd == 6 and hour < 18)


def _keep(c: Candle, minutes: int) -> bool:
    if minutes >= 10080:
        return True
    if minutes >= 1440:
        return c.time.weekday() < 5  # Sat/Sun UTC daily candles are weekend-only PAXG trading
    return not spot_market_closed(c.time)


def parse_ohlc(payload: dict, minutes: int) -> list[Candle]:
    if payload.get("error"):
        raise KrakenUnavailableError("; ".join(payload["error"]))
    result = payload.get("result") or {}
    rows = next((v for k, v in result.items() if k != "last"), None)
    if rows is None:
        raise KrakenUnavailableError("odpověď neobsahuje svíčky")
    candles = [
        Candle(dt.datetime.fromtimestamp(int(r[0]), dt.timezone.utc), float(r[1]), float(r[2]), float(r[3]), float(r[4]))
        for r in rows
    ]
    # Kraken's last row is the still-forming candle; keep it — it is the current price.
    return [c for c in candles if _keep(c, minutes)]


def fetch_ohlc(minutes: int, client: httpx.Client | None = None, pair: str = PAIR) -> list[Candle]:
    owns = client is None
    client = client or httpx.Client(timeout=20.0, headers={"User-Agent": USER_AGENT})
    try:
        resp = client.get(OHLC_URL, params={"pair": pair, "interval": minutes})
        resp.raise_for_status()
        return parse_ohlc(resp.json(), minutes)
    except (httpx.HTTPError, ValueError) as exc:
        raise KrakenUnavailableError(f"Kraken {pair} {minutes} min: {exc}") from exc
    finally:
        if owns:
            client.close()


def fetch_all(client: httpx.Client | None = None, sleep_fn=time.sleep) -> tuple[dict[str, list[Candle]], list[str]]:
    """All timeframes; a failed one is reported, never invented."""
    owns = client is None
    client = client or httpx.Client(timeout=20.0, headers={"User-Agent": USER_AGENT})
    out: dict[str, list[Candle]] = {}
    errors: list[str] = []
    try:
        for i, (label, minutes) in enumerate(TIMEFRAMES.items()):
            if i:
                sleep_fn(SECONDS_BETWEEN_REQUESTS)
            try:
                out[label] = fetch_ohlc(minutes, client)
            except KrakenUnavailableError as exc:
                errors.append(f"Cena zlata {label} nedostupná: {exc}")
        return out, errors
    finally:
        if owns:
            client.close()


TICKER_URL = "https://api.kraken.com/0/public/Ticker"
# Kraken pair -> (key in the answer, label, decimals). Live quotes for the ticker strip.
# USD/JPY left out: Kraken's yen book is thin (showed +2,65 % "since open" on 2026-10-02).
TICKERS = {
    "PAXGUSD": ("PAXGUSD", "Zlato", 2),
    "EURUSD": ("ZEURZUSD", "EUR/USD", 5),
    "GBPUSD": ("ZGBPZUSD", "GBP/USD", 5),
}


def fetch_tickers(client: httpx.Client | None = None) -> list[dict]:
    """Last price and change since today's open (00:00 UTC), per Kraken."""
    owns = client is None
    client = client or httpx.Client(timeout=20.0, headers={"User-Agent": USER_AGENT})
    try:
        resp = client.get(TICKER_URL, params={"pair": ",".join(TICKERS)})
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise KrakenUnavailableError(f"Kraken kurzy: {exc}") from exc
    finally:
        if owns:
            client.close()
    if payload.get("error"):
        raise KrakenUnavailableError("; ".join(payload["error"]))
    result = payload.get("result") or {}
    out = []
    for pair, (key, label, digits) in TICKERS.items():
        row = result.get(key) or result.get(pair)
        if row is None:
            continue
        last, opened = float(row["c"][0]), float(row["o"])
        out.append({"symbol": pair, "label": label, "price": round(last, digits), "digits": digits,
                    "change_pct": round((last / opened - 1) * 100, 2) if opened else None, "source": "Kraken", "live": True})
    return out


def fetch_last(pairs: dict[str, str], client: httpx.Client | None = None) -> dict[str, float]:
    """Last trade price for {pair: key in Kraken's answer} — used for the live DXY."""
    owns = client is None
    client = client or httpx.Client(timeout=20.0, headers={"User-Agent": USER_AGENT})
    try:
        resp = client.get(TICKER_URL, params={"pair": ",".join(pairs)})
        resp.raise_for_status()
        result = resp.json().get("result") or {}
    except (httpx.HTTPError, ValueError) as exc:
        raise KrakenUnavailableError(f"Kraken kurzy: {exc}") from exc
    finally:
        if owns:
            client.close()
    return {p: float(result[k]["c"][0]) for p, k in pairs.items() if k in result}


DXY_PAIRS = {"EURUSD": "ZEURZUSD", "GBPUSD": "ZGBPZUSD", "USDCAD": "ZUSDZCAD", "USDCHF": "USDCHF"}
