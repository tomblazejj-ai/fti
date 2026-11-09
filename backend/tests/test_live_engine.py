"""FTI LIVE DATA ENGINE (9. 11. 2026, test version): normalised ticks → state LIVE / DELAYED / HISTORICAL / UNAVAILABLE,
failover only to a backup proven compatible on simultaneous quotes, candles M1 … D1 on the broker's grid from the
provider's own ticks and history, tick blocks without duplicates, change against the previous close of the SAME
provider, monitoring, the API, and the AI gate: no LIVE price → no valid LONG / SHORT. No network: a clock of our own."""

import datetime as dt
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.data import market_hours, store
from app.db import Base
from app.live import engine as live_engine, providers, runner, storage
from app.live.engine import LiveEngine
from app.live.providers import Tick

UTC = dt.timezone.utc
WED = dt.datetime(2026, 11, 4, 12, 0, tzinfo=UTC).timestamp()  # Wednesday noon: every market open
REAL_SAVE = store.save_bars


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def tick(code, provider, t, bid, ask, sym=None, basis="quote"):
    return Tick(code, provider, sym or code, t, t + 0.3, bid, ask, None, basis)


@pytest.fixture()
def eng():
    clock = Clock(WED)
    return LiveEngine(clock=clock), clock


# --- state -------------------------------------------------------------------------------------------------------------

def test_state_follows_the_age_of_the_quote(eng):
    e, clock = eng
    assert e.quote("XAUUSD")["status"] == "UNAVAILABLE"  # nothing at all
    e.on_tick(tick("XAUUSD", "deriv", WED, 4096.0, 4096.58))
    q = e.quote("XAUUSD", WED + 1)
    assert (q["status"], q["provider"], q["bid"], q["ask"], q["spread"]) == ("LIVE", "deriv", 4096.0, 4096.58, 0.58)
    assert q["mid"] == pytest.approx(4096.29) and q["quote_time"].startswith("2026-11-04T12:00:00") and "Deriv" in q["product"]
    q = e.quote("XAUUSD", WED + 20)
    assert q["status"] == "DELAYED" and "20 s stará" in q["notes"][0]
    assert e.quote("XAUUSD", WED + 16 * 60)["status"] == "HISTORICAL"
    sat = dt.datetime(2026, 11, 7, 12, tzinfo=UTC).timestamp()
    q = e.quote("XAUUSD", sat)
    assert q["status"] == "HISTORICAL" and "zavřený" in q["notes"][0] and q["bid"] == 4096.0  # the last price, with its time


def test_index_cfd_outside_the_providers_session_is_never_live():
    """Deriv quotes US 500 only 6–21 h UTC; the CFD market is open 23 h — outside the session the price is historical
    (measured 9. 11.: at the close hour Deriv froze while Purple's US100 moved 338 points)."""
    night = dt.datetime(2026, 11, 4, 2, 30, tzinfo=UTC).timestamp()
    e = LiveEngine(clock=Clock(night))
    e.on_tick(tick("US500.CFD", "deriv", night - 5 * 3600, 7409.6, 7410.0, "OTC_SPC"))
    q = e.quote("US500.CFD", night)
    assert q["status"] == "HISTORICAL" and "jen 6–21 h UTC" in q["notes"][0] and "ne index sám" in q["product"]


# --- failover ---------------------------------------------------------------------------------------------------------

def _both(e, start, n, kraken_offset):
    for i in range(n):
        t = start + i
        e.on_tick(tick("EURUSD", "deriv", t, 1.11858, 1.11866, "frxEURUSD"))
        e.on_tick(Tick("EURUSD", "kraken", "EUR/USD", t + 0.2, t + 0.2, 1.11858 + kraken_offset, 1.11866 + kraken_offset,
                       None, "receive"))


