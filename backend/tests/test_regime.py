"""Market Regime Detection (Ú2, 9. 11. 2026): what kind of market gold is in — trend or range, volatility, risk mood,
dollar, real yields, intermarket relations. Deterministic from the engine's own results (a historical test can recompute
it), every input with source and time, closed daily candles only for the volatility, context — never a vote in the
verdict; a change of regime asks the AI for a new analysis; the AI and the app get it with its sources."""

import copy
import datetime as dt
import math

import pytest

from app.connectors.kraken import Candle
from app.market import mtf, regime

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 9, 12, 0, tzinfo=UTC)  # Monday noon; Monday's daily candle (from Sunday 22:00 UTC) is forming


def _tf(tf, direction, adx, word=None):
    words = {"up": "Nahoru", "down": "Dolů", "sideways": "Do strany"}
    return {"tf": tf, "direction": direction, "word": word or words[direction], "adx": adx, "ema20": 4064.39, "ema50": 4149.71,
            "close": 4055.42, "as_of": "2026-11-08T22:00:00+00:00"}


def _mtf(d1=("down", 26.3), h4=("up", 25.4)):
    return {"timeframes": [_tf("H4", *h4), _tf("D1", *d1)]}


def _days(n=320, base_range=60.0, last_ranges=(), end=NOW):
    """n closed trading days ending Friday 6. 11. (+ Monday 9. 11. forming), range base_range, the last ones as given."""
    out, d, price = [], dt.date(2026, 11, 6), 4000.0
    dates = []
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d)
        d -= dt.timedelta(days=1)
    dates.reverse()
    ranges = [base_range * (1 + 0.1 * math.sin(i / 7)) for i in range(n)]
    for k, r in enumerate(last_ranges):
        ranges[n - len(last_ranges) + k] = r
    for day, r in zip(dates, ranges):
        start = dt.datetime(day.year, day.month, day.day, tzinfo=UTC) - dt.timedelta(hours=2)  # 22:00 UTC the day before
        out.append(Candle(start, price, price + r / 2, price - r / 2, price + 1))
        price += 1
    forming = Candle(dt.datetime(2026, 11, 8, 22, tzinfo=UTC), price, price + 400, price - 400, price)  # a huge forming day
    return out + [forming]


IM_ITEMS = {"items": [
    {"id": "VIXCLS", "label": "VIX", "last": 28.18, "as_of": "2026-11-05", "change_5": 10.98, "change_20": 12.77, "corr_gold": -0.29,
     "corr_days": 60, "stale": False, "source": "FRED VIXCLS"},
    {"id": "SP500", "label": "S&P 500", "last": 7353.73, "as_of": "2026-11-05", "change_5": -4.75, "change_20": -5.3, "corr_gold": 0.38,
     "corr_days": 60, "stale": False, "source": "FRED SP500"},
    {"id": "DFII10", "label": "Reálný výnos", "last": 2.6, "as_of": "2026-11-05", "change_5": -0.03, "change_20": -0.32,
     "corr_gold": -0.19, "corr_word": "slabá opačná", "corr_days": 60, "stale": False, "source": "FRED DFII10"},
    {"id": "DGS10", "label": "Výnos 10 let", "last": 4.84, "as_of": "2026-11-05", "change_5": -0.14, "change_20": -0.44,
     "corr_gold": -0.23, "corr_days": 60, "stale": False, "source": "FRED DGS10"},
]}
DXY = {"price": 102.308, "source": "DXY přepočet ICE", "trends": {"timeframes": [
    {"tf": "D1", "direction": "up", "word": "Nahoru", "adx": 19.4, "as_of": "2026-11-09T00:00:00+00:00"},
    {"tf": "W1", "direction": "up", "word": "Nahoru", "adx": 21.8, "as_of": "2026-11-05T00:00:00+00:00"}]}}


def _rel(label, r, stability, breakdown, b="X"):
    return {"b": b, "label": label, "windows": [{"window": 60, "r": r}], "stability": {"verdict": stability},
            "breakdown": {"state": breakdown}}


