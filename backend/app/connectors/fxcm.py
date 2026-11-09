"""FXCM's public candle repository — free, no account (github.com/fxcm/MarketData, terms: personal use per FXCM's EULA).

An INDEPENDENT source for the major currency pairs (FXCM's own dealing prices, bid and ask — not Dukascopy, not the
user's broker). Verified 8. 11. 2026 with real downloads:
  * H1 and m1 files by trading week: EURUSD, GBPUSD, USDJPY, USDCAD, USDCHF (week 43 of 2026: 120 hours, 7 187 minutes);
  * hour by hour against the broker's MT5 history: the same UTC bar starts (120/120), median difference 0.15–0.19 bp;
  * NOT in the repository: XAUUSD, XAGUSD, USDSEK, indices, oil; no D1 files; a week appears only after it ended
    (published on Mondays) — FXCM is history, the latest days come from Dukascopy / MT5;
  * the week number in the file name does not follow one calendar rule (2025/10 starts 2. 3., 2026/43 starts 25. 10.),
    so FTI never computes it: it reads the bars' own timestamps.
Finished weeks are cached on disk and never asked again (a 404 of a long-past week too); an error of this host stops only
FXCM's run, never Dukascopy's (and the other way round). Nothing is filled in. FTI uses the data only for its own
computations — FXCM's candles are not published in the public phone files.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import threading
import time
from pathlib import Path

import httpx

from app.config import BACKEND_DIR

URL = "https://candledata.fxcorporate.com/{period}/{symbol}/{year}/{week}.csv.gz"
SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "USDCAD", "USDCHF")
CACHE_DIR = BACKEND_DIR / "cache" / "fxcm"
MIN_INTERVAL = 0.5
UTC = dt.timezone.utc
_transport: httpx.BaseTransport | None = None  # tests inject a mock
_lock = threading.Lock()
_last = {"t": 0.0}


HEALTH_KEY, HEALTH_NAME = "feed:fxcm-archive", "FXCM archiv svíček (forex, týdenní soubory)"
MISS_TTL = 6 * 3600  # a week not published yet is asked again after 6 hours, not in every cycle


class FxcmUnavailable(RuntimeError):
    """The host does not answer (timeout, 5xx): FXCM's run stops, Dukascopy's goes on."""


class FxcmBadFile(RuntimeError):
    """One file is broken (not gzip / not CSV): only this instrument is skipped in the run, the file is not kept."""


def _path(period: str, symbol: str, year: int, week: int) -> Path:
    return CACHE_DIR / f"{period}_{symbol}_{year}_{week}.csv.gz"


def parse(raw: bytes) -> list[tuple]:
    """[(unix start, open, high, low, close, ticks)] of the BID side, oldest first. Times in the files are UTC."""
    if not raw:
        return []
    try:
        text = gzip.decompress(raw).decode("utf-8-sig", errors="replace")
    except (OSError, EOFError) as exc:  # gzip.BadGzipFile is an OSError
        raise FxcmBadFile(f"poškozený soubor FXCM ({type(exc).__name__})") from exc
    if "DateTime" not in text[:200]:
        raise FxcmBadFile("soubor FXCM nemá očekávanou hlavičku")
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            t = dt.datetime.strptime(r["DateTime"], "%m/%d/%Y %H:%M:%S.%f").replace(tzinfo=UTC)
            out.append((int(t.timestamp()), float(r["BidOpen"]), float(r["BidHigh"]), float(r["BidLow"]), float(r["BidClose"]),
                        float(r.get("TickQty") or 0)))
        except (KeyError, ValueError):
            continue
    return sorted(out)


def week_file(symbol: str, year: int, week: int, now: dt.datetime, budget: list[int], period: str = "H1") -> list[tuple] | None:
    """Bars of one weekly file, or [] when the repository has no such file, or None when this run's budget is spent."""
    p = _path(period, symbol, year, week)
    if p.exists():
        try:
            return parse(p.read_bytes())
        except FxcmBadFile:
            p.unlink(missing_ok=True)  # a damaged copy on disk is fetched again
            raise
    miss = p.with_suffix(".miss")
    if miss.exists() and time.time() - miss.stat().st_mtime < MISS_TTL:
        return []  # asked a moment ago: not published yet
    if budget[0] <= 0:
        return None
    with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last["t"])
    if wait > 0:
        time.sleep(wait)
    budget[0] -= 1
    from app.data import health

    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), transport=_transport,
                          headers={"User-Agent": "FTI/1.0 (personal analysis)"}) as c:
            r = c.get(URL.format(period=period, symbol=symbol, year=year, week=week))
    except httpx.HTTPError as exc:
        health.record(HEALTH_KEY, HEALTH_NAME, ok=False, ms=(time.monotonic() - t0) * 1000, error=type(exc).__name__)
        raise FxcmUnavailable(f"FXCM neodpověděl ({type(exc).__name__})") from exc
    finally:
        with _lock:
            _last["t"] = time.monotonic()
    ok = r.status_code in (200, 404)
    health.record(HEALTH_KEY, HEALTH_NAME, ok=ok, ms=(time.monotonic() - t0) * 1000, error=None if ok else f"HTTP {r.status_code}")
    if not ok:
        raise FxcmUnavailable(f"FXCM odpověděl HTTP {r.status_code}")
    raw = r.content if r.status_code == 200 else b""
    bars = parse(raw)
    p.parent.mkdir(parents=True, exist_ok=True)
    # FXCM publishes a week only after it ended, so a file with data is final once its last bar is two days old; a
    # missing file is final only when even the latest reading of the week number is long over (the numbering varies)
    if bars and bars[-1][0] < (now - dt.timedelta(days=2)).timestamp():
        p.write_bytes(raw)
        miss.unlink(missing_ok=True)
    elif not bars and dt.datetime(year, 1, 1, tzinfo=UTC) + dt.timedelta(weeks=week + 2) < now - dt.timedelta(days=10):
        p.write_bytes(b"")
        miss.unlink(missing_ok=True)
    elif not bars:
        miss.write_bytes(b"")
    return bars
