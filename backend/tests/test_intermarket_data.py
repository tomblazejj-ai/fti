"""Intermarket data and method — the failure modes the user listed (8. 11. 2026): missing and stale data, unsynchronised
series, a Dukascopy outage, incomplete candles, look-ahead bias, spurious correlation of trends, historical recalculation."""

import datetime as dt
import lzma
import math
import random
import struct

import httpx
import pytest

from app.connectors import dukascopy
from app.market import intermarket_data as imd
from app.market import intermarket_intel as im
from app.market.intermarket_intel import Series
from app.models import MarketBar

UTC = dt.timezone.utc
H = 3600
REAL_RUN = imd.run  # conftest replaces it with a no-op for all other tests (no Dukascopy downloads)
T0 = int(dt.datetime(2026, 9, 1, tzinfo=UTC).timestamp())


def walk(returns, start=100.0):
    out, v = [], start
    for r in returns:
        v *= math.exp(r)
        out.append(v)
    return out


def noise(n, seed, sd=0.002, drift=0.0):
    rnd = random.Random(seed)
    return [drift + rnd.gauss(0, sd) for _ in range(n)]


def hourly(key, closes, start=T0, kind="price"):
    return Series(key, key.split("@")[0], key, "test", kind, False, 0.0, {start + i * H: c for i, c in enumerate(closes)})


# ---------------------------------------------------------------- spurious correlation of trends, autocorrelation

def test_two_independent_trends_correlate_in_levels_but_not_in_returns():
    """Why FTI correlates RETURNS: two unrelated markets that both drift upward look 'related' in price levels."""
    a = walk(noise(400, 1, drift=0.001))
    b = walk(noise(400, 2, drift=0.001))
    assert im.pearson(a, b) > 0.8  # levels: a fake relationship
    rel = im.analyze(hourly("XAUUSD@t", a), hourly("X@t", b), "H1")
    w = next(x for x in rel["windows"] if x["window"] == 120)
    assert abs(w["r"]) < 0.3 and w["p"] > 0.01  # returns: nothing there


def test_autocorrelated_series_count_for_fewer_observations():
    rnd = random.Random(3)
    x, y, e1, e2 = [0.0], [0.0], 0.0, 0.0
    for _ in range(499):
        e1 = 0.9 * e1 + rnd.gauss(0, 1)
        e2 = 0.9 * e2 + rnd.gauss(0, 1)
        x.append(e1)
        y.append(e2)
    assert im.n_effective(x, y) < 0.4 * len(x)  # AR(1) 0.9 on both: far fewer independent observations
    white = noise(500, 4), noise(500, 5)
    assert im.n_effective(*white) > 0.8 * 500
    r = im.pearson(x, y)
    assert im.p_value(r, im.n_effective(x, y)) > im.p_value(r, len(x))  # the honest p is larger


# ---------------------------------------------------------------------- unsynchronised, missing and stale data

def test_unsynchronised_series_get_no_correlation():
    """Closes 30 minutes apart are never paired — there is no common instant."""
    g = hourly("XAUUSD@t", walk(noise(300, 6)))
    x = hourly("X@t", walk(noise(300, 7)), start=T0 + 1800)
    rel = im.analyze(g, x, "H1")
    assert rel["observations_total"] == 0 and all(w["r"] is None for w in rel["windows"])
    assert rel["quality"]["label"] == "nedostatečná"


def test_stale_series_is_marked_and_missing_hours_are_not_filled():
    g = hourly("XAUUSD@t", walk(noise(600, 8)))
    x = hourly("X@t", walk(noise(500, 9)))  # stops 100 hours (4 days) before gold's last bar
    rel = im.analyze(g, x, "H1")
    assert any("zastaralá" in i for i in rel["quality"]["issues"])
    assert rel["observations_total"] == 499 and rel["last_common"].startswith(
        dt.datetime.fromtimestamp(T0 + 500 * H, UTC).isoformat()[:13])


# ----------------------------------------------------------------------------------------- incomplete candles

def test_m30_and_h4_closes_exist_only_with_their_last_part():
    m15 = {T0: 1.0, T0 + 900: 2.0, T0 + 1800: 3.0}  # the second half hour lacks its second quarter
    assert im.resample_close(m15, 900, 1800) == {T0: 2.0}
    h1 = {T0 + k * H: float(k) for k in range(8) if k != 7}  # 04:00–08:00 block misses 07:00
    assert im.resample_close(h1, 3600, 14400) == {T0: 3.0}


