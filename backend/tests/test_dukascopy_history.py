"""Dukascopy's own history (ETAPA 2, task 1): get_bars() asks Dukascopy only when MT5 and OANDA fail, so its bars were
never stored. collect_history() keeps them whatever feed is shown — only whole candles, the still forming one never
marked closed, files on disk used during an outage, one small download budget per run, no duplicates, other providers
untouched, nothing ever filled in."""

import datetime as dt
import lzma
import struct

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.connectors import dukascopy
from app.data import bars, store
from app.db import Base
from app.models import MarketBar

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 3, 15, 30, tzinfo=UTC)  # Tuesday afternoon
REAL_BARS = dukascopy.bars
REAL_SAVE = store.save_bars


def _minutes(price=3870.0):
    recs = b"".join(struct.pack(">5i1f", m * 60, int(price * 1000), int((price + 0.1) * 1000), int((price - 0.5) * 1000),
                                int((price + 0.5) * 1000), 1.0) for m in range(0, 1440, 30))
    return lzma.compress(recs, format=lzma.FORMAT_ALONE)


def _ticks(price=3875.0):
    recs = b"".join(struct.pack(">3i2f", ms, int((price + 0.3) * 1000), int(price * 1000), 1.0, 1.0)
                    for ms in (1000, 1_800_000, 3_599_000))
    return lzma.compress(recs, format=lzma.FORMAT_ALONE)


