"""Dukascopy Bank (Switzerland) public datafeed — delayed real XAU/USD quotes with exact times.

Verified 2026-11-01 against the user's broker (Purple Trading XAUUSD_ecn, MT5 minute bars 2025):
same instrument (spot gold, USD per troy ounce), timestamps aligned to the minute, median difference
0.10 USD (0.003 %), 95 % of minutes within 0.25 USD. Bid prices.

What it is not: live. Tick files appear per hour, about an hour late, so the label is DELAYED with
the exact time of the last tick. The datafeed is not an official API: it often answers 503 or times
out. FTI therefore asks gently — finished periods are cached on disk and never fetched again, at most
NEW_FILES_PER_CALL new files per call (history fills up over a few cycles), MIN_INTERVAL between
requests, and a pause after the first failure. Nothing is ever guessed: a missing file is missing.

Files used (month in the URL is 0-based):
  {SYM}/{Y}/{MM}/{DD}/BID_candles_min_1.bi5   minute candles of one finished day (LZMA, 24 B: t o c l h v)
  {SYM}/{Y}/{MM}/{DD}/{HH}h_ticks.bi5          ticks of one hour (LZMA, 20 B: ms ask bid ask_vol bid_vol)
"""

from __future__ import annotations

import datetime as dt
import lzma
import struct
import threading
import time
from pathlib import Path

import httpx

from app.config import BACKEND_DIR

BASE = "https://datafeed.dukascopy.com/datafeed"
POINT = {"XAUUSD": 1000.0}  # price = integer / POINT
CACHE_DIR = BACKEND_DIR / "cache" / "dukascopy"
MIN_INTERVAL = 1.5
PAUSES = (120, 300, 900, 1800)  # 2 → 5 → 15 → 30 minutes after consecutive failures
NEW_FILES_PER_CALL = 4
UTC = dt.timezone.utc
_transport: httpx.BaseTransport | None = None  # tests inject a mock
_lock = threading.Lock()
_state = {"last_request": 0.0, "paused_until": 0.0, "reason": "", "fails": 0}
_last_tick: dict[str, tuple[float, float, float, str]] = {}  # symbol -> (unix time, bid, ask, "tick" | "minute")
# every download attempt is counted, so FTI can say how reliable the datafeed really is
_stats = {"requests": 0, "ok": 0, "empty": 0, "errors": 0, "from_cache": 0, "pauses": 0, "last_ok": None, "last_error": None,
          "last_error_at": None}
_expected: dict[tuple[str, dt.date], frozenset[int]] = {}


class DukascopyUnavailable(RuntimeError):
    pass


def reset() -> None:
    with _lock:
        _state.update(last_request=0.0, paused_until=0.0, reason="", fails=0)
        _last_tick.clear()
        _stats.update(requests=0, ok=0, empty=0, errors=0, from_cache=0, pauses=0, last_ok=None, last_error=None,
                      last_error_at=None)


def _cache_path(path: str) -> Path:
    return CACHE_DIR / path.replace("/", "_")


def _get(path: str, final: bool, budget: list[int], keep_if_data: bool = False) -> bytes | None:
    """File content, b"" for a period without data, None when the call's budget for new files is spent.
    final: the period is long over — keep the answer, even an empty one. keep_if_data: a file that already
    has data is complete (Dukascopy publishes an hour's ticks only after the hour), so keep it too."""
    cached = _cache_path(path)
    if cached.exists():
        with _lock:
            _stats["from_cache"] += 1
        return cached.read_bytes()
    if budget[0] <= 0:
        return None
    with _lock:
        if time.monotonic() < _state["paused_until"]:
            raise DukascopyUnavailable(_state["reason"])
        wait = MIN_INTERVAL - (time.monotonic() - _state["last_request"])
    if wait > 0:
        time.sleep(wait)
    budget[0] -= 1
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0), transport=_transport, headers={"User-Agent": "FTI/1.0 (personal analysis)"}) as c:
            r = c.get(f"{BASE}/{path}")
        status, content = r.status_code, r.content
    except httpx.HTTPError as exc:
        status, content = None, type(exc).__name__
    _record(status, content, (time.monotonic() - t0) * 1000)
    with _lock:
        _state["last_request"] = time.monotonic()
        if status not in (200, 404):
            _stats["pauses"] += 1
            pause = PAUSES[min(_state["fails"], len(PAUSES) - 1)]
            _state["fails"] += 1
            _state["paused_until"] = time.monotonic() + pause
            _state["reason"] = f"Dukascopy teď neodpovídá ({status or content}) — další pokus nejdřív za {pause // 60} min."
            raise DukascopyUnavailable(_state["reason"])
        _state["fails"] = 0
    data = content if status == 200 else b""
    if final or (keep_if_data and data):
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    return data


