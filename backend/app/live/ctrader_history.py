"""cTrader Open API history: OHLC trendbars (M1 … MN1) and ticks (bid and ask apart) — READ-ONLY.

Messages (help.ctrader.com/open-api, checked 9. 11. 2026): ProtoOAGetTrendbarsReq 2137 / Res 2138 (period, symbolId,
fromTimestamp, toTimestamp in Unix ms, optional count; hasMore when more bars match than one answer holds),
ProtoOAGetTickDataReq 2145 / Res 2146 (type BID = 1 / ASK = 2; ticks newest first, the first with absolute values,
the next ones as differences from the previous one), ProtoOASymbolByIdReq 2116 / Res 2117.

Limits (cTrader): 50 requests a second for ordinary requests and 5 a second for history requests on one connection;
error REQUEST_FREQUENCY_EXCEEDED when exceeded. FTI keeps below them with its own limiter, sends history requests one
by one from a queue, retries a refused or timed-out request with exponential backoff and random jitter, and caches
finished (closed) ranges on disk so the same history is never asked for twice. The limits can be lowered in settings
(ctrader.limits); they are the provider's, not FTI's.

Not verified against the live service yet: the app is Submitted (not Active). The price encoding of trendbars and
ticks (integers in 1/100 000, as in spot events) is the documented spot rule applied to history — tools/ctrader_coverage
checks it against the live price as soon as the app is Active.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import random
import time
import uuid
from collections import deque
from pathlib import Path

from app.data import settings_store
from app.live.ctrader import CT, HOSTS, PRICE, CTrader, CTraderError

HIST = {"TRENDBARS": 2137, "TRENDBARS_RES": 2138, "TICKDATA": 2145, "TICKDATA_RES": 2146, "SYMBOL_BY_ID": 2116,
        "SYMBOL_BY_ID_RES": 2117}
PERIOD = {"M1": 1, "M5": 5, "M15": 7, "M30": 8, "H1": 9, "H4": 10, "D1": 12, "W1": 13, "MN1": 14}
PERIOD_S = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800, "MN1": 2678400}
QUOTE = {"bid": 1, "ask": 2}
LIMITS = {"general": 50, "history": 5}  # per second and connection (cTrader); settings ctrader.limits may lower them
RETRYABLE = {"REQUEST_FREQUENCY_EXCEEDED", "TIMEOUT", "DISCONNECTED", "INTERNAL_ERROR", "SERVER_IS_UNDER_MAINTENANCE"}
MAX_ATTEMPTS = 5
CACHE_DIR = Path(__file__).resolve().parents[2] / "cache" / "ctrader"


def limits() -> dict[str, int]:
    own = (settings_store.get("ctrader", {}) or {}).get("limits") or {}
    return {k: max(1, min(int(own.get(k, v)), v)) for k, v in LIMITS.items()}  # lower only, never above cTrader's


class RateLimiter:
    """At most `per_second` calls in any one-second window (sliding window)."""

    def __init__(self, per_second: int, clock=time.monotonic, sleep=asyncio.sleep):
        self.n, self.clock, self.sleep = per_second, clock, sleep
        self.window: deque[float] = deque()

    async def acquire(self) -> None:
        while True:
            now = self.clock()
            while self.window and now - self.window[0] >= 1.0:
                self.window.popleft()
            if len(self.window) < self.n:
                self.window.append(now)
                return
            await self.sleep(1.0 - (now - self.window[0]) + 0.001)


def backoff(attempt: int, base: float = 1.0, cap: float = 60.0, rnd=random.random) -> float:
    """Seconds before retry `attempt` (0, 1, 2 …): 1, 2, 4 … up to 60 s, each with ±25 % random jitter."""
    return min(cap, base * 2 ** attempt) * (0.75 + rnd() / 2)


def decode_trendbar(tb: dict, scale: float = PRICE) -> tuple[int, float, float, float, float, float]:
    """(t in Unix s, open, high, low, close, tick volume) — prices are integers relative to `low`."""
    low = int(tb.get("low") or 0)
    t = int(tb.get("utcTimestampInMinutes") or 0) * 60
    return (t, (low + int(tb.get("deltaOpen") or 0)) / scale, (low + int(tb.get("deltaHigh") or 0)) / scale, low / scale,
            (low + int(tb.get("deltaClose") or 0)) / scale, float(tb.get("volume") or 0))


def decode_ticks(rows: list[dict], scale: float = PRICE) -> list[tuple[int, float]]:
    """[(t in Unix ms, price)] oldest first. cTrader sends them newest first: the first tick absolute, every next one as
    the difference from the one before (time and price alike)."""
    out, t, price = [], 0, 0
    for i, r in enumerate(rows):
        dt_ms, dp = int(r.get("timestamp") or 0), int(r.get("tick") or 0)
        t, price = (dt_ms, dp) if i == 0 else (t + dt_ms, price + dp)
        out.append((t, price / scale))
    return sorted(out)


def _cache_file(kind: str, code: str, key: str) -> Path:
    return CACHE_DIR / kind / f"{code.replace('/', '_')}-{key}.json.gz"


class HistoryClient:
    """One read-only connection to the demo (or live) server for history requests. Use as `async with`."""

    def __init__(self, symbols: dict[str, str] | None = None, host: str = "demo", connect=None, clock=time.monotonic,
                 sleep=asyncio.sleep, rnd=random.random, now=time.time, cache: bool = True):
        self.adapter = CTrader(symbols or {c: c for c in ("XAUUSD", "EURUSD", "US500.CFD", "US100.CFD")}, host=host)
        self.url = HOSTS[host]
        self._connect = connect
        self.ws = None
        lim = limits()
        self.general = RateLimiter(lim["general"], clock, sleep)
        self.history = RateLimiter(lim["history"], clock, sleep)
        self.queue = asyncio.Lock()  # history requests go one by one
        self.sleep, self.rnd, self.now, self.cache = sleep, rnd, now, cache
        self.requests = {"general": 0, "history": 0, "retries": 0}

    async def __aenter__(self) -> HistoryClient:
        if self._connect is None:
            import websockets

            self.ws = await websockets.connect(self.url, open_timeout=20, ping_interval=20, ping_timeout=20, max_size=2 ** 24)
        else:
            self.ws = await self._connect(self.url)
        await self.adapter.authorize(self.ws)
        return self

    async def __aexit__(self, *exc) -> None:
        close = getattr(self.ws, "close", None)
        if close:
            await close()

    @property
    def account(self) -> int:
        return int(self.adapter.account or 0)

    def symbol_id(self, code: str) -> int:
        for sid, (_, c) in self.adapter.ids.items():
            if c == code:
                return sid
        raise CTraderError("NO_SYMBOL", f"{code} u brokera nenalezen")

    async def _request(self, kind: str, ptype: int, payload: dict, expect: int) -> dict:
        limiter = self.history if kind == "history" else self.general
        for attempt in range(MAX_ATTEMPTS):
            await limiter.acquire()
            self.requests[kind] += 1
            try:
                return await self._send(ptype, payload, expect)
            except (CTraderError, asyncio.TimeoutError) as exc:
                code = exc.code if isinstance(exc, CTraderError) else "TIMEOUT"
                if code not in RETRYABLE or attempt == MAX_ATTEMPTS - 1:
                    raise
                self.requests["retries"] += 1
                await self.sleep(backoff(attempt, rnd=self.rnd))
        raise CTraderError("RETRIES", "pokusy vyčerpány")  # pragma: no cover — the loop raises before

    async def _send(self, ptype: int, payload: dict, expect: int) -> dict:
        msg_id = uuid.uuid4().hex
        await self.ws.send(json.dumps({"clientMsgId": msg_id, "payloadType": ptype, "payload": payload}))
        while True:
            msg = json.loads(await asyncio.wait_for(self.ws.recv(), 30))
            pt = msg.get("payloadType")
            if pt in (CT["OA_ERROR"], CT["ERROR"]):
                p = msg.get("payload") or {}
                raise CTraderError(str(p.get("errorCode")), str(p.get("description") or ""))
            if pt == expect:
                return msg.get("payload") or {}

    async def symbol_details(self, code: str) -> dict:
        res = await self._request("general", HIST["SYMBOL_BY_ID"], {"ctidTraderAccountId": self.account,
                                                                   "symbolId": [self.symbol_id(code)]}, HIST["SYMBOL_BY_ID_RES"])
        rows = res.get("symbol") or []
        return rows[0] if rows else {}

    async def trendbars(self, code: str, tf: str, from_ms: int, to_ms: int, count: int | None = None) -> list[tuple]:
        """Bars of [from_ms, to_ms), oldest first; pages back while cTrader says there is more."""
        if tf not in PERIOD:
            raise ValueError(f"cTrader rámec {tf} nezná")
        key = f"{tf}-{from_ms}-{to_ms}-{count or 0}"
        closed = to_ms <= (self.now() - PERIOD_S[tf]) * 1000  # only finished ranges are cached
        cached = self._read_cache("trendbars", code, key) if self.cache and closed else None
        if cached is not None:
            return [tuple(r) for r in cached]
        out: dict[int, tuple] = {}
        end = to_ms
        async with self.queue:
            while end > from_ms:
                payload = {"ctidTraderAccountId": self.account, "symbolId": self.symbol_id(code), "period": PERIOD[tf],
                           "fromTimestamp": from_ms, "toTimestamp": end}
                if count:
                    payload["count"] = count
                res = await self._request("history", HIST["TRENDBARS"], payload, HIST["TRENDBARS_RES"])
                bars = [decode_trendbar(tb) for tb in res.get("trendbar") or []]
                for b in bars:
                    out[b[0]] = b
                if not res.get("hasMore") or not bars or count:
                    break
                oldest = min(b[0] for b in bars) * 1000
                if oldest >= end:
                    break
                end = oldest
        rows = [out[k] for k in sorted(out)]
        if self.cache and closed:
            self._write_cache("trendbars", code, key, rows)
        return rows

    async def ticks(self, code: str, side: str, from_ms: int, to_ms: int) -> list[tuple[int, float]]:
        """Ticks of one side ("bid" / "ask") in [from_ms, to_ms], oldest first; pages back on hasMore."""
        key = f"{side}-{from_ms}-{to_ms}"
        closed = to_ms <= (self.now() - 60) * 1000
        cached = self._read_cache("ticks", code, key) if self.cache and closed else None
        if cached is not None:
            return [tuple(r) for r in cached]
        out: dict[int, float] = {}
        end = to_ms
        async with self.queue:
            while end > from_ms:
                res = await self._request("history", HIST["TICKDATA"], {
                    "ctidTraderAccountId": self.account, "symbolId": self.symbol_id(code), "type": QUOTE[side],
                    "fromTimestamp": from_ms, "toTimestamp": end}, HIST["TICKDATA_RES"])
                got = decode_ticks(res.get("tickData") or [])
                for t, p in got:
                    out[t] = p
                if not res.get("hasMore") or not got:
                    break
                oldest = got[0][0]
                if oldest >= end:
                    break
                end = oldest - 1
        rows = sorted(out.items())
        if self.cache and closed:
            self._write_cache("ticks", code, key, rows)
        return rows

    def _read_cache(self, kind: str, code: str, key: str):
        f = _cache_file(kind, code, key)
        try:
            return json.loads(gzip.decompress(f.read_bytes()))
        except (OSError, ValueError):
            return None

    def _write_cache(self, kind: str, code: str, key: str, rows) -> None:
        f = _cache_file(kind, code, key)
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(gzip.compress(json.dumps(rows).encode()))
        except OSError:
            pass  # the cache only saves requests; without it the history is asked for again