@pytest.fixture()
def feed(monkeypatch, tmp_path):
    monkeypatch.setattr(dukascopy, "bars", REAL_BARS)  # conftest replaces it for all other tests
    monkeypatch.setattr(dukascopy, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(dukascopy, "MIN_INTERVAL", 0.0)
    monkeypatch.setattr(bars, "DUKASCOPY_DAYS", {**bars.DUKASCOPY_DAYS, "D1": 10, "H4": 6})  # small windows, quick tests
    monkeypatch.setattr(bars, "DUKASCOPY_MONTHS", {})  # the minute-file path; the monthly files: test_dukascopy_daily.py
    dukascopy.reset()
    state = {"seen": [], "fail": None}

    def handler(request):
        state["seen"].append(request.url.path)
        if state["fail"]:
            return httpx.Response(state["fail"], content=b"<html>503</html>")
        if request.url.path.endswith("BID_candles_min_1.bi5"):
            return httpx.Response(200, content=_minutes())
        return httpx.Response(200, content=_ticks())

    monkeypatch.setattr(dukascopy, "_transport", httpx.MockTransport(handler))
    return state


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(store, "SessionLocal", Session)
    monkeypatch.setattr(store, "save_bars", REAL_SAVE)
    return Session


def _rows(Session, **flt):
    with Session() as s:
        q = s.query(MarketBar).filter_by(**flt).order_by(MarketBar.tf, MarketBar.t)
        return [(r.provider, r.feed_symbol, r.tf, r.t, r.o, r.h, r.l, r.c, r.v, r.closed, r.quality, r.origin, r.delay_s) for r in q]


def test_keep_whole_drops_cut_candles_and_keeps_the_forming_one():
    covered = [(0, 100), (200, 300)]
    got = dukascopy.keep_whole([(0,), (50,), (150,), (190,), (250,)], 100, covered)
    # 0: whole; 50: crosses the gap at 100–200 → cut; 150: in the gap; 190: starts before the newest stretch → cut;
    # 250: starts inside the newest stretch and runs past its end → still forming, kept
    assert [b[0] for b in got] == [0, 250]
    assert dukascopy.keep_whole([(0,)], 100, []) == []


def test_history_is_collected_while_another_feed_is_shown(feed, db, monkeypatch):
    # MT5 shows XAUUSD; collect_history does not use get_bars at all
    for _ in range(10):  # a few runs: the history fills up NEW_FILES_PER_CALL files at a time
        bars.collect_history(now=NOW)
    h1 = _rows(db, provider="dukascopy", tf="H1")
    assert h1 and all(r[1] == "XAUUSD" and r[12] == 3600 for r in h1)  # symbol, delay
    # quality = the feed's state when the bar first came (while the history was filling up it was stale); the newest is delayed
    assert {r[10] for r in h1} <= {"DELAYED", "STALE"} and h1[-1][10] == "DELAYED"
    assert all(r[8] is None for r in h1)  # no fake volume for an OTC bank quote
    d1 = _rows(db, provider="dukascopy", tf="D1")
    today0 = int(dt.datetime(2026, 11, 2, 22, tzinfo=UTC).timestamp())  # the trading day starts 17:00 New York (EST)
    assert d1[-1][3] == today0 and not d1[-1][9]  # today's daily bar is still forming → never closed
    assert all(r[9] for r in d1[:-1])
    assert {r[2] for r in _rows(db, provider="dukascopy")} == {"M1", "M5", "M15", "H1", "H4", "D1", "W1"}
    # OHLC of a finished day = what the minute file says (price 3870, high +0.5, low -0.5)
    yday = [r for r in d1 if r[3] == today0 - 86400][0]
    assert yday[4:8] == (pytest.approx(3870.0), pytest.approx(3870.5), pytest.approx(3869.5), pytest.approx(3870.1))


def test_one_small_download_budget_per_run(feed, db):
    bars.collect_history(now=NOW)
    assert len(feed["seen"]) <= dukascopy.NEW_FILES_PER_CALL  # all timeframes together, not 4 per timeframe


def test_running_again_adds_no_duplicates_and_keeps_other_providers(feed, db):
    store.save_bars("XAUUSD", "H1", [(1793700000, 4000.0, 4001.0, 3999.0, 4000.5, 50.0)], "mt5", meta={"feed_symbol": "XAUUSD_ecn"})
    mt5_before = _rows(db, provider="mt5")
    for _ in range(10):
        bars.collect_history(now=NOW)
    first = _rows(db, provider="dukascopy")
    for _ in range(3):
        bars.collect_history(now=NOW)
    again = _rows(db, provider="dukascopy")
    assert len(again) == len(first)  # same keys, no second copy
    assert [r[:10] for r in again] == [r[:10] for r in first]
    assert _rows(db, provider="mt5") == mt5_before


def test_outage_uses_the_files_already_on_disk(feed, db):
    for _ in range(10):
        bars.collect_history(now=NOW)
    before = len(_rows(db, provider="dukascopy", tf="H1"))
    feed["fail"] = 503
    report = bars.collect_history(now=NOW + dt.timedelta(hours=1))  # a new hour is due, the feed is down
    assert any(v.get("outage") for v in report.values())  # the outage is reported…
    assert len(_rows(db, provider="dukascopy", tf="H1")) >= before  # …and nothing already kept is lost
    n = len(feed["seen"])
    bars.collect_history(now=NOW + dt.timedelta(hours=1))
    assert len(feed["seen"]) == n  # paused after the failure: no new request


def test_missing_files_leave_gaps_and_are_never_filled(feed, db, monkeypatch):
    def handler(request):
        if "/2026/10/02/" in request.url.path:  # 2 Nov 2026 (0-based month) is missing at the source
            return httpx.Response(404)
        if request.url.path.endswith("BID_candles_min_1.bi5"):
            return httpx.Response(200, content=_minutes())
        return httpx.Response(200, content=_ticks())

    monkeypatch.setattr(dukascopy, "_transport", httpx.MockTransport(handler))
    for _ in range(10):
        bars.collect_history(now=NOW)
    nov2 = int(dt.datetime(2026, 11, 2, tzinfo=UTC).timestamp())
    h1_times = {r[3] for r in _rows(db, provider="dukascopy", tf="H1")}
    assert not any(nov2 <= t < nov2 + 86400 for t in h1_times)  # nothing invented for the missing day
    assert store.gaps("XAUUSD", "dukascopy", "H1", nov2 - 3 * 86400, nov2 + 86400)  # the gap is reported


def test_save_bars_respects_complete_until(db):
    t = int(dt.datetime(2026, 10, 27, 10, tzinfo=UTC).timestamp())  # long finished
    store.save_bars("XAUUSD", "H1", [(t, 1, 1, 1, 1, None), (t + 3600, 1, 1, 1, 1, None)], "dukascopy",
                    meta={"complete_until": t + 3600})
    assert [r[9] for r in _rows(db, provider="dukascopy")] == [True, False]  # the bar after the complete data is still forming