def test_a_backup_takes_over_only_after_its_prices_were_proven_compatible(eng):
    e, _ = eng
    _both(e, WED, 10, 0.00002)  # compatible but too few simultaneous quotes yet
    e.on_tick(Tick("EURUSD", "kraken", "EUR/USD", WED + 30, WED + 30, 1.1186, 1.11868, None, "receive"))
    q = e.quote("EURUSD", WED + 30.5)
    assert q["status"] == "DELAYED" and q["failover"] is False
    assert any("nepřevezme" in n and "potřeba aspoň 30" in n for n in q["notes"])
    _both(e, WED + 40, 40, 0.00002)  # now 50 pairs, median difference 0.2 pip ≤ 1.5 pip
    e.on_tick(Tick("EURUSD", "kraken", "EUR/USD", WED + 100, WED + 100, 1.1186, 1.11868, None, "receive"))
    q = e.quote("EURUSD", WED + 100.5)  # Deriv silent for 21 s, Kraken live and compatible
    assert (q["status"], q["provider"], q["failover"]) == ("LIVE", "kraken", True) and q["time_basis"] == "receive"
    assert e.quote("EURUSD", WED + 100.5)["providers"][1]["compat"]["ok"]
    e.on_tick(tick("EURUSD", "deriv", WED + 101, 1.1186, 1.11868, "frxEURUSD"))
    assert e.quote("EURUSD", WED + 101.5)["provider"] == "deriv"  # the primary back → it is used again
    # every change of the price's source is logged: none (Deriv silent, Kraken not yet proven) → Kraken → Deriv again
    assert [(x["from"], x["to"]) for x in e.events if x["code"] == "EURUSD"] == [(None, "kraken"), ("kraken", "deriv")]


def test_an_incompatible_backup_never_stands_in(eng):
    """Kraken's EUR/USD differed from the broker by 2 pips (median, 9. 11.) — it must not replace the price."""
    e, _ = eng
    _both(e, WED, 60, 0.0003)
    e.on_tick(Tick("EURUSD", "kraken", "EUR/USD", WED + 90, WED + 90, 1.119, 1.11908, None, "receive"))
    q = e.quote("EURUSD", WED + 90.5)
    assert q["status"] == "DELAYED" and q["provider"] == "deriv" and not q["failover"]
    assert any("shoda neověřena" in n for n in q["notes"])


# --- candles, ticks, change ---------------------------------------------------------------------------------------------

def test_candles_on_the_broker_grid_from_ticks(eng):
    e, _ = eng
    day_start = market_hours.trading_day_start(int(WED))  # 3. 11. 22:00 UTC (EST)
    prices = [(WED, 4000.0), (WED + 30, 4005.0), (WED + 61, 3995.0), (WED + 3600, 4010.0), (day_start + 86400 + 5, 4020.0)]
    for t, p in prices:
        e.on_tick(tick("XAUUSD", "deriv", t, p - 0.25, p + 0.25))
    _, m1 = e.series("XAUUSD", "M1")
    assert m1[0] == (int(WED), 3999.75, 4004.75, 3999.75, 4004.75) and m1[1][0] == int(WED) + 60  # from the bid
    _, d1 = e.series("XAUUSD", "D1")
    assert [r[0] for r in d1] == [day_start, day_start + 86400]  # 17:00 New York, the next day from Wednesday 22:00 UTC
    assert d1[0][1:] == (3999.75, 4009.75, 3994.75, 4009.75)
    _, h4 = e.series("XAUUSD", "H4")
    assert all((r[0] - market_hours.trading_day_start(r[0])) % 14400 == 0 for r in h4)
    drained = e.drain(WED + 90000)
    groups = {(g["tf"]): g for g in drained["candles"] if g["provider"] == "deriv"}
    assert set(groups) == {"M1", "M5", "M15", "M30", "H1", "H4", "D1"} and groups["D1"]["price_type"] == "bid"
    assert not e.drain(WED + 90001)["candles"]  # handed out once
    assert sum(len(b[3]) for b in drained["ticks"]) == 5  # every tick in its minute block


