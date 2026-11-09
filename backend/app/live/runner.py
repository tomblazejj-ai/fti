"""The live engine in its own thread with its own event loop — inside the FastAPI app (settings live.enabled) or alone:

    python -m app.live.runner --seconds 600      (DATABASE_URL must point to a COPY: the runner refuses the live fti.db)

Startup: each provider's own stored candles (bid) seed the candles, then the streams run. Every FLUSH_S the changed
candles go to the database and the finished ticks to the hourly files (never ticks into the database — brief 9. 11.);
every HEALTH_S each provider is reported to FTI's source monitoring (Data page). One provider failing never stops the
others or the app.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import logging
import os
import threading
import time

from app.live import ctrader, providers, storage  # noqa: F401 — ctrader registers its adapter
from app.live.engine import LiveEngine
from app.live import instruments as live_instruments
from app.live.instruments import TIMEFRAMES

log = logging.getLogger(__name__)
FLUSH_S, HEALTH_S = 10.0, 60.0
NAMES = {"deriv": "Deriv — živé kotace (veřejný WebSocket)", "kraken": "Kraken — živé nabídky EUR/USD (WebSocket)",
         "ctrader": "Purple Trading cTrader — živé kotace brokera (Open API)"}
SEED_DAYS = {"M1": 2, "M5": 7, "M15": 14, "M30": 21, "H1": 60, "H4": 120, "D1": 400}  # own stored candles at startup
_runner: "Runner | None" = None


class Runner:
    def __init__(self, engine: LiveEngine | None = None, session_factory=None, backfill: bool = True, store: bool = True,
                 tick_dir=None):
        self.engine = engine or LiveEngine(live_instruments.current())
        self.session_factory = session_factory
        self.backfill, self.store, self.tick_dir = backfill, store, tick_dir
        self.providers: dict[str, providers.Provider] = {}
        insts = tuple(self.engine.instruments.values())
        for name, cls in providers.ADAPTERS.items():
            symbols = {f.symbol: i.code for i in insts for f in i.feeds if f.provider == name}
            if symbols:
                self.providers[name] = cls(symbols, host=_ctrader_host()) if name == "ctrader" else cls(symbols)
        self.stats = {"candles_stored": 0, "ticks_stored": 0, "flushes": 0, "seeded": {}, "write_errors": 0}
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self.engine.connected = lambda name: self.providers[name].metrics.connected if name in self.providers else False

    # --- lifecycle ---------------------------------------------------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=lambda: asyncio.run(self._main()), name="fti-live", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 15) -> None:
        if self._loop and self._stop:
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread:
            self._thread.join(timeout)

    async def _main(self) -> None:
        self._loop, self._stop = asyncio.get_running_loop(), asyncio.Event()
        if self.backfill:
            await self._seed()
        tasks = [asyncio.create_task(p.run(self.engine.on_tick, self._stop)) for p in self.providers.values()]
        tasks += [asyncio.create_task(self._every(FLUSH_S, self._flush)), asyncio.create_task(self._every(HEALTH_S, self._health))]
        await self._stop.wait()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self._flush(final=True)  # what arrived last is stored too, including the minute being filled

    async def _every(self, seconds: float, fn) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=seconds)
            except asyncio.TimeoutError:
                await fn()

    async def _seed(self) -> None:
        """Each provider's OWN stored candles (from the bid, never another provider's): the live candles continue them,
        and the change is measured against the provider's own previous close."""
        if self.session_factory is None:
            return
        await asyncio.get_running_loop().run_in_executor(None, self._seed_from_db)

    def _seed_from_db(self) -> None:
        now = int(time.time())
        session = self.session_factory()
        try:
            for inst in self.engine.instruments.values():
                for f in inst.feeds:
                    if not f.store_candles:
                        continue
                    for tf in TIMEFRAMES:
                        rows = storage.load_own_candles(session, inst.code, f.provider, tf, now - SEED_DAYS[tf] * 86400)
                        self.stats["seeded"][f"{inst.code} {tf} {f.provider}"] = self.engine.seed(inst.code, f.provider, tf, rows)
        except Exception:  # noqa: BLE001 — without stored candles the live candles simply start now
            log.exception("live: seeding from stored candles failed")
        finally:
            session.close()

    async def _flush(self, final: bool = False) -> None:
        drained = self.engine.drain(final=final)
        if not self.store or self.session_factory is None or not (drained["candles"] or drained["ticks"]):
            return
        await asyncio.get_running_loop().run_in_executor(None, self._write, drained)

    def _write(self, drained: dict) -> None:
        session = self.session_factory()
        try:
            self.stats["candles_stored"] += storage.save_candles(session, drained["candles"])
            session.commit()
            self.stats["ticks_stored"] += storage.save_ticks(drained["ticks"], self.tick_dir)  # files, never the DB
            if self.stats["flushes"] % 360 == 0:
                storage.prune_ticks(dt.datetime.now(dt.timezone.utc), self.tick_dir)
            self.stats["flushes"] += 1
        except Exception as exc:  # noqa: BLE001 — storing must never stop the stream; what failed is stored next time
            session.rollback()
            self.engine.requeue(drained)
            self.stats["write_errors"] += 1
            self.stats["last_write_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            log.warning("live: storing failed, retried at the next flush: %s", exc)
        finally:
            session.close()

    async def _health(self) -> None:
        from app.data import health

        now = time.time()
        for name, p in self.providers.items():
            v = p.metrics.view(now)
            ok = v["connected"] and v["last_message_age_s"] is not None and v["last_message_age_s"] < 60
            health.record(f"live:{name}", NAMES.get(name, name), ok=ok,
                          ms=(v["latency_median_s"] or 0) * 1000 if v["latency_median_s"] is not None else None,
                          records=v["ticks"], error=None if ok else ((v["errors"] or [{}])[-1].get("error") or "bez spojení"),
                          quality="LIVE" if ok else None, expected="LIVE")

    def health(self) -> dict:
        now = time.time()
        return {"providers": [p.metrics.view(now) for p in self.providers.values()], "events": list(self.engine.events)[-20:],
                "stats": self.stats, "running_for_s": round(now - self.engine.started)}


def _ctrader_host() -> str:
    from app.data import settings_store

    return "live" if (settings_store.get("live", {}) or {}).get("ctrader_host") == "live" else "demo"


def get() -> Runner | None:
    return _runner


def start(session_factory=None) -> Runner:
    global _runner
    if _runner is None:
        if session_factory is None:
            from app.db import SessionLocal as session_factory  # noqa: N813
        _runner = Runner(session_factory=session_factory)
        _runner.start()
    return _runner


def stop() -> None:
    global _runner
    if _runner is not None:
        _runner.stop()
        _runner = None


def main() -> int:
    ap = argparse.ArgumentParser(description="FTI LIVE engine alone, on a COPY of the database.")
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--no-store", action="store_true")
    args = ap.parse_args()
    from app.config import settings

    if "scratchpad" not in settings.database_url and not os.environ.get("FTI_LIVE_ALLOW_DB"):
        raise SystemExit(f"Odmítnuto: DATABASE_URL ukazuje na {settings.database_url} — test jen na kopii databáze.")
    from app.db import SessionLocal

    r = Runner(session_factory=SessionLocal, store=not args.no_store)
    r.start()
    end = time.time() + args.seconds
    while time.time() < end:
        time.sleep(min(30, max(0.5, end - time.time())))
        snap = r.engine.snapshot()
        print(time.strftime("%H:%M:%S"), " | ".join(f"{q['label']} {q['status']} {q.get('mid')} ({q.get('age_s')} s)"
                                                     for q in snap["instruments"]), flush=True)
    r.stop()
    print(json.dumps({"health": r.health(), "snapshot": r.engine.snapshot()}, ensure_ascii=False, default=str, indent=1))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    raise SystemExit(main())