IM_D1 = {"main_window": 60, "computed_at": "2026-11-09T08:32:00+00:00", "relations": [
    _rel("EUR/USD", 0.486, "stabilní", "drží"), _rel("Dolarový index DXY* (vzorec ICE)", -0.485, "stabilní", "drží", b="DXY*@mt5"),
    _rel("S&P 500 (oficiální uzávěrka)", 0.386, "převážně stejný směr", "bez pevného dlouhodobého vztahu")]}
SOURCES = {"D1": "Dukascopy", "H4": "Dukascopy"}


def _compute(**kw):
    args = dict(d1_candles=_days(), mtf=_mtf(), technical={"sma200_pct": 9.89, "volatility20": 24.4, "as_of": "2026-11-09"},
                gold_vol={"last": 25.83, "median": 26.62, "p75": 30.06, "as_of": "2026-11-05"}, intermarket=IM_ITEMS, dxy=DXY,
                im_d1=IM_D1, sources=SOURCES, as_of=NOW.isoformat())
    args.update(kw)
    return regime.compute(**args)


def _dim(rg, key):
    return next(d for d in rg["dimensions"] if d["key"] == key)


# --- each dimension ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("d1, h4, state, words", [
    (("down", 26.3), ("up", 25.4), "trend_down", ["Klesající trend", "H4 jde proti D1"]),
    (("up", 31.0), ("up", 22.0), "trend_up", ["Rostoucí trend", "H4 jde stejným směrem"]),
    (("down", 22.0), ("sideways", 15.0), "weak_down", ["Slabý klesající trend", "H4 je bez směru"]),
    (("up", 17.0), ("up", 30.0), "range", ["Pásmo bez trendu"]),
    (("sideways", 30.0), ("down", 30.0), "range", ["Pásmo bez trendu"]),
])
def test_trend_from_adx_and_direction(d1, h4, state, words):
    d = _dim(_compute(mtf=_mtf(d1, h4)), "trend")
    assert d["state"] == state and d["available"]
    text = d["word"] + " " + d["detail"] + " " + (d["implication"] or "")
    assert all(w in text for w in words)
    assert {i["name"] for i in d["inputs"]} >= {"ADX D1", "směr D1"} and d["inputs"][0]["source"] == "Dukascopy"


def test_trend_without_daily_data_is_said_not_guessed():
    d = _dim(_compute(mtf={"timeframes": [_tf("H4", "up", 30)]}), "trend")
    assert not d["available"] and d["state"] == "unknown" and d["word"] == "nelze určit"


def test_volatility_is_a_percentile_of_closed_days_only():
    calm = _compute(d1_candles=_days(last_ranges=[30.0]))  # the last closed day the calmest of the year
    hot = _compute(d1_candles=_days(last_ranges=[200.0] * 6))  # a week of very wide days
    assert _dim(calm, "volatilita")["state"] in ("low", "normal") and _dim(hot, "volatilita")["state"] == "extreme"
    v = _dim(hot, "volatilita")
    closed = _days(last_ranges=[200.0] * 6)[:-1]
    assert hot["atr"]["d1"] == pytest.approx(mtf.atr(closed), abs=0.01)  # the same ATR the trend tables use
    assert hot["atr"]["as_of"] == "2026-11-06" and "uzavřené dny do 2026-11-06" in v["detail"]
    # the huge forming Monday changes nothing (it is not closed yet)
    without_forming = _compute(d1_candles=_days(last_ranges=[200.0] * 6)[:-1])
    assert without_forming["atr"] == hot["atr"]
    assert "GVZ" in v["detail"] and any(i["name"] == "GVZ" for i in v["inputs"])


def test_volatility_needs_a_year_of_atr():
    d = _dim(_compute(d1_candles=_days(n=100)), "volatilita")
    assert not d["available"] and "120" in d["detail"]