def test_daily_close_needs_the_hour_ending_exactly_at_17_new_york():
    fri = int(dt.datetime(2026, 11, 6, 21, tzinfo=UTC).timestamp())  # 16:00–17:00 NY (EST)
    assert im.ny_close_daily({fri - H: 1.0}) == {}  # only up to 16:00 NY: no close that day (another instant)
    assert im.ny_close_daily({fri - H: 1.0, fri: 2.0}) == {"2026-11-06": 2.0}
    summer = int(dt.datetime(2026, 7, 10, 20, tzinfo=UTC).timestamp())  # EDT: 16:00–17:00 NY starts 20:00 UTC
    assert im.ny_close_daily({summer: 5.0}) == {"2026-07-10": 5.0}


# ------------------------------------------------------------------------------------------------ DXY formula

def test_dxy_formula_and_sek_from_the_fixing_of_that_day():
    fx = {"EURUSD": {"2026-11-06": 1.0}, "USDJPY": {"2026-11-06": 1.0}, "GBPUSD": {"2026-11-06": 1.0},
          "USDCAD": {"2026-11-06": 1.0}, "USDCHF": {"2026-11-06": 1.0}}
    assert im.dxy_points(fx, {"2026-11-06": 1.0}, "D1") == {"2026-11-06": pytest.approx(50.14348112)}
    fx["EURUSD"]["2026-11-06"] = 1.12
    v = im.dxy_points(fx, {"2026-11-05": 11.0}, "D1")["2026-11-06"]  # the fixing of the day before
    assert v == pytest.approx(50.14348112 * 1.12 ** -0.576 * (11.0 / 1.12) ** 0.042)
    assert im.dxy_points({k: v for k, v in fx.items() if k != "GBPUSD"}, {"2026-11-06": 11.0}, "D1") == {}  # never partial


def test_related_pairs_are_marked_not_discovered():
    rnd = random.Random(10)
    base = noise(300, 11)
    a = Series("US10Y@t", "US10Y", "10Y", "t", "yield", False, 15.5, {})
    b = Series("US10YR@t", "US10YR", "10Y real", "t", "yield", False, 15.5, {})
    a.points = {T0 + i * H: 4 + v for i, v in enumerate(walk(base, 1.0))}
    b.points = {T0 + i * H: 2 + 0.9 * (v - 1) + 0.0001 * rnd.gauss(0, 1) for i, v in enumerate(walk(base, 1.0))}
    found = im.discover([a, b], "H1")
    assert found and "inflaci" in found[0]["related"]


# --------------------------------------------------------------- look-ahead bias and historical recalculation

def _db_bars(session, code, closes, provider="dukascopy", start=T0):
    session.add_all([MarketBar(code=code, provider=provider, feed_symbol=code, tf="H1", t=start + i * H, o=c, h=c, l=c, c=c,
                               closed=True) for i, c in enumerate(closes)])
    session.commit()


def test_recalculation_as_of_a_past_moment_never_sees_later_data(db_session, monkeypatch):
    monkeypatch.setattr(im, "_eursek", lambda as_of_date: {})
    a, b = noise(700, 12), noise(700, 13)
    b = [0.7 * x + 0.3 * y for x, y in zip(a, b)]
    _db_bars(db_session, "XAUUSD", walk(a[:600]))
    _db_bars(db_session, "EURUSD", walk(b[:600]))
    as_of = dt.datetime.fromtimestamp(T0 + 600 * H, UTC)
    first = im.compute(db_session, "H1", now=as_of, as_of=as_of)
    # later data arrive (100 more hours, a completely different relationship)
    later = noise(100, 14)
    _db_bars(db_session, "XAUUSD", walk(a[600:], walk(a[:600])[-1]), start=T0 + 600 * H)
    _db_bars(db_session, "EURUSD", walk([-x for x in later], walk(b[:600])[-1]), start=T0 + 600 * H)
    again = im.compute(db_session, "H1", now=as_of, as_of=as_of)
    strip = lambda res: [{k: v for k, v in r.items()} for r in res["relations"]]  # noqa: E731
    assert strip(again) == strip(first) and again["fingerprint"] == first["fingerprint"]  # deterministic, no look-ahead
    today = im.compute(db_session, "H1")
    assert today["fingerprint"] != first["fingerprint"]  # the new data are seen only after their time


