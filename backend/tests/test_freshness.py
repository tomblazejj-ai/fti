import datetime as dt

from app.connectors import bullionvault
from app.ingestion import run_ingest
from app.market import market_status, sources
from app.scoring.xauusd import MacroPoint

UTC = dt.timezone.utc


def test_spot_gold_market_hours_weekend_and_daily_pause():
    sunday = market_status.status(dt.datetime(2026, 10, 4, 17, 56, tzinfo=UTC))
    assert not sunday["open"] and sunday["reason"] == "víkend"
    assert sunday["next_open"] == "2026-10-04T22:00:00+00:00"  # Sun 18:00 New York = Mon 00:00 Praha
    monday = market_status.status(dt.datetime(2026, 10, 5, 9, tzinfo=UTC))
    assert monday["open"] and monday["closes_at"] == "2026-10-05T21:00:00+00:00"
    pause = market_status.status(dt.datetime(2026, 10, 5, 21, 30, tzinfo=UTC))
    assert pause["reason"] == "denní pauza" and pause["next_open"] == "2026-10-05T22:00:00+00:00"


def test_price_check_flags_disagreeing_sources():
    good = market_status.price_check(4142.83, 4143.92, 4139.5)
    assert good["ok"] and good["max_gap_pct"] == 0.08
    bad = market_status.price_check(4142.83, 4170.0, None)
    assert bad["ok"] is False and "rozcházejí" in bad["text"]
    assert market_status.price_check(4142.83, None, None)["ok"] is None


BV_XML = """<envelope><pitches>
<pitch securityClassNarrative="GOLD" securityId="AUXLN" considerationCurrency="USD">
 <buyPrices><price actionIndicator="B" quantity="0.075" limit="133100"/></buyPrices>
 <sellPrices><price actionIndicator="S" quantity="0.075" limit="133360"/></sellPrices>
</pitch>
<pitch securityClassNarrative="SILVER" securityId="AGXLN" considerationCurrency="USD">
 <buyPrices><price actionIndicator="B" quantity="1" limit="1941"/></buyPrices>
 <sellPrices><price actionIndicator="S" quantity="1" limit="1949"/></sellPrices>
</pitch></pitches></envelope>"""


def test_bullionvault_price_per_kg_becomes_usd_per_ounce():
    q = bullionvault.parse(BV_XML)
    assert q["vault"] == "AUXLN" and q["mid"] == 4143.92


def test_sources_panel_says_closed_market_is_fine_and_flags_late_data():
    now = dt.datetime(2026, 10, 4, 18, tzinfo=UTC)
    payload = {
        "mtf": {"price_time": "2026-10-02T20:45:00+00:00"},
        "cot": {"as_of": "2026-09-29", "schedule": {"late": False}},
        "calendar": {"events": [{"past": False}]},
        "news": {"top": [{"published_at": "2026-10-04T15:00:00+00:00"}], "count": 9, "hours": 72},
        "gold_vol": {"as_of": "2026-09-10"},
    }
    macro = {"core_cpi": MacroPoint(actual=3.1, previous=3.0, period="2026-08-01", frequency="M"),
             "real_yield_10y": MacroPoint(actual=None, previous=None, frequency="D")}
    rows = {r["key"]: r for r in sources.build(payload, macro, now, market_open=False)}
    assert rows["price"]["status"] == "closed"
    assert rows["macro:core_cpi"]["status"] == "ok"
    assert rows["macro:real_yield_10y"]["status"] == "missing"
    assert rows["gvz"]["status"] == "late"
    assert rows["cot"]["status"] == "ok"


def test_market_refresh_waits_for_the_first_full_cycle(db_session, monkeypatch):
    monkeypatch.setattr(run_ingest, "_LAST_MACRO", {})
    assert run_ingest.refresh_market(db_session) is False
