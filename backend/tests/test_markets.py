"""Market overview for all instruments: FX and oil models, calendar feed, international data, API."""

import datetime as dt

import httpx
import pytest

from app.connectors import ffcal, intl_macro
from app.market import central_banks, fx_model, markets, oil_model

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
REAL_FF = ffcal.fetch_week
REAL_ECB, REAL_ONS, REAL_MOF = intl_macro.ecb_series, intl_macro.ons_series, intl_macro.mof_jgb_2y


def monthly(values: list[float], start=(2025, 1)) -> dict[str, float]:
    y, m = start
    out = {}
    for v in values:
        out[f"{y:04d}-{m:02d}-01"] = v
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def daily(value_fn, days=200) -> dict[str, float]:
    start = NOW.date() - dt.timedelta(days=days)
    return {(start + dt.timedelta(days=i)).isoformat(): value_fn(i) for i in range(days + 1)}


def currency(code, infl, unemp, gdp, rate_now, rate_then, policy) -> fx_model.CurrencyData:
    return fx_model.CurrencyData(
        code, core=monthly(infl), unemp=monthly(unemp), gdp_qoq={"2026-04-01": gdp},
        rate2y=daily(lambda i: rate_then + (rate_now - rate_then) * i / 200), policy=daily(lambda i: policy))


# --- FX model ---------------------------------------------------------------------------------

def test_pair_score_compares_both_currencies():
    # euro: inflation rising, rates rising, growth fine; dollar: inflation falling, rates falling
    eur = currency("EUR", [2.0] * 18 + [2.4, 2.8, 3.1], [6.5] * 21, 0.7, 3.0, 2.5, 2.5)
    usd = currency("USD", [3.0] * 18 + [2.7, 2.5, 2.3], [4.0] * 18 + [4.2, 4.3, 4.4], 0.2, 3.6, 4.2, 4.0)
    res = fx_model.score_pair(eur, usd, None, False, "euru", None, NOW)
    by = {c["key"]: c for c in res["components"]}
    assert by["rates"]["score"] >= 2  # the gap moved by +1.1 p.p. towards EUR
    assert by["inflation"]["score"] > 0 and by["labor"]["score"] > 0
    assert by["cot"]["score"] is None and "COT – hedgeové fondy" in res["missing"]
    assert res["possible"] == 8 and res["bias"] == "LONG" and res["score10"] >= 5
    assert "Inflace" in by["inflation"]["label"] and "USA" in by["inflation"]["text"]


def test_missing_inflation_is_listed_not_guessed():
    usd = currency("USD", [3.0] * 21, [4.0] * 21, 0.5, 4.0, 4.0, 4.0)
    jpy = fx_model.CurrencyData("JPY", unemp=monthly([2.6] * 21), gdp_qoq={"2026-04-01": 0.3}, rate2y=daily(lambda i: 1.9), policy=daily(lambda i: 1.0))
    res = fx_model.score_pair(usd, jpy, None, True, "jenu", None, NOW)
    by = {c["key"]: c for c in res["components"]}
    assert by["inflation"]["score"] is None and "Japonsko" in by["inflation"]["text"]
    assert "Inflace" in res["missing"]


def test_stale_core_inflation_falls_back_to_headline():
    c = fx_model.CurrencyData("EUR", core=monthly([2.3] * 12), cpi=monthly([1.9] * 21))  # core stops in 12/2025
    assert "celková" in fx_model.inflation(c)["text"]


def test_cot_for_usdjpy_is_read_the_other_way_round():
    rows = [{"lev_long": 30.0, "lev_short": 70.0}] * 10 + [{"lev_long": 70.0, "lev_short": 30.0}]
    assert fx_model.cot_component(rows, False, "jenu")["score"] == 1
    assert fx_model.cot_component(rows, True, "jenu")["score"] == -1


# --- oil ----------------------------------------------------------------------------------------

def test_oil_inventory_draws_support_the_price():
    days = [(dt.date(2020, 1, 3) + dt.timedelta(weeks=i)).isoformat() for i in range(360)]
    stocks = {d: 450000.0 for d in days}
    for d in days[-4:]:
        stocks[d] = 450000.0 - 12000 * (days.index(d) - len(days) + 5)
    c = oil_model.stocks_component(stocks)
    assert c["score"] >= 2 and "ubývají" in c["text"]


def test_supply_risk_needs_two_fresh_headlines():
    h = [{"title_en": "Missile strike hits Saudi oil field", "published_at": (NOW - dt.timedelta(hours=3)).isoformat()},
         {"title_en": "Houthi drones attack tanker in Red Sea", "published_at": (NOW - dt.timedelta(hours=20)).isoformat()},
         {"title_en": "Oil prices steady", "published_at": (NOW - dt.timedelta(hours=1)).isoformat()}]
    c = oil_model.supply_risk_component(h, NOW)
    assert c["score"] == 1 and "2 zprávy" in c["text"]
    assert oil_model.supply_risk_component(h[:1], NOW)["score"] == 0


# --- overview: arguments, watch list, retail -----------------------------------------------------