def test_risk_mood_from_vix_and_stocks_and_what_it_means_for_gold_now():
    d = _dim(_compute(), "riziko")
    assert d["state"] == "risk_off" and "zvýšená nervozita" in d["detail"]
    assert "souběžně" in d["implication"] and "bezpečného přístavu" in d["implication"]  # r +0.38: not a safe haven now
    calm = copy.deepcopy(IM_ITEMS)
    calm["items"][0].update(last=13.2, change_5=-0.5)
    calm["items"][1].update(change_20=2.1, corr_gold=-0.35)
    d = _dim(_compute(intermarket=calm), "riziko")
    assert d["state"] == "risk_on" and "klid" in d["detail"] and "proti akciím" in d["implication"]
    mid = copy.deepcopy(IM_ITEMS)
    mid["items"][0].update(last=18.0, change_5=0.5)
    mid["items"][1].update(change_20=-1.0, corr_gold=0.1)
    d = _dim(_compute(intermarket=mid), "riziko")
    assert d["state"] == "neutral" and "slabý" in d["implication"]


def test_dollar_and_real_yields():
    assert _dim(_compute(), "dolar")["state"] == "usd_up"
    assert "−0,48" in _dim(_compute(), "dolar")["implication"]  # gold × DXY* from Intermarket (r −0.485)
    mixed = copy.deepcopy(DXY)
    mixed["trends"]["timeframes"][1]["direction"] = "down"
    assert _dim(_compute(dxy=mixed), "dolar")["state"] == "usd_mixed"
    assert _dim(_compute(), "sazby")["state"] == "real_down"
    up = copy.deepcopy(IM_ITEMS)
    up["items"][2]["change_20"] = 0.2
    assert _dim(_compute(intermarket=up), "sazby")["state"] == "real_up"
    up["items"][2]["change_20"] = 0.1
    assert _dim(_compute(intermarket=up), "sazby")["state"] == "real_flat"


def test_intermarket_relations_and_their_age():
    d = _dim(_compute(), "korelace")
    assert d["state"] == "stable" and "EUR/USD" in d["detail"] and "2026-11-09 08:32" in d["detail"]
    broken = copy.deepcopy(IM_D1)
    broken["relations"][0]["breakdown"]["state"] = "rozpad"
    assert _dim(_compute(im_d1=broken), "korelace")["state"] == "breaking"
    assert not _dim(_compute(im_d1=None), "korelace")["available"]


# --- the whole regime -------------------------------------------------------------------------------------------------

def test_regime_is_deterministic_and_says_what_is_missing():
    a, b = _compute(), _compute()
    assert a == b
    assert a["label"] == "Klesající trend · volatilita " + _dim(a, "volatilita")["word"].lower() + " · riziková averze"
    assert a["missing"] == [] and "kontext, ne hlas" in a["note"]
    partial = _compute(im_d1=None, intermarket=None)
    assert set(partial["missing"]) == {"Riziková nálada", "Reálné výnosy", "Vztahy se zlatem"}


def test_a_change_of_regime_is_found_only_where_it_matters():
    old = _compute()
    new = _compute(mtf=_mtf(("down", 17.0), ("up", 25.4)))  # trend → range
    assert regime.change(new, old) == ["Trend: klesající trend → pásmo bez trendu"]
    up = copy.deepcopy(IM_ITEMS)
    up["items"][2]["change_20"] = 0.2  # real yields turn: shown, but not a reason for a new AI analysis
    assert regime.change(_compute(intermarket=up), old) == []
    assert regime.change(_compute(intermarket=None), old) == []  # a dimension that went missing is no change
    assert regime.change(old, None) == []


def test_verdict_does_not_depend_on_the_regime():
    """Context, not a vote: the rule verdict has no regime input (until the historical test, Ú6, shows it helps)."""
    import inspect

    from app.verdict import build_verdict

    assert "regime" not in inspect.signature(build_verdict).parameters


# --- integration: the cycle, the AI, the triggers, the app ----------------------------------------------------------

def test_old_intermarket_result_is_not_used(monkeypatch):
    from app.data import store
    from app.market import service

    payload = {"computed_at": "2026-11-05T08:00:00+00:00", "relations": []}
    monkeypatch.setattr(store, "cache_get", lambda key, session=None: (payload, None))
    assert service._recent_intermarket(NOW) is None
    payload["computed_at"] = "2026-11-09T08:00:00+00:00"
    assert service._recent_intermarket(NOW) is payload