def test_breakdown_uses_windows_that_end_at_the_same_latest_point():
    a1, b1 = noise(481, 15), noise(481, 16)  # 480 returns = the long window
    b1 = [0.8 * x + 0.2 * y for x, y in zip(a1, b1)]
    rel = im.analyze(hourly("XAUUSD@t", walk(a1)), hourly("X@t", walk(b1)), "H1")
    assert rel["breakdown"]["state"] == "drží"
    # appending data AFTER the evaluation point is what changes it — the past verdict did not know the future
    a2, b2 = noise(120, 17), noise(120, 18)
    rel2 = im.analyze(hourly("XAUUSD@t", walk(a1 + a2)), hourly("X@t", walk(b1 + b2)), "H1")
    assert rel2["breakdown"]["state"] in ("rozpad", "obrat")


# ----------------------------------------------------------------------------------------- Dukascopy outage

def _hour_file(rows):
    return lzma.compress(b"".join(struct.pack(">5i1f", t, o, c, lo, hi, v) for t, o, c, lo, hi, v in rows))


def test_outage_stops_the_run_without_partial_data_and_the_next_run_continues(tmp_path, monkeypatch, db_session):
    monkeypatch.setattr(imd, "run", REAL_RUN)
    monkeypatch.setattr(dukascopy, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(dukascopy, "MIN_INTERVAL", 0.0)
    monkeypatch.setattr(imd, "FEEDS", {"EURUSD": imd.FEEDS["EURUSD"], "USDJPY": imd.FEEDS["USDJPY"]})
    dukascopy.reset()
    good = _hour_file([(0, 112000, 112100, 111900, 112200, 5.0), (3600, 112100, 112200, 112000, 112300, 5.0)])
    calls = []

    def handler(req):
        calls.append(req.url.path)
        if "USDJPY" in req.url.path:
            return httpx.Response(503)
        return httpx.Response(200, content=good)

    monkeypatch.setattr(dukascopy, "_transport", httpx.MockTransport(handler))
    from app.data import store

    saved = []
    monkeypatch.setattr(store, "save_bars", lambda code, tf, rows, src, session=None, meta=None: saved.append((code, tf, len(rows))) or len(rows))
    now = dt.datetime(2026, 11, 8, 12, tzinfo=UTC)
    rep = REAL_RUN(session=db_session, now=now, max_files=10, months=2, days=0)
    assert rep["stopped_by"] == "výpadek Dukascopy" and "503" in rep["outage"]
    assert saved == [("EURUSD", "H1", 2)]  # the one good file is stored whole; nothing of the failed one
    assert rep["missing_after"] == rep["missing_before"] - 1
    # the datafeed is back: the next run fetches only what is still missing
    monkeypatch.setattr(dukascopy, "_transport", httpx.MockTransport(lambda req: calls.append(req.url.path) or httpx.Response(200, content=good)))
    dukascopy.reset()
    calls.clear()
    rep2 = REAL_RUN(session=db_session, now=now, max_files=10, months=2, days=0)
    assert rep2["missing_after"] == 0 and all("2026/09" not in c or "EURUSD" not in c for c in calls)


def test_a_run_respects_its_file_budget_and_time_limit(tmp_path, monkeypatch, db_session):
    monkeypatch.setattr(imd, "run", REAL_RUN)
    monkeypatch.setattr(dukascopy, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(dukascopy, "MIN_INTERVAL", 0.0)
    dukascopy.reset()
    monkeypatch.setattr(dukascopy, "_transport", httpx.MockTransport(lambda req: httpx.Response(404)))
    now = dt.datetime(2026, 11, 8, 12, tzinfo=UTC)
    rep = REAL_RUN(session=db_session, now=now, max_files=3, months=24, days=0)
    assert rep["fetched"] == 3 and rep["stopped_by"] == "rozpočet souborů na běh"
    rep = REAL_RUN(session=db_session, now=now, max_files=1000, max_seconds=0.0, months=24, days=0)
    assert rep["stopped_by"] == "časový limit" and rep["fetched"] <= 1