def test_arguments_follow_the_bias():
    comps = [{"key": "a", "label": "A", "score": 2, "max": 3, "text": "pro růst", "details": []},
             {"key": "b", "label": "B", "score": -1, "max": 2, "text": "pro pokles", "details": []}]
    sup, against = markets._arguments(comps, "SHORT")
    assert [x["label"] for x in sup] == ["B"] and [x["label"] for x in against] == ["A"]


def test_retail_crowd_against_the_score_supports_it():
    r = markets.retail_view(80.0, 5.0, "2026-10-27", "SHORT")
    assert r["tone"] == "support" and "SHORT" in r["head"]
    flipped = markets.retail_view(80.0, 5.0, "2026-10-27", "SHORT", invert=True)  # USD/JPY from the yen future
    assert flipped["long_pct"] == 20.0 and flipped["tone"] == "warn" or flipped["tone"] == "neutral"


def test_watch_list_keeps_important_events_of_the_pair():
    events = [
        {"datetime": "2026-11-05T12:00:00+00:00", "currency": "GBP", "title_en": "BoE", "title_cs": "Rozhodnutí BoE", "impact": 3},
        {"datetime": "2026-11-05T12:00:00+00:00", "currency": "JPY", "title_en": "x", "title_cs": "Japonsko", "impact": 3},
        {"datetime": "2026-11-03T15:00:00+00:00", "currency": "USD", "title_en": "JOLTS", "title_cs": "JOLTS", "impact": 1},
        {"datetime": "2026-12-20T12:00:00+00:00", "currency": "GBP", "title_en": "far", "title_cs": "Daleko", "impact": 3},
    ]
    w = markets.watch_list(events, ["GBP", "USD"], NOW, days=10)
    assert [x["title"] for x in w] == ["Rozhodnutí BoE"] and w[0]["impact_text"] == "Vysoký dopad na GBP"


def test_gold_score_is_scaled_from_the_11_category_model():
    tra = {"xau": {"total": -9, "missing": [], "components": [
        {"key": "rates", "label": "Úrokové sazby", "score": -2, "max": 2, "reason": "Fed"},
        {"key": "trend", "label": "Trend", "score": -7, "max": 23, "reason": "x"}]}}
    res = markets.gold_result(tra)
    assert res["score10"] == round(-9 / 25 * 10) and res["bias"] == "SHORT"


# --- calendar -----------------------------------------------------------------------------------

def test_forexfactory_rows_and_czech_names():
    rows = [{"title": "CPI y/y", "country": "USD", "date": "2026-11-12T08:30:00-05:00", "impact": "High", "forecast": "3.0%", "previous": "2.9%"},
            {"title": "German Prelim CPI m/m", "country": "EUR", "date": "2026-11-02T08:00:00-05:00", "impact": "Medium", "forecast": "", "previous": ""},
            {"title": "Something", "country": "XYZ", "date": "2026-11-02T08:00:00-05:00", "impact": "Low"}]
    ev = ffcal.parse(rows)
    assert len(ev) == 2 and ev[0]["impact"] == 3 and ev[0]["datetime"] == "2026-11-12T13:30:00+00:00" and ev[0]["forecast"] == "3.0%"
    assert ffcal.czech_title("CPI y/y") == "Inflace CPI r/r"
    assert ffcal.czech_title("Spanish Flash GDP q/q") == "HDP q/q (Španělsko, rychlý odhad)"
    assert ffcal.czech_title("Totally Unknown Index") is None


def test_forexfactory_keeps_history_and_survives_an_outage(tmp_path, monkeypatch):
    monkeypatch.setattr(ffcal, "_mem", {"at": None, "events": None})
    cache = tmp_path / "ff.json"
    ok = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[
        {"title": "CPI y/y", "country": "USD", "date": "2026-10-28T08:30:00-04:00", "impact": "High", "forecast": "", "previous": ""}])))
    assert len(REAL_FF(NOW, client=ok, cache_file=cache)) == 1
    monkeypatch.setattr(ffcal, "_mem", {"at": None, "events": None})
    down = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert len(REAL_FF(NOW, client=down, cache_file=cache)) == 1  # the cached week is still there


def test_central_bank_dates_in_local_time():
    ev = central_banks.upcoming({"EUR", "GBP"}, NOW, days=60)
    names = [(e["currency"], e["datetime"]) for e in ev]
    assert ("GBP", "2026-11-05T12:00:00+00:00") in names  # 12:00 London = 12:00 UTC in November
    assert ("EUR", "2026-12-17T13:15:00+00:00") in names  # 14:15 Frankfurt


# --- international data parsers -------------------------------------------------------------------

def test_ons_months_and_quarters():
    body = {"months": [{"date": "2026 AUG", "value": "3.3"}, {"date": "2026 SEP", "value": "3.5"}], "quarters": []}
    c = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    assert REAL_ONS("x/y", client=c) == {"2026-08-01": 3.3, "2026-09-01": 3.5}
    q = {"months": [], "quarters": [{"date": "2026 Q2", "value": "0.5"}]}
    c = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=q)))
    assert REAL_ONS("x/y", client=c) == {"2026-04-01": 0.5}


