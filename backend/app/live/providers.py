"""Provider adapters: a stream → normalised ticks. Each adapter reconnects by itself (growing pause), keeps the
connection alive and measures itself (connection, messages, latency, errors) — one failing provider never stops another.

  Deriv   public WebSocket, no key (wss://api.derivws.com/trading/v1/options/ws/public): a snapshot about once a second
          with bid, ask, mid ("quote") and the quote time (epoch). Tested 9. 11. 2026: age at receipt 0.3 s.
          History: ticks_history candles (built from the mid).
  Kraken  WebSocket v2 ticker with event_trigger "bbo": every change of the best bid / offer of Kraken's own EUR/USD
          market — no quote time in the message, so the receive time is used and said so (time_basis "receive").
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import statistics
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)
PAUSES = (1, 2, 5, 15, 30, 60)  # s between reconnects after consecutive failures


@dataclass(frozen=True)
class Tick:
    code: str
    provider: str
    symbol: str
    t: float  # quote time (unix s) — the provider's, or the receive time when the provider gives none
    recv: float  # when FTI received it
    bid: float | None
    ask: float | None
    last: float | None = None  # last trade, where the provider has one
    time_basis: str = "quote"  # "quote" = the provider's quote time, "receive" = FTI's receive time

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        return self.last


class Metrics:
    """Per provider: is it connected, how often it speaks, how late its quotes arrive, what went wrong."""

    def __init__(self, name: str):
        self.name = name
        self.connected = False
        self.connects = 0
        self.disconnects = 0
        self.messages = 0
        self.ticks = 0
        self.last_message: float | None = None
        self.connected_since: float | None = None
        self.errors: collections.deque = collections.deque(maxlen=8)
        self.latency: collections.deque = collections.deque(maxlen=600)  # receive − quote time, s
        self.notes: dict[str, str] = {}  # symbol → why it is not streaming (e.g. market closed)

    def error(self, text: str) -> None:
        self.errors.append({"at": time.time(), "error": text[:200]})

    def view(self, now: float | None = None) -> dict:
        now = now or time.time()
        lat = sorted(self.latency)
        return {"provider": self.name, "connected": self.connected, "connects": self.connects, "disconnects": self.disconnects,
                "messages": self.messages, "ticks": self.ticks,
                "last_message_age_s": round(now - self.last_message, 1) if self.last_message else None,
                "connected_for_s": round(now - self.connected_since) if self.connected and self.connected_since else None,
                "latency_median_s": round(statistics.median(lat), 3) if lat else None,
                "latency_p95_s": round(lat[int(0.95 * (len(lat) - 1))], 3) if lat else None,
                "errors": list(self.errors), "notes": dict(self.notes)}


class Provider:
    name = ""
    url = ""

    def __init__(self, symbols: dict[str, str]):
        self.symbols = symbols  # provider symbol → FTI code
        self.metrics = Metrics(self.name)

    async def run(self, emit, stop: asyncio.Event) -> None:
        import websockets

        fails = 0
        while not stop.is_set():
            try:
                async with websockets.connect(self.url, open_timeout=20, ping_interval=20, ping_timeout=20, max_size=2 ** 22) as ws:
                    self.metrics.connected, self.metrics.connected_since = True, time.time()
                    self.metrics.connects += 1
                    fails = 0
                    await self.subscribe(ws)
                    keep = asyncio.create_task(self.keepalive(ws, stop))
                    try:
                        while not stop.is_set():
                            try:
                                raw = await asyncio.wait_for(ws.recv(), timeout=60)
                            except asyncio.TimeoutError:
                                raise ConnectionError("60 s bez jediné zprávy")
                            self.metrics.messages += 1
                            self.metrics.last_message = time.time()
                            for tick in self.parse(json.loads(raw)):
                                self.metrics.ticks += 1
                                if tick.time_basis == "quote":
                                    self.metrics.latency.append(tick.recv - tick.t)
                                emit(tick)
                    finally:
                        keep.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — every failure: record, pause, reconnect
                self.metrics.error(f"{type(exc).__name__}: {exc}")
                log.warning("live provider %s: %s", self.name, exc)
            if self.metrics.connected:
                self.metrics.disconnects += 1
            self.metrics.connected = False
            if stop.is_set():
                break
            pause = PAUSES[min(fails, len(PAUSES) - 1)]
            fails += 1
            try:
                await asyncio.wait_for(stop.wait(), timeout=pause)
            except asyncio.TimeoutError:
                pass

    async def subscribe(self, ws) -> None:  # pragma: no cover — overridden
        raise NotImplementedError

    async def keepalive(self, ws, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(30)

    def parse(self, msg: dict) -> list[Tick]:  # pragma: no cover — overridden
        raise NotImplementedError


class Deriv(Provider):
    name = "deriv"
    url = "wss://api.derivws.com/trading/v1/options/ws/public"
    RESUBSCRIBE_S = 300  # a symbol refused (market closed) is asked again after 5 min

    async def subscribe(self, ws) -> None:
        self._ws = ws
        self._pending: dict[str, float] = {}
        for sym in self.symbols:  # one request per symbol: a closed market must not block the others
            await ws.send(json.dumps({"ticks": sym, "subscribe": 1, "passthrough": {"symbol": sym}}))

    async def keepalive(self, ws, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(30)
            await ws.send(json.dumps({"ping": 1}))
            now = time.time()
            for sym, since in list(self._pending.items()):
                if now - since >= self.RESUBSCRIBE_S:
                    self._pending.pop(sym)
                    await ws.send(json.dumps({"ticks": sym, "subscribe": 1, "passthrough": {"symbol": sym}}))

    def parse(self, msg: dict) -> list[Tick]:
        now = time.time()
        if msg.get("error"):
            sym = ((msg.get("echo_req") or {}).get("passthrough") or {}).get("symbol") or (msg.get("echo_req") or {}).get("ticks")
            text = f"{msg['error'].get('code')}: {msg['error'].get('message')}"
            if sym in self.symbols:
                self.metrics.notes[sym] = text
                self._pending[sym] = now
            else:
                self.metrics.error(text)
            return []
        t = msg.get("tick")
        if not t or t.get("symbol") not in self.symbols:
            return []
        self.metrics.notes.pop(t["symbol"], None)
        bid, ask = t.get("bid"), t.get("ask")
        return [Tick(self.symbols[t["symbol"]], self.name, t["symbol"], float(t.get("epoch") or now), now,
                     float(bid) if bid is not None else None, float(ask) if ask is not None else None,
                     float(t["quote"]) if t.get("quote") is not None else None)]


class Kraken(Provider):
    name = "kraken"
    url = "wss://ws.kraken.com/v2"

    async def subscribe(self, ws) -> None:
        await ws.send(json.dumps({"method": "subscribe", "params": {"channel": "ticker", "symbol": list(self.symbols),
                                                                    "event_trigger": "bbo"}}))

    async def keepalive(self, ws, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(30)
            await ws.send(json.dumps({"method": "ping"}))

    def parse(self, msg: dict) -> list[Tick]:
        now = time.time()
        if msg.get("method") == "subscribe" and not msg.get("success", True):
            self.metrics.error(str(msg.get("error")))
            return []
        if msg.get("channel") != "ticker":
            return []
        out = []
        for d in msg.get("data") or []:
            if d.get("symbol") in self.symbols and d.get("bid") is not None and d.get("ask") is not None:
                out.append(Tick(self.symbols[d["symbol"]], self.name, d["symbol"], now, now, float(d["bid"]), float(d["ask"]),
                                float(d["last"]) if d.get("last") is not None else None, time_basis="receive"))
        return out


ADAPTERS = {"deriv": Deriv, "kraken": Kraken}


async def deriv_history(symbol: str, granularity: int, count: int) -> list[tuple]:
    """Deriv's own candles (from the mid quote) — the history the live candles continue: [(t, o, h, l, c), …] oldest first."""
    import websockets

    async with websockets.connect(Deriv.url, open_timeout=20, max_size=2 ** 24) as ws:
        await ws.send(json.dumps({"ticks_history": symbol, "style": "candles", "granularity": granularity, "end": "latest",
                                  "count": count}))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 30))
            if msg.get("error"):
                raise RuntimeError(f"{msg['error'].get('code')}: {msg['error'].get('message')}")
            if msg.get("msg_type") == "candles":
                return [(int(c["epoch"]), float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"]))
                        for c in msg.get("candles") or []]
