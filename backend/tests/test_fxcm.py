"""FXCM's public candle archive as the second, independent FX source (8. 11. 2026): parsing, download once and never
again, a failing instrument never stops the others, an outage of one provider never stops the other, and the choice of
one source per market for Intermarket."""

import datetime as dt
import gzip
import lzma
import math
import random
import struct

import httpx
import pytest
from sqlalchemy import func, select

from app.connectors import dukascopy, fxcm
from app.data import store
from app.market import intermarket_data as imd
from app.market import intermarket_intel as im
from app.market.intermarket_intel import Series
from app.models import MarketBar

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 8, 12, tzinfo=UTC)
WEEK43 = dt.datetime(2026, 10, 25, 21, tzinfo=UTC)  # FXCM's 2026/43 starts on Sunday 25. 10. at 21:00 UTC
HEADER = "DateTime,BidOpen,BidHigh,BidLow,BidClose,AskOpen,AskHigh,AskLow,AskClose"


def week_gz(start: dt.datetime, n: int, step: int = 3600, base: float = 1.10) -> bytes:
    rows = [HEADER]
    for i in range(n):
        t = start + dt.timedelta(seconds=i * step)
        v = base + i * 0.0001
        rows.append(f"{t.strftime('%m/%d/%Y %H:%M:%S')}.000,{v:.5f},{v + 0.0005:.5f},{v - 0.0005:.5f},{v + 0.0001:.5f},"
                    f"{v + 0.0002:.5f},{v + 0.0007:.5f},{v - 0.0003:.5f},{v + 0.0003:.5f}")
    return gzip.compress("\n".join(rows).encode())


