"""LIVE terminal API — reads the live engine (app/live), never starts or changes it.

  GET /api/live/snapshot          every live instrument: state, bid, ask, spread, mid, quote time, age, source, change
  GET /api/live/stream            the same as Server-Sent Events: a new event when a price changes (at most 4 a second)
  GET /api/live/candles           candles M1 … D1 of the active provider (built from its ticks, its own history before)
  GET /api/live/health            providers: connection, messages, latency, errors; failover events; what was stored
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.live import runner
from app.live.instruments import TIMEFRAMES

router = APIRouter(prefix="/api/live", tags=["live"])
OFF = "Živá data jsou vypnutá (Nastavení → LIVE). Ceny jinde v aplikaci jsou z periodických zdrojů se svým štítkem kvality."


def _runner():
    r = runner.get()
    if r is None:
        raise HTTPException(status_code=503, detail=OFF)
    return r


@router.get("/snapshot")
def snapshot():
    r = _runner()
    return {**r.engine.snapshot(), "running": True}


@router.get("/stream")
async def stream(events: int = 0):
    """events > 0: end after that many events (diagnostics, tests); 0 = until the client leaves."""
    r = _runner()

    async def gen():
        version, quiet, sent = -1, 0.0, 0
        while runner.get() is r and (events <= 0 or sent < events):
            if r.engine.version != version:
                version = r.engine.version
                yield f"data: {json.dumps({**r.engine.snapshot(), 'running': True}, ensure_ascii=False)}\n\n"
                sent += 1
                quiet = 0.0
            else:
                quiet += 0.25
                if quiet >= 15:  # a comment keeps proxies and the browser from closing an idle stream
                    yield ": keepalive\n\n"
                    quiet = 0.0
            await asyncio.sleep(0.25)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/candles")
def candles(code: str = "XAUUSD", tf: str = "M1", limit: int = 300):
    r = _runner()
    code, tf = code.upper(), tf.upper()
    if code not in r.engine.instruments:
        raise HTTPException(status_code=404, detail=f"{code} není v živém terminálu (zatím XAUUSD, EURUSD, US500, NAS100).")
    if tf not in TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"Timeframe jen {', '.join(TIMEFRAMES)}.")
    provider, rows = r.engine.series(code, tf, max(10, min(limit, 2000)))
    feed = next((f for f in r.engine.instruments[code].feeds if f.provider == provider), None)
    return {"code": code, "tf": tf, "provider": provider, "product": feed.product if feed else None,
            "price_type": feed.price_type if feed else None, "candles": [[int(t), o, h, lo, c] for t, o, h, lo, c in rows],
            "quote": r.engine.quote(code)}


@router.get("/health")
def health():
    return _runner().health()
