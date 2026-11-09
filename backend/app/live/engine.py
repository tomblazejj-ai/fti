"""The live engine: ticks in → state of every instrument, failover, candles, tick blocks, change against the previous
close. Pure logic (no network, no database) — the runner feeds it ticks and stores what it hands out, tests drive it
with a clock of their own.

State of an instrument (shown with every price, and the AI may call a price live only when it is LIVE):
  LIVE         the active provider's quote is at most LIVE_MAX_AGE old
  DELAYED      no live quote although the market is open: the last quote is at most DELAYED_MAX_AGE old
  HISTORICAL   the market is closed, the provider does not quote now (its session), or the last quote is older —
               the price shown is the last one, with its time
  UNAVAILABLE  nothing at all
Failover: the primary provider first; a backup takes over only while it is live AND its prices were proven compatible
with the primary's on simultaneous quotes (at least COMPAT_MIN_PAIRS pairs, median |difference| ≤ the instrument's
tolerance). Prices are never shifted by the measured offset — the offset only decides whether the backup may stand in.
"""

from __future__ import annotations

import collections
import datetime as dt
import statistics
import threading
import time

from app.connectors.dukascopy import bucket
from app.data import market_hours, universe
from app.live.instruments import (BANNER, COMPAT_MIN_PAIRS, COMPAT_PAIR_GAP, DELAYED_MAX_AGE, INSTRUMENTS, JUMP_ATR,
                                  JUMP_CONFIRM, LIVE_MAX_AGE, TIMEFRAMES, DERIVED, LiveInstrument)
from app.live.providers import Tick

UTC = dt.timezone.utc
STATUS_CS = {"LIVE": "živě", "DELAYED": "zpožděno", "HISTORICAL": "historická cena", "UNAVAILABLE": "nedostupné"}
KEEP_BARS = 2000  # per timeframe and provider in memory (the database keeps the rest)


class CandleSet:
    """Candles of ONE provider for one instrument on the broker's grid, from its own ticks (and its own history)."""

    def __init__(self):
        self.bars: dict[str, dict[int, list[float]]] = {tf: {} for tf in TIMEFRAMES}
        self.dirty: dict[str, set[int]] = {tf: set() for tf in TIMEFRAMES}

    def update(self, t: float, price: float) -> None:
        for tf, sec in TIMEFRAMES.items():
            k = bucket(int(t), sec)
            bars = self.bars[tf]
            b = bars.get(k)
            if b is None:
                if bars and k < max(bars) - 30 * sec:
                    continue  # a very late tick: never rewrite old history
                bars[k] = [price, price, price, price]
                if len(bars) > KEEP_BARS:
                    for old in sorted(bars)[: len(bars) - KEEP_BARS]:
                        bars.pop(old)
                        self.dirty[tf].discard(old)
            else:
                b[1], b[2], b[3] = max(b[1], price), min(b[2], price), price
            self.dirty[tf].add(k)

    def seed(self, tf: str, rows: list[tuple]) -> int:
        """History from the provider itself, only where no live candle exists yet."""
        bars, n = self.bars[tf], 0
        first_live = min(bars) if bars else None
        for t, o, h, lo, c, *_ in rows:
            if first_live is None or t < first_live:
                bars[t] = [o, h, lo, c]
                n += 1
        return n

    def series(self, tf: str, limit: int = 500) -> list[tuple]:
        bars = self.bars[tf]
        return [(t, *bars[t]) for t in sorted(bars)[-limit:]]


def aggregate(rows: list[tuple], sec: int) -> list[tuple]:
    """Finer candles (oldest first) → candles of `sec` seconds on the broker's grid."""
    out: dict[int, list[float]] = {}
    for t, o, h, lo, c, *_ in rows:
        k = bucket(int(t), sec)
        b = out.get(k)
        out[k] = [o, h, lo, c] if b is None else [b[0], max(b[1], h), min(b[2], lo), c]
    return [(k, *v) for k, v in sorted(out.items())]