@pytest.fixture()
def fx(monkeypatch, tmp_path):
    monkeypatch.setattr(fxcm, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(fxcm, "MIN_INTERVAL", 0.0)
    monkeypatch.setattr(imd, "fxcm_run", REAL_FXCM_RUN)
    calls: list[str] = []

    def serve(handler):
        def wrapped(req):
            calls.append(req.url.path)
            return handler(req)
        monkeypatch.setattr(fxcm, "_transport", httpx.MockTransport(wrapped))
    return calls, serve


REAL_FXCM_RUN = imd.fxcm_run
REAL_RUN = imd.run
REAL_SAVE = store.save_bars  # conftest replaces these for all other tests


@pytest.fixture(autouse=True)
def _real_storage(monkeypatch):
    monkeypatch.setattr(store, "save_bars", REAL_SAVE)


def _count(session, code, provider="fxcm", tf="H1"):
    return session.scalar(select(func.count()).select_from(MarketBar).where(
        MarketBar.code == code, MarketBar.provider == provider, MarketBar.tf == tf))


def test_file_is_read_as_bid_prices_in_utc():
    bars = fxcm.parse(week_gz(WEEK43, 3))
    assert bars[0] == (int(WEEK43.timestamp()), 1.1, 1.1005, 1.0995, 1.1001, 0.0)
    assert [b[0] - bars[0][0] for b in bars] == [0, 3600, 7200]
    with pytest.raises(fxcm.FxcmBadFile):
        fxcm.parse(b"<html>not a file</html>")


def test_finished_weeks_are_downloaded_once_and_a_rerun_downloads_nothing(fx, db_session, monkeypatch):
    calls, serve = fx
    monkeypatch.setattr(fxcm, "SYMBOLS", ("EURUSD", "GBPUSD"))

    def handler(req):
        if req.url.path == "/H1/EURUSD/2026/43.csv.gz":
            return httpx.Response(200, content=week_gz(WEEK43, 120))
        if req.url.path == "/m1/EURUSD/2026/43.csv.gz":
            return httpx.Response(200, content=week_gz(WEEK43, 60 * 24, step=60))
        return httpx.Response(404)  # weeks 44 and 45 are not published yet, GBPUSD has nothing here
    serve(handler)
    rep = imd.fxcm_run(session=db_session, now=NOW, years=0)
    assert rep["outage"] is None and rep["errors"] == {}
    assert rep["stored"]["EURUSD"] == {"H1": 120, "M15": 96}  # the minute file of the latest week gives quarter hours
    assert _count(db_session, "EURUSD") == 120 and _count(db_session, "EURUSD", tf="M15") == 96
    first = len(calls)
    assert first == rep["fetched"] > 0
    # the same cycle again: the finished week is on disk, the unpublished ones were asked a moment ago -> no request
    rep2 = imd.fxcm_run(session=db_session, now=NOW, years=0)
    assert len(calls) == first and rep2["fetched"] == 0 and rep2["stored"] == {}
    # another database (a restore, the live one after a rehearsal on a copy): the files on disk go in without a request
    db_session.query(MarketBar).filter(MarketBar.provider == "fxcm").delete()
    db_session.commit()
    rep3 = imd.fxcm_run(session=db_session, now=NOW, years=0)
    assert len(calls) == first and rep3["stored"]["EURUSD"] == {"H1": 120, "M15": 96}
    assert _count(db_session, "EURUSD") == 120


def test_one_failing_instrument_does_not_stop_the_others(fx, db_session, monkeypatch):
    calls, serve = fx
    monkeypatch.setattr(fxcm, "SYMBOLS", ("EURUSD", "GBPUSD", "USDJPY"))

    def handler(req):
        if "/EURUSD/" in req.url.path:
            return httpx.Response(503)  # only this instrument answers with an error
        if "/BAD/" in req.url.path:
            return httpx.Response(200, content=b"garbage")
        if req.url.path.startswith("/H1/") and req.url.path.endswith("/2026/43.csv.gz"):
            return httpx.Response(200, content=week_gz(WEEK43, 120, base=150.0 if "JPY" in req.url.path else 1.3))
        return httpx.Response(404)
    serve(handler)
    rep = imd.fxcm_run(session=db_session, now=NOW, years=0, m1_weeks=0)
    assert rep["outage"] is None and list(rep["errors"]) == ["EURUSD"]
    assert sum(1 for c in calls if "/EURUSD/" in c) == 1  # tried once, then left for the next run
    assert _count(db_session, "GBPUSD") == 120 and _count(db_session, "USDJPY") == 120 and _count(db_session, "EURUSD") == 0


def test_two_failing_instruments_mean_the_host_is_down(fx, db_session, monkeypatch):
    calls, serve = fx
    monkeypatch.setattr(fxcm, "SYMBOLS", ("EURUSD", "GBPUSD", "USDJPY"))
    serve(lambda req: httpx.Response(503))
    rep = imd.fxcm_run(session=db_session, now=NOW, years=0)
    assert rep["stopped_by"] == "výpadek FXCM" and len(calls) == 2  # the third instrument is not hammered


def test_broken_file_skips_only_its_instrument_and_is_not_kept(fx, db_session, monkeypatch):
    calls, serve = fx
    monkeypatch.setattr(fxcm, "SYMBOLS", ("EURUSD", "GBPUSD"))

    def handler(req):
        if req.url.path == "/H1/EURUSD/2026/43.csv.gz":
            return httpx.Response(200, content=b"\x1f\x8b broken")
        if req.url.path == "/H1/GBPUSD/2026/43.csv.gz":
            return httpx.Response(200, content=week_gz(WEEK43, 120, base=1.3))
        return httpx.Response(404)
    serve(handler)
    rep = imd.fxcm_run(session=db_session, now=NOW, years=0, m1_weeks=0)
    assert "EURUSD" in rep["errors"] and rep["outage"] is None
    assert _count(db_session, "GBPUSD") == 120
    assert not (fxcm.CACHE_DIR / "H1_EURUSD_2026_43.csv.gz").exists()  # asked again next time


def test_dukascopy_outage_does_not_stop_fxcm(fx, db_session, monkeypatch, tmp_path):
    calls, serve = fx
    monkeypatch.setattr(fxcm, "SYMBOLS", ("EURUSD",))
    serve(lambda req: httpx.Response(200, content=week_gz(WEEK43, 120)) if req.url.path == "/H1/EURUSD/2026/43.csv.gz"
          else httpx.Response(404))
    monkeypatch.setattr(imd, "run", REAL_RUN)
    monkeypatch.setattr(dukascopy, "CACHE_DIR", tmp_path / "duka")
    monkeypatch.setattr(dukascopy, "MIN_INTERVAL", 0.0)
    dukascopy.reset()
    monkeypatch.setattr(dukascopy, "_transport", httpx.MockTransport(lambda req: httpx.Response(503, text="No server is available")))
    rep = imd.run_all(session=db_session, now=NOW)
    assert rep["dukascopy"]["stopped_by"] == "výpadek Dukascopy"
    assert rep["fxcm"]["outage"] is None and rep["fxcm"]["stored"]["EURUSD"]["H1"] == 120
    dukascopy.reset()


def test_broken_dukascopy_file_skips_only_its_instrument(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(imd, "run", REAL_RUN)
    monkeypatch.setattr(dukascopy, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(dukascopy, "MIN_INTERVAL", 0.0)
    monkeypatch.setattr(imd, "FEEDS", {"EURUSD": imd.FEEDS["EURUSD"], "USDJPY": imd.FEEDS["USDJPY"]})
    dukascopy.reset()
    good = lzma.compress(b"".join(struct.pack(">5i1f", t, 150000, 150100, 149900, 150200, 5.0) for t in (0, 3600)))

    def handler(req):
        return httpx.Response(200, content=b"not lzma" if "EURUSD" in req.url.path else good)
    monkeypatch.setattr(dukascopy, "_transport", httpx.MockTransport(handler))
    rep = imd.run(session=db_session, now=NOW, max_files=10, months=2, days=0)
    assert rep["outage"] is None and list(rep["errors"]) == ["EURUSD"]
    assert rep["stored"]["USDJPY"]["H1"] == 4  # both months of the other instrument
    assert not list(tmp_path.glob("EURUSD*"))  # the broken file is not kept: the next run asks again
    dukascopy.reset()


# --------------------------------------------------------------------------------- one source per market

def _walk(n, seed, start=100.0):
    rnd, v, out = random.Random(seed), start, []
    for _ in range(n):
        v *= math.exp(rnd.gauss(0, 0.002))
        out.append(v)
    return out


def _s(key, closes, start=1_790_000_000):
    code = key.split("@")[0]
    return Series(key, code, code, "test", "price", code.endswith(".CFD"), 0.0,
                  {start + i * 3600: c for i, c in enumerate(closes)})


def test_freshest_source_wins_then_the_source_order():
    duka, fxcm_s = _s("EURUSD@dukascopy", _walk(200, 1)), _s("EURUSD@fxcm", _walk(400, 2), start=1_790_000_000 - 200 * 3600)
    assert im._primary([duka, fxcm_s], "H1")[0] is duka  # both end together: Dukascopy first
    late = _s("EURUSD@dukascopy", _walk(200, 1), start=1_790_000_000 - 7 * 86400)
    assert im._primary([late, fxcm_s], "H1")[0] is fxcm_s  # Dukascopy a week behind: FXCM, though second in order
    cfd, calc = _s("DXY.CFD@dukascopy", _walk(200, 3)), _s("DXY*@fxcm", _walk(200, 4))
    assert im._primary([cfd, calc], "H1")[0] is calc  # ICE's formula from spot rates before the futures CFD


def test_each_market_is_one_relation_and_other_sources_are_checks(db_session, monkeypatch):
    monkeypatch.setattr(im, "_eursek", lambda as_of_date: {})
    rnd = random.Random(7)
    g = [rnd.gauss(0, 0.002) for _ in range(300)]
    e = [0.6 * x + 0.4 * rnd.gauss(0, 0.002) for x in g]
    t0 = int(dt.datetime(2026, 9, 1, tzinfo=UTC).timestamp())

    def bars(code, provider, rets, noise_bp=0.0):
        v, rows = 1.1, []
        for i, r in enumerate(rets):
            v *= math.exp(r)
            c = v * (1 + noise_bp * 1e-4 * rnd.gauss(0, 1))
            rows.append(MarketBar(code=code, provider=provider, feed_symbol=code, tf="H1", t=t0 + i * 3600, o=c, h=c, l=c, c=c,
                                  closed=True))
        db_session.add_all(rows)
    bars("XAUUSD", "dukascopy", g)
    bars("EURUSD", "dukascopy", e)
    bars("EURUSD", "fxcm", e, noise_bp=0.2)
    db_session.commit()
    res = im.compute(db_session, "H1", now=dt.datetime.fromtimestamp(t0 + 300 * 3600, UTC))
    assert [r["b"] for r in res["relations"]] == ["EURUSD@dukascopy"]
    check = next(c for c in res["source_checks"] if c["b"] == "EURUSD@fxcm")
    assert next(w["r"] for w in check["windows"] if w["window"] == im.MAIN["H1"]) > 0.99  # two dealers, one market