def _record(status, content, ms: float) -> None:
    """Count the attempt and report it to FTI's source monitoring (Data page)."""
    from app.data import health

    now = dt.datetime.now(UTC).isoformat()
    with _lock:
        _stats["requests"] += 1
        if status == 200:
            _stats["ok"] += 1
            _stats["last_ok"] = now
        elif status == 404:
            _stats["empty"] += 1
        else:
            _stats["errors"] += 1
            _stats["last_error"] = str(status or content)
            _stats["last_error_at"] = now
    health.record("feed:dukascopy-datafeed", "Dukascopy datafeed (soubory)", ok=status in (200, 404), ms=ms,
                  error=None if status in (200, 404) else f"{status or content}")


def stats() -> dict:
    with _lock:
        out = dict(_stats)
    tried = out["ok"] + out["empty"] + out["errors"]
    out["success_pct"] = round(100 * (out["ok"] + out["empty"]) / tried, 1) if tried else None
    return out


def expected_minutes(symbol: str, day: dt.date) -> frozenset[int]:
    """Minutes of `day` (unix times) in which the market is open by FTI's trading calendar."""
    key = (symbol, day)
    if key not in _expected:
        from app.data import market_hours, universe

        inst = universe.get(symbol)
        day0 = int(dt.datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())
        _expected[key] = frozenset(day0 + m * 60 for m in range(1440) if inst is not None and market_hours.state(
            inst, dt.datetime.fromtimestamp(day0 + m * 60, UTC)).get("state") == market_hours.OPEN)
    return _expected[key]


def coverage(symbol: str, day: dt.date, minutes: list[tuple]) -> dict:
    """How complete one finished day is: present vs expected trading minutes and the gaps. Never filled in."""
    expected = expected_minutes(symbol, day)
    present = {m[0] for m in minutes}
    missing = sorted(expected - present)
    gaps, start, prev = [], None, None
    for t in missing:
        if start is None:
            start = prev = t
        elif t == prev + 60:
            prev = t
        else:
            gaps.append((start, prev))
            start = prev = t
    if start is not None:
        gaps.append((start, prev))
    return {"day": day.isoformat(), "expected": len(expected), "present": len(present & expected),
            "outside_hours": len(present - expected), "missing": len(missing),
            "gaps": [(dt.datetime.fromtimestamp(a, UTC).isoformat(), int((b - a) / 60) + 1) for a, b in gaps]}


def _minute_day(symbol: str, day: dt.date, budget: list[int]) -> list[tuple] | None:
    path = f"{symbol}/{day.year}/{day.month - 1:02d}/{day.day:02d}/BID_candles_min_1.bi5"
    raw = _get(path, final=True, budget=budget)
    if raw is None:
        return None
    if not raw:
        return []
    data = lzma.decompress(raw)
    day0 = int(dt.datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())
    p = POINT[symbol]
    out = []
    for i in range(0, len(data) - 23, 24):
        t, o, c, lo, hi, v = struct.unpack(">5i1f", data[i:i + 24])
        if v > 0:
            out.append((day0 + t, o / p, hi / p, lo / p, c / p, float(v)))
    return out


def _hour_ticks(symbol: str, hour: dt.datetime, now: dt.datetime, budget: list[int]) -> list[tuple] | None:
    path = f"{symbol}/{hour.year}/{hour.month - 1:02d}/{hour.day:02d}/{hour.hour:02d}h_ticks.bi5"
    raw = _get(path, final=hour + dt.timedelta(hours=3) < now, budget=budget, keep_if_data=hour + dt.timedelta(hours=1) <= now)
    if raw is None:
        return None
    if not raw:
        return []
    data = lzma.decompress(raw)
    h0 = hour.timestamp()
    p = POINT[symbol]
    return [(h0 + ms / 1000, bid / p, ask / p) for ms, ask, bid, _, _ in
            (struct.unpack(">3i2f", data[i:i + 20]) for i in range(0, len(data) - 19, 20))]


def _aggregate(minutes: list[tuple], sec: int) -> list[tuple]:
    """Minute records (t, o, h, l, c) → bars of `sec` seconds. Volume is 0: on the OTC market one bank's
    volume is not the market's volume, so FTI does not show it as if it were."""
    out: dict[int, list] = {}
    for t, o, h, lo, c, *_ in minutes:
        k = t - t % sec
        b = out.get(k)
        out[k] = [k, o, h, lo, c, 0.0] if b is None else [k, b[1], max(b[2], h), min(b[3], lo), c, 0.0]
    return [tuple(b) for _, b in sorted(out.items())]


def keep_whole(bars: list[tuple], span: int, covered: list[tuple[int, int]]) -> list[tuple]:
    """Only real candles: a candle whose whole time span lies in received files, plus the newest one that is still
    filling up (it starts inside the newest received stretch and runs past its end). A candle cut by the window edge
    or by a file not downloaded yet would show a wrong open, high or low, so it is left out — never stitched."""
    if not covered:
        return []
    last_a, last_z = covered[-1]
    return [b for b in bars if any(a <= b[0] and b[0] + span <= z for a, z in covered)
            or (last_a <= b[0] < last_z < b[0] + span)]


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for a, z in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], z)
        else:
            out.append([a, z])
    return [(a, z) for a, z in out]