def whole_history(rows: list[tuple], src_sec: int, sec: int) -> list[tuple]:
    """A provider's history window → only whole candles: a source candle that does not start on its grid was cut by
    the window's edge (Deriv's first H1 started at 17:21:15), and so is the first aggregated candle when the history
    begins after its start — both are left out, never shown with a wrong open, high or low (the rule of Ú1)."""
    src = [r for r in rows if int(r[0]) % src_sec == 0]
    if sec == src_sec or not src:
        return src
    agg = aggregate(src, sec)
    return agg[1:] if agg and int(src[0][0]) > agg[0][0] else agg


class Compat:
    """Simultaneous quotes of the primary and one backup provider: may the backup stand in for the primary?"""

    def __init__(self, tolerance: float):
        self.tolerance = tolerance
        self.diffs: collections.deque = collections.deque(maxlen=600)
        self.last_pair = 0.0

    def add(self, diff: float, at: float) -> None:
        if at - self.last_pair >= 1.0:  # at most one pair a second: a chatty feed must not outvote time
            self.diffs.append(diff)
            self.last_pair = at

    def view(self) -> dict:
        d = list(self.diffs)
        if not d:
            return {"pairs": 0, "ok": False, "text": "zatím žádné souběžné kotace"}
        med_abs = statistics.median(abs(x) for x in d)
        ok = len(d) >= COMPAT_MIN_PAIRS and med_abs <= self.tolerance
        return {"pairs": len(d), "median_abs": round(med_abs, 6), "offset": round(statistics.median(d), 6), "tolerance": self.tolerance,
                "ok": ok, "text": (f"shoda ověřena na {len(d)} souběžných kotacích (medián rozdílu {med_abs:.5g} ≤ {self.tolerance:g})" if ok else
                                   f"shoda neověřena: {len(d)} souběžných kotací, medián rozdílu {med_abs:.5g}, povoleno {self.tolerance:g}"
                                   + (f", potřeba aspoň {COMPAT_MIN_PAIRS}" if len(d) < COMPAT_MIN_PAIRS else ""))}


