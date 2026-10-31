"""The trading assistant: S/D zones, NBP gold history, seasonal windows, the checklist and the week plan."""

import datetime as dt
import json

import httpx
import pytest

from app.connectors import nbp
from app.connectors.kraken import Candle
from app.ingestion import run_ingest
from app.market import cot_analysis, seasonality, setup, tra, zones
from app.models import TraScorePoint

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
REAL_NBP_FETCH = nbp.fetch_gold_usd  # conftest stubs it for every test; these tests use a fake HTTP client instead


def _c(i: int, o: float, h: float, low: float, c: float, days: int = 1) -> Candle:
    return Candle(dt.datetime(2025, 1, 1, tzinfo=UTC) + dt.timedelta(days=i * days), o, h, low, c)


def _drift(n: int, start: float, step: float = 0.0, days: int = 1, wiggle: float = 4.0) -> list[Candle]:
    out = []
    p = start
    for i in range(n):
        o = p
        c = p + step + (wiggle if i % 2 else -wiggle)
        out.append(_c(i, o, max(o, c) + 3, min(o, c) - 3, c, days))
        p = c
    return out


def _with_rally(days: int = 1) -> list[Candle]:
    """Quiet market, a small base candle, a strong rally, then drift back down towards the base."""
    c = _drift(30, 100.0, days=days)
    i = len(c)
    c.append(_c(i, 100, 103, 98, 101, days))  # base
    c.append(_c(i + 1, 101, 140, 100, 138, days))  # impulse up
    c.append(_c(i + 2, 138, 150, 136, 148, days))
    p = 148.0
    for k in range(i + 3, i + 20):  # slow drift back down, never closing below the zone
        c.append(_c(k, p, p + 2, p - 5, p - 2.5, days))
        p -= 2.5
    return c


def test_demand_zone_is_the_base_before_a_rally():
    found = zones.find_zones(_with_rally(), "D1")
    demand = [z for z in found if z["kind"] == "demand"]
    assert demand, found
    z = demand[-1]
    assert z["distal"] == 98 and z["proximal"] == 101  # base low and body top
    assert z["touches"] == 0 and z["fresh"] and z["departure"] >= 1.25


def test_a_close_through_the_zone_kills_it_but_a_forming_candle_does_not():
    c = _with_rally()
    n = len(c)
    broken = c + [_c(n, 104, 105, 90, 92), _c(n + 1, 92, 95, 91, 94)]  # finished candle closes below 98
    assert not [z for z in zones.find_zones(broken, "D1") if z["kind"] == "demand" and z["distal"] == 98]
    forming = c + [_c(n, 104, 105, 90, 92)]  # the same move, still forming
    assert [z for z in zones.find_zones(forming, "D1") if z["kind"] == "demand" and z["distal"] == 98]


def test_tpo_activity_and_poc_inside_the_zone():
    candles = _drift(60, 100.0, wiggle=1.0) + [_c(60 + i, 150 + i * 5, 156 + i * 5, 149 + i * 5, 155 + i * 5) for i in range(10)]
    profile = zones.tpo_profile(candles)  # lots of time around 100, little higher up
    ratio, poc = zones.zone_activity(profile, 98, 102)
    assert ratio > 1.0 and 98 <= poc <= 102
    far, _ = zones.zone_activity(profile, 200, 210)
    assert far is None or far < 0.6


def test_analyze_marks_daily_zones_inside_weekly_ones():
    weekly = _with_rally(days=7)
    daily = _with_rally()
    out = zones.analyze(weekly, daily, daily[-1].close)
    d1 = out["tf"]["D1"]["demand"]
    assert d1 and d1[0]["in_weekly"] is True and d1[0]["distance_pct"] > 0
    assert out["atr_d1"] > 0 and "TPO" in out["method"]


# --- NBP -----------------------------------------------------------------------------------