def test_ai_gets_the_regime_with_sources_and_the_roles_that_need_it(db_session):
    from app.ai import context, pipeline
    from app.models import AnalysisSnapshot, Instrument
    from tests.test_ai_trade import PAYLOAD

    inst = Instrument(code="XAUUSD", name="Gold", pillar_config={})
    db_session.add(inst)
    db_session.commit()
    payload = copy.deepcopy(PAYLOAD)
    payload["regime"] = _compute(im_d1=None)
    db_session.add(AnalysisSnapshot(instrument_id=inst.id, computed_at=NOW, payload=payload))
    db_session.commit()
    fs, meta = context.trade(db_session, "XAUUSD", quote_fn=lambda c: {"available": False})
    rg = [f for f in fs if f.get("oblast") == "rezim"]
    assert rg[0]["co"] == "Režim trhu XAUUSD" and "Klesající trend" in rg[0]["hodnota"]
    trend = next(f for f in rg if f["co"] == "Režim trhu — Trend")
    assert trend["zdroj"] == "Dukascopy" and "ADX 26,3" in trend["text"]
    assert any("vztahy se zlatem" in m for m in meta["missing"])  # Intermarket missing: said, not hidden
    roles = {role: areas for role, areas, *_ in pipeline.STAGES}
    assert "rezim" in roles["technika"] and "rezim" in roles["makro"] and "rezim" in pipeline.SYNTHESIS[1]


def test_regime_change_asks_the_ai_for_a_new_analysis():
    from app.ai import triggers

    old = {"regime": _compute(), "markets": {"markets": []}}
    new = {"regime": _compute(mtf=_mtf(("down", 17.0), ("up", 25.4))), "markets": {"markets": []}}
    assert triggers.trade_reason(new, old, NOW, NOW - dt.timedelta(minutes=30)) == (
        "normal", "režim trhu: Trend: klesající trend → pásmo bez trendu")


def test_app_and_phone_get_the_regime(db_session):
    from fastapi.testclient import TestClient

    from app import export_static
    from app.db import get_session
    from app.main import app
    from app.models import AnalysisSnapshot, Instrument

    app.dependency_overrides[get_session] = lambda: db_session
    try:
        client = TestClient(app)
        inst = Instrument(code="XAUUSD", name="Gold", pillar_config={})
        db_session.add(inst)
        db_session.commit()
        db_session.add(AnalysisSnapshot(instrument_id=inst.id, computed_at=NOW, payload={"markets": {"markets": []}}))
        db_session.commit()
        assert client.get("/api/regime").status_code == 404  # not computed yet: said, not invented
        db_session.add(AnalysisSnapshot(instrument_id=inst.id, computed_at=NOW + dt.timedelta(minutes=30),
                                        payload={"markets": {"markets": []}, "regime": _compute()}))
        db_session.commit()
        r = client.get("/api/regime").json()
        assert r["label"].startswith("Klesající trend") and len(r["dimensions"]) == 6 and r["computed_at"]
        assert client.get("/api/regime?code=EURUSD").status_code == 404
    finally:
        app.dependency_overrides.clear()
    assert export_static.targets()["/api/regime"] == "regime.json"


def test_volatility_is_measured_relative_to_the_price_level():
    """Gold rose by half in a year with the same daily range in % of the price: in dollars today's ATR would be the
    year's highest ("extreme"), relative to the price it is ordinary (found on the live copy 9. 11.: ATR 84.6 USD)."""
    days, d = [], dt.date(2026, 11, 6)
    while len(days) < 320:
        if d.weekday() < 5:
            days.append(d)
        d -= dt.timedelta(days=1)
    days.reverse()
    candles = []
    for i, day in enumerate(days):
        price = 3000 + 1500 * i / (len(days) - 1)
        r = price * 0.02 * (1 + 0.1 * math.sin(i / 5))
        candles.append(Candle(dt.datetime(day.year, day.month, day.day, tzinfo=UTC) - dt.timedelta(hours=2),
                              price, price + r / 2, price - r / 2, price))
    v = _dim(_compute(d1_candles=candles), "volatilita")
    assert v["state"] == "normal", v["detail"]
    assert "% ceny za posledních" in v["detail"]