class LiveEngine:
    def __init__(self, instruments: tuple[LiveInstrument, ...] | None = None, clock=time.time):
        instruments = instruments or INSTRUMENTS
        self.instruments = {i.code: i for i in instruments}
        self.clock = clock
        self._lock = threading.RLock()
        self.last: dict[tuple[str, str], Tick] = {}
        self.candles: dict[tuple[str, str], CandleSet] = collections.defaultdict(CandleSet)
        self.compat: dict[tuple[str, str], Compat] = {}
        self.blocks: dict[tuple[str, str, int], list] = {}
        self.ready_blocks: list[tuple[str, str, int, list]] = []
        self.active: dict[str, str | None] = {}
        self.events: collections.deque = collections.deque(maxlen=200)
        self.version = 0
        self.started = clock()
        self._market_cache: dict[str, tuple[float, str]] = {}
        self.rejected: dict[tuple[str, str], collections.deque] = collections.defaultdict(lambda: collections.deque(maxlen=20))
        self.rejected_count: collections.Counter = collections.Counter()
        self._jumps: dict[tuple[str, str], int] = {}
        self.connected = lambda provider: True  # the runner tells whether a provider's connection is up
        for inst in instruments:
            for f in inst.feeds:
                if f.role == "backup":
                    self.compat[(inst.code, f.provider)] = Compat(inst.tolerance)

    # --- input -----------------------------------------------------------------------------------------------------
    def _invalid(self, inst: LiveInstrument, tick: Tick) -> str | None:
        """Why a quote is not a valid price (brief: bid > 0, ask ≥ bid, a sane spread, no jump beyond 5 × ATR(M1))."""
        if tick.bid is None or tick.ask is None or tick.bid != tick.bid or tick.ask != tick.ask:
            return "chybí bid nebo ask"
        if tick.bid <= 0 or tick.ask <= 0:
            return f"cena ≤ 0 (bid {tick.bid}, ask {tick.ask})"
        if tick.ask < tick.bid:
            return f"ask {tick.ask} < bid {tick.bid}"
        if inst.max_spread and tick.ask - tick.bid > inst.max_spread:
            return f"spread {tick.ask - tick.bid:.6g} > {inst.max_spread:g}"
        prev = self.last.get((tick.code, tick.provider))
        if prev is not None and prev.mid is not None and tick.t - prev.t <= 60:  # after a pause (reopen) a gap is normal
            m1 = self.candles[(tick.code, tick.provider)].series("M1", 16)[:-1]
            if len(m1) >= 14:
                atr = sum(h - lo for _, _, h, lo, _ in m1[-14:]) / 14
                key = (tick.code, tick.provider)
                if atr > 0 and abs(tick.mid - prev.mid) > JUMP_ATR * atr:
                    self._jumps[key] = self._jumps.get(key, 0) + 1
                    if self._jumps[key] < JUMP_CONFIRM:
                        return f"skok {abs(tick.mid - prev.mid):.6g} > {JUMP_ATR:g} × ATR(M1) {atr:.6g}"
                self._jumps.pop(key, None)
        return None

    def on_tick(self, tick: Tick) -> None:
        inst = self.instruments.get(tick.code)
        if inst is None or tick.mid is None:
            return
        with self._lock:
            feed = next((f for f in inst.feeds if f.provider == tick.provider), None)
            if feed is None:
                return
            why = self._invalid(inst, tick)
            if why is not None:  # dropped and logged, never a price
                self.rejected[(tick.code, tick.provider)].append({"at": tick.recv, "reason": why})
                self.rejected_count[(tick.code, tick.provider)] += 1
                return
            self.last[(tick.code, tick.provider)] = tick
            price = tick.bid if feed.price_type == "bid" and tick.bid is not None else tick.mid
            self.candles[(tick.code, tick.provider)].update(tick.t, price)
            minute = int(tick.t) - int(tick.t) % 60
            key = (tick.code, tick.provider, minute)
            for k in [k for k in self.blocks if k[:2] == key[:2] and k[2] < minute]:  # the previous minute is complete
                self.ready_blocks.append((*k, self.blocks.pop(k)))
            self.blocks.setdefault(key, []).append([round(tick.t - minute, 3), tick.bid, tick.ask, tick.last])
            self._pair(inst, tick)
            self.version += 1

    def _pair(self, inst: LiveInstrument, tick: Tick) -> None:
        primary = inst.feeds[0].provider
        for f in inst.feeds[1:]:
            if f.role != "backup":
                continue
            other = f.provider if tick.provider == primary else primary if tick.provider == f.provider else None
            if other is None:
                continue
            o = self.last.get((inst.code, other))
            if o is None or abs(o.recv - tick.recv) > COMPAT_PAIR_GAP or o.mid is None:
                continue
            b, p = (tick, o) if tick.provider == f.provider else (o, tick)
            self.compat[(inst.code, f.provider)].add(b.mid - p.mid, tick.recv)

    def seed(self, code: str, provider: str, tf: str, rows: list[tuple]) -> int:
        with self._lock:
            n = self.candles[(code, provider)].seed(tf, rows)
            self.version += 1
            return n

    # --- state -----------------------------------------------------------------------------------------------------
    def _market_state(self, code: str, now: float) -> str:
        """MARKET STATUS from the instrument's schedule (FTI's trading calendar) — never from whether data arrive."""
        cached = self._market_cache.get(code)
        if cached and now - cached[0] < 30:
            return cached[1]
        inst = universe.get(code)
        state = market_hours.state(inst, dt.datetime.fromtimestamp(now, UTC)).get("state") if inst else market_hours.UNKNOWN
        self._market_cache[code] = (now, state)
        return state

    def _market_open(self, code: str, now: float) -> bool:
        return self._market_state(code, now) == market_hours.OPEN

    @staticmethod
    def _in_session(feed, now: float) -> bool:
        if not feed.sessions_utc:
            return True
        h = dt.datetime.fromtimestamp(now, UTC).hour
        a, z = feed.sessions_utc
        return a <= h < z

    def quote(self, code: str, now: float | None = None) -> dict:
        now = now or self.clock()
        inst = self.instruments[code]
        with self._lock:
            rows, active, failover = [], None, False
            for f in inst.feeds:
                tick = self.last.get((code, f.provider))
                age = (now - tick.t) if tick else None
                fresh = age is not None and age <= LIVE_MAX_AGE
                comp = self.compat.get((code, f.provider))
                rows.append({"provider": f.provider, "symbol": f.symbol, "role": f.role, "product": f.product,
                             "age_s": round(age, 1) if age is not None else None, "fresh": fresh,
                             "in_session": self._in_session(f, now), "compat": comp.view() if comp else None})
            primary = inst.feeds[0]
            if rows[0]["fresh"]:
                active = primary
            else:
                for f, r in zip(inst.feeds[1:], rows[1:]):
                    if f.role == "backup" and r["fresh"] and r["compat"]["ok"]:
                        active, failover = f, True
                        break
            notes: list[str] = []
            market = self._market_state(code, now)
            if active is not None:
                status, shown = "LIVE", active
            else:
                # DATA STATUS (brief): UNAVAILABLE = no connection / nothing at all, DELAYED = connected but the last quote
                # is older than LIVE, HISTORICAL = only the last stored price (old quote or stored candles)
                shown = primary if self.last.get((code, primary.provider)) else None
                tick = self.last.get((code, primary.provider))
                if tick is None and not self._last_close(code, primary.provider):
                    status = "UNAVAILABLE"
                elif not self.connected(primary.provider):
                    status = "UNAVAILABLE"
                    notes.append(f"Spojení se zdrojem {primary.provider} teď není — cena je poslední známá.")
                elif tick is not None and now - tick.t <= DELAYED_MAX_AGE:
                    status = "DELAYED"
                    notes.append(f"Poslední kotace je {now - tick.t:.0f} s stará — zdroj teď nedodává.")
                else:
                    status = "HISTORICAL"
                if market != market_hours.OPEN:
                    notes.append("Trh je teď zavřený — cena je poslední kotace před zavřením.")
                elif not self._in_session(primary, now):
                    notes.append(f"{primary.provider.capitalize()} kotuje {inst.label} jen {primary.sessions_utc[0]}–"
                                 f"{primary.sessions_utc[1]} h UTC; trh CFD je otevřený, ale živá cena teď chybí.")
                for f, r in zip(inst.feeds[1:], rows[1:]):
                    if f.role == "backup" and r["fresh"] and not r["compat"]["ok"]:
                        notes.append(f"Záloha {f.provider} je živá, ale nepřevezme ji: {r['compat']['text']}.")
            prev = self.active.get(code)
            now_active = active.provider if active else None
            if prev != now_active and (code in self.active or now_active is not None):
                self.events.append({"at": now, "code": code, "from": prev, "to": now_active, "status": status})
            self.active[code] = now_active
            tick = self.last.get((code, shown.provider)) if shown else None
            out = {"code": code, "label": inst.label, "name": inst.name, "kind": inst.kind, "digits": inst.digits,
                   "status": status, "data_status": status, "status_cs": STATUS_CS[status],
                   "market_status": market, "market_status_cs": market_hours.LABELS_CS.get(market, market),
                   "banner": BANNER if market == market_hours.OPEN and status != "LIVE" else None,
                   "failover": failover, "notes": notes, "providers": rows}
            if tick is not None:
                prev_close, prev_day = self._prev_close(code, shown.provider, tick.t)
                mid = tick.mid
                out.update({"provider": shown.provider, "symbol": shown.symbol, "product": shown.product,
                            "price_type": shown.price_type, "bid": tick.bid, "ask": tick.ask,
                            "spread": round(tick.ask - tick.bid, 6) if tick.bid is not None and tick.ask is not None else None,
                            "mid": round(mid, 6), "last_trade": tick.last, "time_basis": tick.time_basis,
                            "quote_time": dt.datetime.fromtimestamp(tick.t, UTC).isoformat(),
                            "received_at": dt.datetime.fromtimestamp(tick.recv, UTC).isoformat(), "age_s": round(now - tick.t, 1),
                            "prev_close": prev_close, "prev_close_day": prev_day,
                            "change": round(mid - prev_close, 6) if prev_close else None,
                            "change_pct": round(100 * (mid / prev_close - 1), 3) if prev_close else None})
            else:
                close = self._last_close(code, primary.provider)
                if close:
                    out.update({"provider": primary.provider, "product": primary.product, "mid": close[1],
                                "quote_time": dt.datetime.fromtimestamp(close[0], UTC).isoformat(), "price_type": primary.price_type})
                    notes.append("Žádná živá kotace od spuštění — cena je poslední uložený závěr svíčky.")
            return out

    def _prev_close(self, code: str, provider: str, t: float) -> tuple[float | None, str | None]:
        """The close of the previous trading day of the SAME provider (never across two sources)."""
        d1 = self.candles[(code, provider)].bars["D1"]
        today = bucket(int(t), 86400)
        older = [k for k in d1 if k < today]
        if not older:
            return None, None
        k = max(older)
        return d1[k][3], market_hours.trading_date(k).isoformat()

    def _last_close(self, code: str, provider: str) -> tuple[int, float] | None:
        m1 = self.candles[(code, provider)].bars["M1"]
        if not m1:
            return None
        k = max(m1)
        return k, m1[k][3]

    def snapshot(self, now: float | None = None) -> dict:
        now = now or self.clock()
        return {"version": self.version, "at": dt.datetime.fromtimestamp(now, UTC).isoformat(),
                "instruments": [self.quote(c, now) for c in self.instruments]}

    def series(self, code: str, tf: str, limit: int = 500, provider: str | None = None) -> tuple[str | None, list[tuple]]:
        inst = self.instruments[code]
        with self._lock:
            provider = provider or self.active.get(code) or inst.feeds[0].provider
            if tf in DERIVED:  # W1 / MN1: the engine's D1 candles grouped on the broker's grid
                daily = self.candles[(code, provider)].series("D1", 100000)
                return provider, aggregate(daily, DERIVED[tf])[-limit:]
            return provider, self.candles[(code, provider)].series(tf, limit)

    # --- what the runner stores --------------------------------------------------------------------------------------
    def requeue(self, drained: dict) -> None:
        """A write that failed (e.g. the database was busy with FTI's data cycle) hands its candles and tick blocks
        back: the next flush stores them — the newest values of those candles, the ticks merged, nothing doubled."""
        with self._lock:
            for g in drained["candles"]:
                cs = self.candles[(g["code"], g["provider"])]
                cs.dirty[g["tf"]].update(r[0] for r in g["rows"] if r[0] in cs.bars[g["tf"]])
            self.ready_blocks = list(drained["ticks"]) + self.ready_blocks

    def drain(self, now: float | None = None, final: bool = False) -> dict:
        """Candles changed since the last call (closed and forming) and finished one-minute tick blocks (final: also
        the minute still being filled — when the engine stops)."""
        now = now or self.clock()
        out = {"candles": [], "ticks": []}
        with self._lock:
            for (code, provider), cs in self.candles.items():
                feed = next((f for f in self.instruments[code].feeds if f.provider == provider), None)
                if feed is None or not feed.store_candles:
                    for tf in cs.dirty:
                        cs.dirty[tf].clear()
                    continue
                for tf, keys in cs.dirty.items():
                    if keys:
                        rows = [(k, *cs.bars[tf][k]) for k in sorted(keys) if k in cs.bars[tf]]
                        out["candles"].append({"code": code, "provider": provider, "tf": tf, "symbol": feed.symbol,
                                               "product": feed.product, "price_type": feed.price_type, "rows": rows,
                                               "complete_until": (self.last[(code, provider)].t
                                                                  if (code, provider) in self.last else None)})
                        keys.clear()
            for k in [k for k in self.blocks if final or now - k[2] > 70]:  # a minute nobody continued (feed stopped)
                self.ready_blocks.append((*k, self.blocks.pop(k)))
            out["ticks"], self.ready_blocks = self.ready_blocks, []
        return out


def quote_for_ai(engine: LiveEngine | None, code: str) -> dict | None:
    return engine.quote(code) if engine is not None and code in engine.instruments else None


def signal_allowed(engine: LiveEngine | None, code: str) -> tuple[bool | None, str]:
    """The AI gate: a valid LONG / SHORT only with a LIVE price. None = the live engine does not run (unchanged behaviour)."""
    q = quote_for_ai(engine, code)
    if q is None:
        return None, "živý engine neběží"
    if q["status"] == "LIVE":
        return True, f"živá cena {q.get('provider')} ({q.get('age_s')} s)"
    return False, (f"Cena {code} teď není živá ({q['status_cs']}" + (f", poslední kotace {q.get('quote_time')}" if q.get("quote_time") else "")
                   + ") — FTI bez živé ceny nevydává obchodní signál.")