def test_nbp_converts_pln_per_gram_to_usd_per_ounce_and_caches(tmp_path, monkeypatch):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if "cenyzlota" in req.url.path:
            return httpx.Response(200, json=[{"data": f"2025-{m:02d}-{d:02d}", "cena": 400.0} for m in range(1, 13) for d in range(1, 29)])
        return httpx.Response(200, json={"rates": [{"effectiveDate": f"2025-{m:02d}-{d:02d}", "mid": 4.0}
                                                   for m in range(1, 13) for d in range(1, 29)]})

    monkeypatch.setattr(nbp, "_mem", {"at": None, "data": None})
    cache = tmp_path / "nbp.json"
    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = REAL_NBP_FETCH(dt.datetime(2025, 12, 31, tzinfo=UTC), client=client, sleep_fn=lambda s: None, cache_file=cache)
    assert out["2025-03-03"] == pytest.approx(400 * 31.1034768 / 4.0, rel=1e-4)
    assert json.loads(cache.read_text(encoding="utf-8"))["unit"] == "USD/oz"
    assert any("exchangerates" in c for c in calls)


def test_nbp_without_answer_and_cache_says_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(nbp, "_mem", {"at": None, "data": None})
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(nbp.NbpUnavailableError):
        REAL_NBP_FETCH(NOW, client=client, sleep_fn=lambda s: None, cache_file=tmp_path / "x.json")


# --- seasonal windows ------------------------------------------------------------------------

def _seasonal_prices() -> dict[str, float]:
    """Every year the price rises 3 % between 20 October and 10 November, otherwise flat."""
    out = {}
    d = dt.date(2013, 1, 2)
    while d <= dt.date(2026, 10, 16):
        start, end = dt.date(d.year, 10, 20), dt.date(d.year, 11, 10)
        frac = 0.0 if d < start else 1.0 if d >= end else (d - start).days / (end - start).days
        if d.weekday() < 5:
            out[d.isoformat()] = 1000.0 * (1 + 0.03 * frac)
        d += dt.timedelta(days=1)
    return out


def test_daily_view_finds_the_recurring_window():
    v = seasonality.daily_view(_seasonal_prices(), NOW, "gold", "Zlato")
    up = v["best_up"]
    assert up and up["win"] == 100 and up["avg"] >= 2.0
    assert dt.date.fromisoformat(up["from"]) <= dt.date(2026, 10, 25)
    assert "rostlo" in v["texts"][0] and v["lean"] == 1
    assert set(v["path"]["lines"]) == {"5", "10"}  # 15 years of daily data do not exist → no 15-year line
    assert v["path"]["lines"]["10"][v["path"]["offsets"].index(0)] == 0.0


# --- COT for gold: commercials and open interest ------------------------------------------------

def _gold_rows(comm_last: float, oi_last: float, flow: float = 0.0) -> list[dict]:
    rows = []
    for i in range(60):
        rows.append({"date": (dt.date(2025, 1, 7) + dt.timedelta(weeks=i)).isoformat(), "spec_net": 100.0 + (flow if i >= 56 else 0),
                     "spec_long": 150.0, "spec_short": 50.0, "comm_net": -200.0 + (i % 5), "open_interest": 1000.0})
    rows[-1]["comm_net"] = comm_last
    rows[-1]["open_interest"] = oi_last
    return rows


def test_commercials_extreme_and_open_interest():
    a = cot_analysis.analyze(_gold_rows(-100.0, 950.0), now=NOW)
    assert a["commercials"]["extreme"] == "bullish" and "růst" in a["commercials"]["text"]
    assert a["open_interest_view"]["state"] == "falling"
    score, info = tra.gold_cot_score(_gold_rows(-100.0, 1000.0))
    assert info["comm_pts"] == 1 and score >= 1
    _, damped = tra.gold_cot_score(_gold_rows(-200.0, 900.0, flow=400.0))
    assert damped["oi_damped"] is True


# --- the checklist ------------------------------------------------------------------------------

def _zone(kind: str, lo: float, hi: float, tf: str = "D1", dist: float = 2.0, **kw) -> dict:
    prox, distal = (hi, lo) if kind == "demand" else (lo, hi)
    return {"tf": tf, "kind": kind, "lo": lo, "hi": hi, "proximal": prox, "distal": distal, "formed": "2026-09-25T00:00:00+00:00",
            "touches": 0, "fresh": True, "last_touch": None, "pivots": 2, "strength": 70, "departure_atr": 2.0,
            "distance_pct": dist, "inside": False, "activity": "active", "activity_ratio": 1.3, "poc": (lo + hi) / 2, **kw}


