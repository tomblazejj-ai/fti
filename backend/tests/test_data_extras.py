"""NBP gold history, daily seasonal windows, gold COT commercials and the score history."""

import datetime as dt
import json

import httpx
import pytest

from app.connectors import nbp
from app.connectors.kraken import Candle
from app.ingestion import run_ingest
from app.market import cot_analysis, seasonality, tra
from app.models import TraScorePoint

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
REAL_NBP_FETCH = nbp.fetch_gold_usd  # conftest stubs it for every test; these tests use a fake HTTP client instead


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


# --- score history follows the model version -------------------------------------------------------

def test_old_score_history_is_rebuilt_when_the_rules_change(db_session):
    db_session.add(TraScorePoint(instrument="XAUUSD", computed_at=NOW - dt.timedelta(days=3), total=-3, components={"cot": 0}, source="backfill"))
    db_session.commit()
    assert run_ingest._model_outdated(db_session)
    pack = {"total": -7, "components": [{"key": "cot", "score": -1}]}
    run_ingest.store_tra_points(db_session, {"xau": pack, "usd": {**pack, "total": 9}}, NOW)
    last = db_session.query(TraScorePoint).order_by(TraScorePoint.computed_at.desc()).first()
    assert last.components["_v"] == tra.MODEL_VERSION and not run_ingest._model_outdated(db_session)