def bars(symbol: str, sec: int, days: int, now: dt.datetime | None = None,
         budget: list[int] | None = None) -> tuple[list[tuple], dict]:
    """Bid bars of `sec` seconds (60 = M1 … 86 400 = D1) for the last `days` days: finished days from the
    minute-candle files, today from the hour tick files. meta says how much history is still missing, which
    time the received files cover ("covered") and up to when the data are complete ("complete_until") —
    a candle ending later is still forming. `budget` (new downloads) can be shared by several calls.
    An outage stops further downloads in this call; the files already on disk are still used."""
    if symbol not in POINT:
        raise DukascopyUnavailable(f"{symbol} zatím z Dukascopy neověřen.")
    now = now or dt.datetime.now(UTC)
    budget = budget if budget is not None else [NEW_FILES_PER_CALL]
    today = now.date()
    out: list[tuple] = []
    missing = 0
    newest_minute: tuple | None = None
    days_cov: list[dict] = []
    covered: list[tuple[int, int]] = []
    outage: str | None = None

    def fetch(fn, *args):
        nonlocal outage
        try:
            return fn(*args)
        except DukascopyUnavailable as exc:
            outage = outage or str(exc)
            budget[0] = 0  # nothing more is downloaded in this call; files already on disk still count
            return None

    # newest first, so a limited budget always fills the most recent history
    for back in range(1, days + 1):
        day = today - dt.timedelta(days=back)
        day0 = int(dt.datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())
        if day.weekday() == 5:
            covered.append((day0, day0 + 86400))  # Saturday: spot gold and forex do not trade — nothing is missing
            continue
        got = fetch(_minute_day, symbol, day, budget)
        if got is None:
            missing += 1
            continue
        covered.append((day0, day0 + 86400))
        if got and newest_minute is None:
            newest_minute = got[-1]
        if got:
            days_cov.append(coverage(symbol, day, got))
        out = _aggregate(got, sec) + out
    ticks: list[tuple] = []
    start = dt.datetime(today.year, today.month, today.day, tzinfo=UTC)
    for h in range(now.hour - 1, -1, -1):  # the current hour's file does not exist yet
        hour = start + dt.timedelta(hours=h)
        got = fetch(_hour_ticks, symbol, hour, now, budget)
        if got is None:
            missing += 1
            continue
        if got or hour + dt.timedelta(hours=3) < now:  # an empty answer for a recent hour may only mean "not published yet"
            covered.append((int(hour.timestamp()), int(hour.timestamp()) + 3600))
        ticks = got + ticks
    if ticks:
        minutes = [(int(t) - int(t) % 60, b, b, b, b) for t, b, _ in ticks]
        out = sorted({b[0]: b for b in out + _aggregate(minutes, sec)}.values())
        last = ticks[-1]
        with _lock:
            _last_tick[symbol] = (last[0], last[1], last[2], "tick")
    elif newest_minute is not None:
        # no tick of today yet (weekend, early morning): the close of the last traded minute, exact to the minute
        with _lock:
            prev = _last_tick.get(symbol)
            if prev is None or prev[0] < newest_minute[0] + 59:
                _last_tick[symbol] = (float(newest_minute[0] + 59), newest_minute[4], newest_minute[4], "minute")
    spans = _merge(covered)
    out = keep_whole(out, sec, spans)
    if not out and outage:
        raise DukascopyUnavailable(outage)
    exp = sum(d["expected"] for d in days_cov)
    cov = {"days": len(days_cov), "expected": exp, "present": sum(d["present"] for d in days_cov),
           "missing": sum(d["missing"] for d in days_cov),
           "pct": round(100 * sum(d["present"] for d in days_cov) / exp, 2) if exp else None,
           "longest_gap_min": max((g[1] for d in days_cov for g in d["gaps"]), default=0),
           "gaps": [g for d in days_cov for g in d["gaps"]][:20]}
    return out, {"symbol": symbol, "missing_files": missing, "last_tick": _last_tick.get(symbol), "coverage": cov,
                 "last_update": stats()["last_ok"], "covered": spans, "complete_until": spans[-1][1] if spans else None,
                 "outage": outage,
                 "volume_note": "Objem se nezobrazuje: XAUUSD a forex jsou mimoburzovní (OTC), objem jedné banky není objem trhu."}


def h1_bars(symbol: str, days: int, now: dt.datetime | None = None) -> tuple[list[tuple], dict]:
    return bars(symbol, 3600, days, now)


def last_tick(symbol: str) -> tuple[float, float, float, str] | None:
    """(unix time, bid, ask, precision) of the newest quote FTI has seen from Dukascopy."""
    with _lock:
        return _last_tick.get(symbol)