def test_change_is_against_the_previous_close_of_the_same_provider(eng):
    e, _ = eng
    today = market_hours.trading_day_start(int(WED))
    e.seed("XAUUSD", "deriv", "D1", [(today - 86400, 4050.0, 4100.0, 4040.0, 4080.0)])
    e.on_tick(tick("XAUUSD", "deriv", WED, 4095.75, 4096.25))
    q = e.quote("XAUUSD", WED + 1)
    assert (q["prev_close"], q["prev_close_day"]) == (4080.0, "2026-11-03")
    assert q["change"] == pytest.approx(16.0) and q["change_pct"] == pytest.approx(0.392, abs=0.001)
    e2 = LiveEngine(clock=Clock(WED))
    e2.seed("EURUSD", "deriv", "D1", [(today - 86400, 1.1, 1.12, 1.09, 1.11)])
    _both(e2, WED, 40, 0.00001)
    e2.on_tick(Tick("EURUSD", "kraken", "EUR/USD", WED + 60, WED + 60, 1.1186, 1.11868, None, "receive"))
    q = e2.quote("EURUSD", WED + 60.5)
    assert q["provider"] == "kraken" and q["change"] is None  # Kraken has no previous close of its own: no mixing


# --- providers ------------------------------------------------------------------------------------------------------------

def test_provider_messages_become_ticks():
    d = providers.Deriv({"frxXAUUSD": "XAUUSD", "OTC_SPC": "US500.CFD"})
    d._pending = {}
    ts = d.parse({"msg_type": "tick", "tick": {"symbol": "frxXAUUSD", "epoch": 1794214587, "bid": 4096.0, "ask": 4096.58,
                                               "quote": 4096.29, "pip_size": 2}})
    assert ts[0].code == "XAUUSD" and ts[0].t == 1794214587 and ts[0].mid == pytest.approx(4096.29)
    assert d.parse({"error": {"code": "MarketIsClosed", "message": "This market is presently closed."},
                    "echo_req": {"ticks": "OTC_SPC", "passthrough": {"symbol": "OTC_SPC"}}}) == []
    assert "MarketIsClosed" in d.metrics.notes["OTC_SPC"] and "OTC_SPC" in d._pending  # asked again later, others unaffected
    k = providers.Kraken({"EUR/USD": "EURUSD"})
    ts = k.parse({"channel": "ticker", "type": "update", "data": [{"symbol": "EUR/USD", "bid": 1.11832, "ask": 1.11833, "last": 1.11829}]})
    assert ts[0].time_basis == "receive" and ts[0].bid == 1.11832  # Kraken gives no quote time: said, not invented


# --- storage --------------------------------------------------------------------------------------------------------------

@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(store, "SessionLocal", Session)
    monkeypatch.setattr(store, "save_bars", REAL_SAVE)
    return Session


def test_ticks_go_to_hourly_files_never_to_the_database(db, eng, tmp_path):
    """Brief 9. 11.: ticks are not stored in the database (D1 limit 100 000 writes a day) — hourly files; candles from
    M1 up go to the database."""
    e, _ = eng
    for i in range(130):
        e.on_tick(tick("XAUUSD", "deriv", WED + i, 4000 + i * 0.01, 4000.5 + i * 0.01))
    drained = e.drain(WED + 300)
    storage.save_ticks(drained["ticks"], tmp_path)
    storage.save_ticks(drained["ticks"], tmp_path)  # the same blocks again (a retry) → read once, not doubled
    got = storage.load_ticks("XAUUSD", "deriv", WED, WED + 300, tmp_path)
    assert len(got) == 130 and got[0][1] == 4000 and got == sorted(got)
    assert list(tmp_path.rglob("*.jsonl.gz"))[0].name == "XAUUSD@deriv.jsonl.gz"
    s = db()
    storage.save_candles(s, drained["candles"])
    s.commit()
    rows = s.query(models.MarketBar).filter_by(code="XAUUSD", provider="deriv", tf="M1").all()
    assert len(rows) == 3 and {r.price_type for r in rows} == {"bid"} and all("Deriv" in r.origin for r in rows)
    from sqlalchemy import inspect

    assert "live_tick_blocks" not in inspect(s.get_bind()).get_table_names()
    s.close()


