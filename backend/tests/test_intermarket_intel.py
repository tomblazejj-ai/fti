"""Intermarket Intelligence — correlations measured on synchronised data (synthetic series with KNOWN relationships)."""

import datetime as dt
import math
import random

import pytest

from app.market import intermarket_intel as im
from app.market.intermarket_intel import Series

H = 3600
T0 = int(dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc).timestamp())


def walk(returns, start=100.0):
    out, v = [], start
    for r in returns:
        v *= math.exp(r)
        out.append(v)
    return out


def hourly(key, closes, kind="price", proxy=False, start=T0, skip=()):
    return Series(key, key.split("@")[0], key, "test", kind, proxy, 0.0,
                  {start + i * H: c for i, c in enumerate(closes) if i not in skip})


def pair(n=600, rho=0.8, seed=1):
    rnd = random.Random(seed)
    a, b = [], []
    for _ in range(n):
        x = rnd.gauss(0, 0.002)
        a.append(x)
        b.append(rho * x + math.sqrt(1 - rho * rho) * rnd.gauss(0, 0.002))
    return a, b


def test_statistics_are_exact():
    assert im.pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
    assert im.pearson([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)
    assert im.pearson([1, 1, 1], [1, 2, 3]) is None  # no variance, no correlation
    assert im.p_value(0.0, 100) == pytest.approx(1.0)
    assert im.p_value(0.5, 100) < 1e-6
    lo, hi = im.ci95(0.5, 100)
    assert lo < 0.5 < hi
    assert im.bh([0.01, 0.04, 0.03, 0.5]) == pytest.approx([0.04, 0.0533333, 0.0533333, 0.5], rel=1e-4)


def test_known_correlation_is_recovered_with_window_n_p_and_sufficiency():
    a, b = pair(600, 0.8)
    g, x = hourly("XAUUSD@t", walk(a)), hourly("DXY.CFD@t", walk(b))
    rel = im.analyze(g, x, "H1")
    w = {v["window"]: v for v in rel["windows"]}
    assert w[480]["n"] == 480 and w[480]["r"] == pytest.approx(0.8, abs=0.06) and w[480]["p"] < 1e-10
    assert w[48]["n"] == 48 and w[48]["r"] is not None and all(v >= im.MIN_N for v in im.WINDOWS["H1"] + im.WINDOWS["D1"])
    assert rel["observations_total"] == 599 and rel["last_common"]
    assert "příčin" in rel["causality"]  # correlation is never sold as causation
    short = im.analyze(hourly("XAUUSD@t", walk(a[:25])), hourly("DXY.CFD@t", walk(b[:25])), "H1")
    assert all(v["r"] is None and v["sufficiency"] == "nedostatek pozorování" for v in short["windows"])  # < 30: not computed
    assert short["quality"]["label"] == "nedostatečná"
    assert rel["stability"]["verdict"] == "stabilní" and rel["stability"]["same_sign_share"] == 1.0


def test_only_common_hours_are_used_and_returns_cover_the_same_interval():
    a, b = pair(300, 0.9, seed=2)
    g = hourly("XAUUSD@t", walk(a))
    x = hourly("EURUSD@t", walk(b), skip=set(range(100, 160)))  # the other market has 60 hours missing
    ks, ra, rb = im.aligned_returns(g, x, "H1")
    assert len(ks) == 300 - 60 - 1  # nothing is filled in
    k_gap = T0 + 160 * H
    i = ks.index(k_gap)  # the return across the hole spans hours 99 -> 160 for BOTH markets
    assert ra[i] == pytest.approx(math.log(g.points[k_gap] / g.points[T0 + 99 * H]))
    assert rb[i] == pytest.approx(math.log(x.points[k_gap] / x.points[T0 + 99 * H]))


def test_long_pause_is_not_a_return():
    g = hourly("XAUUSD@t", [100, 101, 102, 103])
    x = Series("X@t", "X", "X", "t", "price", False, 0.0, {T0: 1, T0 + H: 2, T0 + 2 * H + 5 * 86400: 3, T0 + 3 * H + 5 * 86400: 4})
    g.points = {T0: 100, T0 + H: 101, T0 + 2 * H + 5 * 86400: 102, T0 + 3 * H + 5 * 86400: 103}
    ks, ra, rb = im.aligned_returns(g, x, "H1")
    assert len(ks) == 2  # the 5-day jump is skipped


def test_yields_use_basis_point_changes():
    s = Series("US10Y@t", "US10Y", "10Y", "t", "yield", False, 15.5, {"2026-11-02": 4.80, "2026-11-03": 4.84})
    g = Series("XAUUSD@t", "XAUUSD", "g", "t", "price", False, 17.0, {"2026-11-02": 100.0, "2026-11-03": 101.0})
    ks, ra, rb = im.aligned_returns(g, s, "D1")
    assert rb == [pytest.approx(4.0)] and ra == [pytest.approx(math.log(1.01))]


def test_breakdown_and_reversal_are_detected():
    a1, b1 = pair(480, 0.8, seed=3)
    a2, b2 = pair(120, -0.6, seed=4)  # the last 120 hours run the other way
    g, x = hourly("XAUUSD@t", walk(a1 + a2)), hourly("X@t", walk(b1 + b2))
    rel = im.analyze(g, x, "H1")
    assert rel["breakdown"]["state"] == "obrat" and rel["breakdown"]["r_short"] < 0 < rel["breakdown"]["r_long"]
    assert rel["change"]["significant"] and rel["change"]["delta"] < -0.5
    a3, b3 = pair(120, 0.0, seed=5)
    rel2 = im.analyze(hourly("XAUUSD@t", walk(a1 + a3)), hourly("X@t", walk(b1 + b3)), "H1")
    assert rel2["breakdown"]["state"] == "rozpad"


def test_confirmation_follows_the_measured_sign():
    a, b = pair(600, -0.8, seed=6)  # like gold vs the dollar
    a[-24:] = [0.003] * 24  # gold rises for a day
    b[-24:] = [-0.003] * 24  # the other market falls: with r < 0 that CONFIRMS
    rel = im.analyze(hourly("XAUUSD@t", walk(a)), hourly("DXY.CFD@t", walk(b)), "H1")
    assert rel["move"]["verdict"] == "potvrzuje" and rel["move"]["gold_pct"] > 0
    b[-24:] = [0.003] * 24
    rel = im.analyze(hourly("XAUUSD@t", walk(a)), hourly("DXY.CFD@t", walk(b)), "H1")
    assert rel["move"]["verdict"] == "odporuje"


def test_weak_relationship_never_confirms_anything():
    a, b = pair(600, 0.05, seed=7)
    rel = im.analyze(hourly("XAUUSD@t", walk(a)), hourly("X@t", walk(b)), "H1")
    assert rel["move"]["verdict"] == "nelze"


def test_discovery_finds_unlisted_pairs_and_corrects_for_many_tests():
    rnd = random.Random(8)
    base = [rnd.gauss(0, 0.002) for _ in range(300)]
    s = [hourly("A@t", walk(base)), hourly("B@t", walk([0.9 * v + 0.1 * rnd.gauss(0, 0.002) for v in base]))]
    s += [hourly(f"N{i}@t", walk([rnd.gauss(0, 0.002) for _ in range(300)])) for i in range(6)]  # pure noise
    found = im.discover(s, "H1")
    assert [(f["a_key"], f["b_key"]) for f in found] == [("A@t", "B@t")]
    assert found[0]["q"] < 0.05 and found[0]["n"] == 120


def test_lead_lag_finds_a_market_that_moves_first():
    rnd = random.Random(9)
    lead = [rnd.gauss(0, 0.002) for _ in range(600)]
    gold = [0.0] + [0.7 * lead[i - 1] + 0.3 * rnd.gauss(0, 0.002) for i in range(1, 600)]
    hits = im.lead_lag(hourly("XAUUSD@t", walk(gold)), [hourly("X@t", walk(lead))], "H1")
    assert hits and hits[0]["lag"] == 1 and hits[0]["r"] > 0.5 and "ne spolehlivá předpověď" in hits[0]["text"]


def test_daily_closes_are_new_york_17h_and_mt5_days_map_to_the_trading_day():
    # Friday 6. 11. 2026 (EST): the bar 16:00–17:00 NY starts 21:00 UTC; the next one belongs to Monday's session
    fri = int(dt.datetime(2026, 11, 6, 21, tzinfo=dt.timezone.utc).timestamp())
    daily = im.ny_close_daily({fri - 2 * H: 1.0, fri: 2.0, fri + H: 3.0})
    assert daily == {"2026-11-06": 2.0}
    # MT5's D1 bar that starts Thursday 22:00 UTC is Friday's trading day
    assert im.mt5_trading_day(int(dt.datetime(2026, 11, 5, 22, tzinfo=dt.timezone.utc).timestamp())) == "2026-11-06"
    assert im.mt5_trading_day(int(dt.datetime(2026, 10, 29, 21, tzinfo=dt.timezone.utc).timestamp())) == "2026-10-30"  # EDT


def test_daily_quality_names_the_close_time_difference():
    a, b = pair(300, 0.7, seed=10)
    days = [(dt.date(2025, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(300)]
    g = Series("XAUUSD@t", "XAUUSD", "g", "t", "price", False, 17.0, dict(zip(days, walk(a))))
    y = Series("US10Y@t", "US10Y", "y", "t", "yield", False, 15.5, dict(zip(days, [4 + v * 10 for v in walk(b, 1.0)])))
    rel = im.analyze(g, y, "D1")
    assert any("posun" in i for i in rel["quality"]["issues"])


def test_module_is_off_in_the_live_cycle_until_the_user_turns_it_on(monkeypatch):
    """User's rule 8. 11.: no change of the live database without consent — no downloads, nothing stored."""
    from app.data import settings_store, store
    from app.market import intermarket_data

    calls = []
    monkeypatch.setattr(intermarket_data, "run", lambda *a, **k: calls.append("fetch") or {})
    monkeypatch.setattr(store, "cache_put", lambda *a, **k: calls.append("stored"))
    monkeypatch.setattr(store, "cache_get", lambda *a, **k: (None, None))
    monkeypatch.setattr(im, "compute", lambda session, tf: {"tf": tf, "relations": [], "computed_at": "2026-11-08T17:00:00+00:00"})
    monkeypatch.setattr(settings_store, "get", lambda path, default=None: False if path == "intermarket.enabled" else default)
    im._mem.clear()
    assert im.refresh(None) == {"enabled": False} and calls == []
    assert im.get(None, "D1", refresh=True)["tf"] == "D1" and calls == []  # computed on request, not stored
    monkeypatch.setattr(settings_store, "get", lambda path, default=None: True if path == "intermarket.enabled" else default)

    class Session:
        def commit(self):
            calls.append("commit")

    im._mem.clear()
    im.refresh(Session())
    assert calls == ["fetch", "commit", "stored", "stored", "stored", "stored"]  # D1 and H1: result + history