ZONES = {
    "price": 4157.0, "atr_d1": 70.0,
    "tf": {
        "W1": {"demand": [_zone("demand", 3993, 4126, "W1", 0.75)], "supply": [_zone("supply", 4250, 4320, "W1", 2.2)]},
        "D1": {"demand": [_zone("demand", 4039, 4064, dist=2.2, in_weekly=True)],
               "supply": [_zone("supply", 4259, 4308, dist=2.5, in_weekly=True)]},
    },
}


def _tra(total: int, cot: int) -> dict:
    return {"xau": {"total": total, "word": "Medvědí" if total < 0 else "Býčí", "strength": "",
                    "components": [{"key": "cot", "score": cot}]}}


def test_all_confirmations_make_an_a_plus_short_with_a_plan():
    s = setup.build(ZONES, _tra(-7, -1), {"lean": -1, "next30": {"up": 2, "n": 10, "avg": -1.5}, "texts": []}, None, None,
                    {"state": "clear"}, None, NOW)
    short = s["setups"]["short"]
    assert s["primary"] == "short" and short["grade"] == "A+" and short["ok"] == 6
    plan = short["plan"]
    assert plan["entry"] == 4259 and plan["stop"] == pytest.approx(4308 + 0.25 * 70) and plan["target"] == 4126
    assert plan["rr"] == pytest.approx(round((4259 - 4126) / (4308 + 17.5 - 4259), 1))
    assert "SHORT" in s["headline"] and "A+" in s["headline"]


def test_macro_cot_and_seasonality_against_means_leave_it():
    s = setup.build(ZONES, _tra(-7, -2), {"lean": -1, "next30": {"up": 2, "n": 10, "avg": -1.5}, "texts": []}, None, None,
                    {"state": "clear"}, None, NOW)
    long = s["setups"]["long"]
    assert long["grade"] == "skip" and "Nech být" in long["verdict"]


def test_red_news_turns_the_answer_into_wait():
    lock = {"state": "lock", "text": "Za 45 min vychází Inflace CPI (USA) — podle pravidel teď nevstupuj do nových obchodů."}
    s = setup.build(ZONES, _tra(-7, -1), None, -1, None, lock, None, NOW)
    assert s["action"] == "wait" and "nevstupuj" in s["headline"] and s["timing"][0]["state"] == "bad"


def test_zone_without_activity_is_weak():
    zt = json.loads(json.dumps(ZONES))
    zt["tf"]["D1"]["supply"][0]["activity"] = "none"
    s = setup.build(zt, _tra(-7, -1), None, -1, None, None, None, NOW)
    assert s["setups"]["short"]["grade"] == "C"


def test_week_plan_lists_the_week_and_the_rules():
    cal = {"events": [{"date": "2026-10-20", "time": "14:30", "name": "Inflace CPI (USA)", "importance": 3, "past": False},
                      {"date": "2026-10-27", "time": "14:30", "name": "Mimo týden", "importance": 3, "past": False}]}
    s = setup.build(ZONES, _tra(-7, -1), None, -1, None, None, None, NOW)
    w = setup.weekly_plan(s, cal, _tra(-7, -1), None, None, NOW)  # Saturday → the coming week
    assert w["next_week"] and w["monday"] == "2026-10-19" and w["title"] == "Plán na příští týden"
    assert [len(d["events"]) for d in w["days"]] == [0, 1, 0, 0, 0]
    assert any("Červené zprávy: út 14:30 Inflace CPI" in line for line in w["lines"])
    assert setup.week_range(dt.datetime(2026, 10, 14, 9, tzinfo=UTC))[0] == dt.date(2026, 10, 12)


# --- score history follows the model version -------------------------------------------------------

def test_old_score_history_is_rebuilt_when_the_rules_change(db_session):
    db_session.add(TraScorePoint(instrument="XAUUSD", computed_at=NOW - dt.timedelta(days=3), total=-3, components={"cot": 0}, source="backfill"))
    db_session.commit()
    assert run_ingest._model_outdated(db_session)
    pack = {"total": -7, "components": [{"key": "cot", "score": -1}]}
    run_ingest.store_tra_points(db_session, {"xau": pack, "usd": {**pack, "total": 9}}, NOW)
    last = db_session.query(TraScorePoint).order_by(TraScorePoint.computed_at.desc()).first()
    assert last.components["_v"] == tra.MODEL_VERSION and not run_ingest._model_outdated(db_session)
