import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.ingestion import run_ingest
from app.main import app
from app.scoring.xauusd import FOMC_DECISION_DATES_2026, SUPPORTED_HORIZONS
from tests.test_ingestion import _patch_all_connectors


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    yield TestClient(app)  # no `with`: lifespan (scheduler, real DB init) intentionally not run
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded(monkeypatch, db_session):
    _patch_all_connectors(monkeypatch)
    run_ingest.compute_and_store_score(db_session)
    return db_session


def _is_utc_iso(value: str) -> bool:
    return value.endswith("Z") or value.endswith("+00:00")


def test_dashboard_lists_all_eight_instruments_and_only_xauusd_has_a_score(client, seeded):
    body = client.get("/api/dashboard").json()
    codes = [i["code"] for i in body["instruments"]]
    assert codes == ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "US100", "US500", "WTI", "BTCUSD"]

    xau = body["instruments"][0]
    assert xau["status"] == "live"
    assert xau["summary"]["computed"] is True
    assert 0 <= xau["summary"]["score"] <= 100
    assert [h["horizon"] for h in xau["summary"]["horizons"]] == SUPPORTED_HORIZONS
    cov = xau["summary"]["data_coverage"]
    assert cov["total"] == 8 and cov["ok"] <= cov["backed"] <= cov["ok"] + cov["partial"]
    assert _is_utc_iso(xau["summary"]["computed_at"])

    for other in body["instruments"][1:]:
        assert other["status"] == "coming_soon"
        assert "summary" not in other  # nothing a client could render as a score


def test_dashboard_before_first_cycle_says_not_computed(client):
    xau = client.get("/api/dashboard").json()["instruments"][0]
    assert xau["summary"] == {"computed": False}


def test_all_horizon_scores_have_utc_timestamps_and_directions(client, seeded):
    body = client.get("/api/instruments/XAUUSD/scores").json()
    assert set(body) == set(SUPPORTED_HORIZONS)
    for snap in body.values():
        assert snap["direction"] in ("BULLISH", "NEUTRAL", "BEARISH")
        assert _is_utc_iso(snap["computed_at"])


def test_news_endpoint_groups_duplicate_reports_into_one_event(client, seeded):
    body = client.get("/api/instruments/XAUUSD/news").json()
    assert body["total_events"] == 1
    event = body["events"][0]
    assert event["report_count"] == 2
    assert {r["source"] for r in event["reports"]} == {"Fed", "gdelt:reuters.com"}
    assert _is_utc_iso(event["published_at"])


def test_upcoming_events_are_only_verified_fomc_dates_without_invented_times(client):
    body = client.get("/api/events/upcoming").json()
    today = dt.date.today().isoformat()
    for event in body["events"]:
        assert event["date"] in FOMC_DECISION_DATES_2026
        assert event["date"] >= today
        assert event["time"] is None
    assert "zatím napojené nejsou" in body["coverage_note"]


def test_history_entry_detail_resolves_the_data_behind_a_change(client, seeded):
    history = client.get("/api/instruments/XAUUSD/history", params={"horizon": "1-10d"}).json()
    assert history and "id" in history[0]
    detail = client.get(f"/api/instruments/XAUUSD/history/{history[0]['id']}").json()
    assert detail["news"], "related news must be resolved to real rows"
    assert detail["observations"], "related observations must be resolved to real rows"
    assert {o["source"] for o in detail["observations"]} == {"fred", "cftc"}


def test_coming_soon_instruments_have_no_score_or_news(client):
    assert client.get("/api/instruments/EURUSD/score").status_code == 404
    assert client.get("/api/instruments/EURUSD/news").status_code == 404


def test_status_reports_last_cycle_warnings(client, seeded):
    body = client.get("/api/status").json()
    assert body["last_cycle_finished_at"] is not None
    assert isinstance(body["last_cycle_warnings"], list)
    assert body["cycle_running"] is False


def test_analysis_endpoint_returns_trend_and_verdict_without_correlations(client, seeded):
    body = client.get("/api/instruments/XAUUSD/analysis").json()
    assert body["technical"]["trend"] in ("up", "down", "sideways")
    assert len(body["technical"]["history"]) == 180
    assert body["correlations"] is None  # removed on the user's request (2026-10-31)
    assert body["verdict"]["action"] in ("long", "short", "wait")
    assert body["verdict"]["reasons"]
    assert _is_utc_iso(body["computed_at"])

    dash = client.get("/api/dashboard").json()["instruments"][0]["summary"]
    assert dash["verdict"]["headline"] == body["verdict"]["headline"]


def test_analysis_endpoint_before_first_cycle_is_404(client):
    assert client.get("/api/instruments/XAUUSD/analysis").status_code == 404