# --- AI gate and API -----------------------------------------------------------------------------------------------------

def test_ai_gate_no_live_price_no_trade_signal(eng, monkeypatch):
    from app.ai import pipeline

    e, _ = eng
    assert live_engine.signal_allowed(None, "XAUUSD")[0] is None  # engine off: unchanged behaviour
    e.on_tick(tick("XAUUSD", "deriv", WED, 4096.0, 4096.58))
    r = runner.Runner(engine=e, store=False)
    monkeypatch.setattr(runner, "_runner", r)
    e.clock = Clock(WED + 1)
    final = {"doporuceni": "LONG", "shrnuti": "Pullback k EMA20."}
    assert pipeline._live_gate("XAUUSD", final)["allowed"] is True and final["doporuceni"] == "LONG"
    e.clock = Clock(WED + 120)
    final = {"doporuceni": "SHORT", "shrnuti": "Průraz supportu."}
    gate = pipeline._live_gate("XAUUSD", final)
    assert gate["overridden"] and final["doporuceni"] == "NO TRADE" and "nevydává obchodní signál" in final["shrnuti"]
    assert "AI navrhovala SHORT" in final["shrnuti"]


def test_live_api_and_stream(eng, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.get("/api/live/snapshot").status_code == 503  # off: said, nothing pretended
    e, clock = eng
    e.on_tick(tick("XAUUSD", "deriv", WED, 4096.0, 4096.58))
    monkeypatch.setattr(runner, "_runner", runner.Runner(engine=e, store=False))
    snap = client.get("/api/live/snapshot").json()
    assert snap["running"] and [q["label"] for q in snap["instruments"]] == ["XAUUSD", "EURUSD", "US500", "NAS100"]
    assert snap["instruments"][0]["status"] == "LIVE"
    c = client.get("/api/live/candles?code=XAUUSD&tf=M1").json()
    assert c["provider"] == "deriv" and c["price_type"] == "bid" and c["candles"][0][1] == pytest.approx(4096.0)
    assert client.get("/api/live/candles?code=GBPUSD").status_code == 404
    resp = client.get("/api/live/stream?events=1")  # the test client reads a response to its end: one event
    assert resp.headers["content-type"].startswith("text/event-stream")
    first = next(line for line in resp.text.splitlines() if line.startswith("data: "))
    assert json.loads(first[6:])["instruments"][0]["bid"] == 4096.0
    assert client.get("/api/live/health").json()["providers"]
    monkeypatch.setattr(runner, "_runner", None)
    assert client.get("/api/live/health").status_code == 503


def test_live_is_off_by_default(monkeypatch):
    from app.data import settings_store
    from app.main import _start_live

    monkeypatch.delenv("FTI_DISABLE_LIVE", raising=False)  # the test's own settings file (conftest): defaults only
    assert settings_store.DEFAULTS["live"]["enabled"] is False
    assert _start_live() is False and runner.get() is None


def test_history_window_edge_never_makes_a_cut_candle():
    """Deriv's H1 history began at 17:21:15 (9. 11.): that candle and the first H4 / D1 built over it are cut by the
    window's edge — left out, like every cut candle in FTI (Ú1)."""
    from app.live.engine import whole_history

    day = market_hours.trading_day_start(int(WED))  # 22:00 UTC
    h1 = [(day - 3600 * 2 + 1275, 1, 2, 0.5, 1.5)] + [(day + 3600 * i, 10 + i, 11 + i, 9 + i, 10.5 + i) for i in range(30)]
    assert whole_history(h1, 3600, 3600)[0][0] == day  # the 17:21:15-like candle is dropped
    d1 = whole_history(h1, 3600, 86400)
    assert d1[0] == (day, 10, 34, 9, 33.5)  # starts exactly at its day: kept whole
    late = h1[1 + 3:]  # history beginning 3 h into the trading day → that day is partial
    assert [r[0] for r in whole_history(late, 3600, 86400)] == [day + 86400]
    assert [r[0] for r in whole_history(late, 3600, 14400)][0] == day + 14400  # the H4 cut at its start is dropped


def test_stopping_stores_the_minute_still_being_filled(eng):
    e, _ = eng
    e.on_tick(tick("XAUUSD", "deriv", WED + 5, 4000.0, 4000.5))
    assert e.drain(WED + 10)["ticks"] == []  # the minute is still open
    assert len(e.drain(WED + 10, final=True)["ticks"]) == 1


def test_a_failed_write_is_stored_at_the_next_flush_without_loss_or_doubles(db, eng, monkeypatch, tmp_path):
    """In the user's FTI the 30-min data cycle may hold the database: a live write that fails must lose nothing."""
    e, _ = eng
    for i in range(130):
        e.on_tick(tick("XAUUSD", "deriv", WED + i, 4000 + i * 0.01, 4000.5 + i * 0.01))
    r = runner.Runner(engine=e, session_factory=db, backfill=False, tick_dir=tmp_path)
    real = storage.save_candles
    monkeypatch.setattr(storage, "save_candles", lambda s, g: (_ for _ in ()).throw(RuntimeError("database is locked")))
    r._write(e.drain(WED + 300))
    assert r.stats["write_errors"] == 1 and "locked" in r.stats["last_write_error"]
    monkeypatch.setattr(storage, "save_candles", real)
    r._write(e.drain(WED + 301))  # the retry: everything from the failed flush
    s = db()
    assert len(storage.load_ticks("XAUUSD", "deriv", WED, WED + 300, tmp_path)) == 130
    assert s.query(models.MarketBar).filter_by(provider="deriv", tf="M1").count() == 3
    s.close()



# --- brief 9. 11.: validation, MARKET vs DATA STATUS, banner, gate before AI, own history ----------------------------------

def test_invalid_quotes_are_dropped_and_logged(eng):
    e, _ = eng
    for i in range(20):  # a calm minute history: ATR(M1) ≈ 1 USD
        for k in range(3):
            t = WED - 1200 + i * 60 + k * 20
            e.on_tick(tick("XAUUSD", "deriv", t, 4000 + k * 0.5, 4000.4 + k * 0.5))
    base = WED - 5
    e.on_tick(tick("XAUUSD", "deriv", base, 4000.0, 4000.4))
    for bad, why in (((4001.0, 4000.5), "ask"), ((0.0, 0.3), "≤ 0"), ((4000.0, 4009.0), "spread"), ((4100.0, 4100.4), "skok")):
        e.on_tick(tick("XAUUSD", "deriv", base + 1, *bad))
        assert why in e.rejected[("XAUUSD", "deriv")][-1]["reason"]
    assert e.last[("XAUUSD", "deriv")].bid == 4000.0  # none of them became the price
    for k in range(2):  # the market really jumped: 3 quotes in a row at the new level confirm it
        e.on_tick(tick("XAUUSD", "deriv", base + 2 + k, 4100.0, 4100.4))
    assert e.last[("XAUUSD", "deriv")].bid == 4100.0 and e.rejected_count[("XAUUSD", "deriv")] == 5
    e.on_tick(tick("XAUUSD", "deriv", base + 600, 4150.0, 4150.4))  # after a pause (reopen) a gap is normal
    assert e.last[("XAUUSD", "deriv")].bid == 4150.0


def test_market_status_and_data_status_are_separate_with_the_banner(eng):
    e, _ = eng
    e.on_tick(tick("XAUUSD", "deriv", WED, 4096.0, 4096.58))
    q = e.quote("XAUUSD", WED + 1)
    assert (q["market_status"], q["data_status"], q["banner"]) == ("OPEN", "LIVE", None)
    q = e.quote("XAUUSD", WED + 30)
    assert (q["market_status"], q["data_status"], q["banner"]) == ("OPEN", "DELAYED", "TRH OTEVŘEN – DATA NEAKTUÁLNÍ")
    e.connected = lambda provider: False
    q = e.quote("XAUUSD", WED + 30)
    assert q["data_status"] == "UNAVAILABLE" and q["bid"] == 4096.0 and "Spojení" in q["notes"][0]
    sat = dt.datetime(2026, 11, 7, 12, tzinfo=UTC).timestamp()
    e.connected = lambda provider: True
    q = e.quote("XAUUSD", sat)
    assert q["market_status"] == "CLOSED" and q["data_status"] == "HISTORICAL" and q["banner"] is None


def test_without_a_live_price_the_code_decides_no_trade_before_any_ai_call(eng, monkeypatch, db_session):
    from app.ai import groq, pipeline

    e, _ = eng
    e.on_tick(tick("XAUUSD", "deriv", WED, 4096.0, 4096.58))
    e.clock = Clock(WED + 120)
    monkeypatch.setattr(runner, "_runner", runner.Runner(engine=e, store=False))
    monkeypatch.setattr(groq, "_transport", None)
    called = []
    monkeypatch.setattr(pipeline.context, "trade", lambda *a, **k: called.append(1))
    r = pipeline.run(db_session, "XAUUSD")
    assert r["status"] == "unavailable" and r["no_trade"] and r["text"].startswith("NO TRADE") and "AI se nevolala" in r["text"]
    assert called == []  # not even the context was built


def test_live_candles_continue_the_providers_own_stored_candles(db, eng):
    e, _ = eng
    today = market_hours.trading_day_start(int(WED))
    store.save_bars("XAUUSD", "D1", [(today - 86400, 4050.0, 4100.0, 4040.0, 4080.0)], "deriv",
                    meta={"feed_symbol": "frxXAUUSD", "price_type": "bid", "complete_until": today})
    store.save_bars("XAUUSD", "D1", [(today - 86400, 1, 2, 0.5, 9999.0)], "deriv-mid", meta={"feed_symbol": "x", "price_type": "mid"})
    r = runner.Runner(engine=e, session_factory=db)
    r._seed_from_db()
    e.on_tick(tick("XAUUSD", "deriv", WED, 4095.75, 4096.25))
    q = e.quote("XAUUSD", WED + 1)
    assert q["prev_close"] == 4080.0  # its own bid history — never the moved-aside mid candles of the first test


def test_first_versions_mid_candles_move_aside():
    from sqlalchemy import create_engine as ce, text

    from app.data import migrations

    engine = ce("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    with engine.begin() as c:
        for prov, pt in (("deriv", "mid"), ("deriv", "bid"), ("dukascopy", "bid")):
            c.execute(text("INSERT INTO market_bars (code, provider, feed_symbol, tf, t, o, h, l, c, closed, received_at, origin, "
                           "price_type) VALUES ('XAUUSD', :p, 's', 'M1', :t, 1, 2, 0.5, 1.5, 1, '2026-11-09', 'x', :pt)"),
                      {"p": prov, "pt": pt, "t": 60 if pt == "mid" else 120})
    assert "2026-11-09_deriv_mid_candles_aside" in migrations.apply_all(engine)
    with engine.connect() as c:
        got = sorted(c.execute(text("SELECT provider, price_type FROM market_bars")).all())
    assert got == [("deriv", "bid"), ("deriv-mid", "mid"), ("dukascopy", "bid")]