def test_ecb_csv_and_mof_csv():
    csv_body = "KEY,FREQ,TIME_PERIOD,OBS_VALUE\nICP,M,2026-08,2.0\nICP,M,2026-09,1.9\n"
    c = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=csv_body)))
    assert REAL_ECB("ICP", "M.U2", client=c) == {"2026-08-01": 2.0, "2026-09-01": 1.9}
    mof = "Interest Rate,,\nDate,1Y,2Y,3Y\n" + "\n".join(f"2026/9/{d},1.6,1.9{d % 10},2.0" for d in range(1, 26)) + "\n"
    c = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=mof.encode())))
    out = REAL_MOF(client=c)
    assert out["2026-09-02"] == pytest.approx(1.92) and len(out) == 25


# --- API ------------------------------------------------------------------------------------------

def test_markets_and_calendar_endpoints(db_session):
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import app
    from app.models import AnalysisSnapshot, Instrument

    inst = Instrument(code="XAUUSD", name="Zlato", pillar_config={})
    db_session.add(inst)
    db_session.commit()
    payload = {"markets": {"computed_at": NOW.isoformat(), "markets": [{"code": "EURUSD", "name": "EUR/USD", "score10": 3}], "method": "x",
                           "errors": []},
               "calendar_all": {"events": [{"datetime": NOW.isoformat(), "currency": "USD"}], "timezone": "Europe/Prague", "sources": []},
               "market": {"open": True}}
    db_session.add(AnalysisSnapshot(instrument_id=inst.id, computed_at=NOW, payload=payload))
    db_session.commit()
    app.dependency_overrides[get_session] = lambda: db_session
    try:
        client = TestClient(app)
        body = client.get("/api/markets").json()
        assert body["markets"][0]["code"] == "EURUSD" and body["market"]["open"] is True
        assert client.get("/api/markets/eurusd").json()["score10"] == 3
        assert client.get("/api/markets/BTCUSD").status_code == 404
        assert len(client.get("/api/calendar").json()["events"]) == 1
    finally:
        app.dependency_overrides.clear()


# --- technical outlooks, highlights, next events ---------------------------------------------------

def test_technical_outlooks_come_only_from_public_analyses_of_that_market():
    heads = [
        {"title": "EUR/USD Price Forecast: býci míří na 1,1200", "title_en": "EUR/USD Price Forecast: bulls eye 1.1200",
         "source": "FXEmpire prognózy", "url": "u1", "published_at": "2026-10-31T08:00:00+00:00", "translated": True},
        {"title": "Fed nechal sazby", "title_en": "Fed holds rates", "source": "CNBC", "url": "u2",
         "published_at": "2026-10-31T09:00:00+00:00", "translated": True},
        {"title": "Gold technical outlook", "title_en": "Gold technical outlook", "source": "Investing.com technika komodit", "url": "u3",
         "published_at": "2026-10-31T07:00:00+00:00", "translated": False},
    ]
    eur = markets.technical_outlooks(heads, "EURUSD")
    assert [h["url"] for h in eur] == ["u1"]
    assert [h["url"] for h in markets.technical_outlooks(heads, "XAUUSD")] == ["u3"]
    # technical items never end up among the ordinary news of the market
    assert all(n["url"] != "u1" for n in markets.instrument_news(heads, "EURUSD"))


def test_highlights_are_deduplicated_and_newest_first():
    key = [{"title": "Fed holds", "source": "A", "url": "k1", "published_at": "2026-10-31T09:00:00+00:00", "translated": False, "impact": "bullish"}]
    cards = [{"code": "EURUSD", "news": [{"title": "Fed holds!", "source": "B", "url": "k2", "published_at": "2026-10-31T09:30:00+00:00", "translated": False},
                                          {"title": "Euro up", "source": "C", "url": "k3", "published_at": "2026-10-31T10:00:00+00:00", "translated": False}]}]
    out = markets.highlights(key, cards)
    assert [h["url"] for h in out] == ["k3", "k1"]
    assert out[1]["market"] == "XAUUSD" and out[1]["impact"] == "bullish"


def test_next_events_keep_only_upcoming_high_impact_of_the_four_currencies():
    ev = [
        {"datetime": "2026-10-31T09:00:00+00:00", "currency": "USD", "title_en": "old", "title_cs": "Staré", "impact": 3},
        {"datetime": "2026-10-31T12:30:00+00:00", "currency": "USD", "title_en": "PCE", "title_cs": "Inflace PCE", "impact": 3, "forecast": "2.8%"},
        {"datetime": "2026-10-31T13:00:00+00:00", "currency": "EUR", "title_en": "low", "title_cs": "Nízký", "impact": 2},
        {"datetime": "2026-10-31T14:00:00+00:00", "currency": "CNY", "title_en": "cn", "title_cs": "Čína", "impact": 3},
    ]
    out = markets.next_events(ev, NOW)
    assert [e["title"] for e in out] == ["Inflace PCE"] and out[0]["forecast"] == "2.8%"
