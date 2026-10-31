import datetime as dt
import math

import pytest

from app.market.correlations import DRIVERS, analyze_all, analyze_driver, pearson
from app.market.technical import InsufficientPriceHistory, analyze, rsi, sma
from app.verdict import build_verdict


def _dates(n: int) -> list[str]:
    start = dt.date(2025, 1, 1)
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(n)]


# ---------- technical ----------

def test_sma_and_rsi_basics():
    assert sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]
    assert rsi(list(range(1, 40))) == 100.0  # only gains
    falling = list(range(40, 1, -1))
    assert rsi(falling) < 1.0


def test_steady_uptrend_is_classified_as_rising():
    closes = [100 * (1.002 ** i) for i in range(300)]
    t = analyze(_dates(300), closes)
    assert t["trend"] == "up"
    assert t["trend_score"] >= 40
    assert t["rsi_state"] == "překoupeno"  # unbroken rise
    assert all(s["pct"] < 0 for s in t["supports"])
    assert t["changes"]["20d"] > 0


def test_steady_downtrend_is_classified_as_falling():
    closes = [100 * (0.998 ** i) for i in range(300)]
    t = analyze(_dates(300), closes)
    assert t["trend"] == "down"
    assert t["trend_score"] <= -40
    assert all(r["pct"] > 0 for r in t["resistances"])


def test_too_little_history_is_refused_not_guessed():
    with pytest.raises(InsufficientPriceHistory):
        analyze(_dates(50), [100.0] * 50)


def test_levels_are_percent_distances_from_last_close():
    closes = [100.0] * 250 + [110.0] * 20 + [105.0]
    t = analyze(_dates(len(closes)), closes)
    top = next(r for r in t["resistances"] if r["label"] == "Roční maximum")
    assert top["pct"] == pytest.approx((110 / 105 - 1) * 100, abs=0.01)


# ---------- correlations ----------

def _walk(n: int, seed: int) -> list[float]:
    vals, x = [], 100.0
    for i in range(n):
        x *= 1 + 0.01 * math.sin(i * 1.7 + seed) * math.cos(i * 0.3 + seed * 2)
        vals.append(x)
    return vals


def test_pearson_extremes():
    assert pearson([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [2, 4, 6, 8, 10, 12, 14, 16, 18, 20]) == pytest.approx(1.0)
    assert pearson([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]) == pytest.approx(-1.0)


def test_mirror_image_driver_is_strong_negative_and_its_rise_brakes_gold():
    dates = _dates(300)
    gold_vals = _walk(300, 1)
    usd_vals = [10000 / g for g in gold_vals]  # exact inverse moves
    usd_vals[-1] *= 1.0  # keep
    gold = dict(zip(dates, gold_vals))
    usd = dict(zip(dates, usd_vals))
    res = analyze_driver(DRIVERS[0], gold, usd)
    assert res["corr_now"] < -0.95
    assert res["strength"] == "silná"
    assert res["unusual"] is False  # gold–USD is normally negative
    expected_effect = -1 if res["move20"] > 0 else 1
    if abs(res["move20"]) >= 1.0:
        assert res["effect"] == expected_effect


def test_positive_correlation_with_usd_is_flagged_unusual():
    dates = _dates(300)
    gold_vals = _walk(300, 3)
    gold = dict(zip(dates, gold_vals))
    usd = dict(zip(dates, [g * 0.5 for g in gold_vals]))
    res = analyze_driver(DRIVERS[0], gold, usd)
    assert res["corr_now"] > 0.95 and res["unusual"] is True


def test_missing_driver_is_reported_unavailable():
    dates = _dates(300)
    gold = dict(zip(dates, _walk(300, 1)))
    res = analyze_all(gold, {})
    assert len(res) == len(DRIVERS)
    assert all(r["available"] is False for r in res)


# ---------- verdict ----------

FUND_BEARISH = {
    "score": 27.0, "bias": "SHORT",
    "pillar_breakdown": {
        "real_yields": {"points": -20.0, "data_quality": "ok"},
        "usd": {"points": -12.0, "data_quality": "ok"},
        "fed": {"points": -10.0, "data_quality": "ok"},
        "inflation": {"points": 0.0, "data_quality": "ok"},
        "economy": {"points": 0.0, "data_quality": "ok"},
        "geopolitics": {"points": 0.0, "data_quality": "partial"},
        "central_banks": {"points": 0.0, "data_quality": "partial"},
        "positioning": {"points": -1.0, "data_quality": "ok"},
    },
}


def _tech(score: float, rsi_state: str = "neutrální") -> dict:
    return {
        "trend_score": score, "trend_label": "Klesající trend" if score < 0 else "Rostoucí trend",
        "rsi14": 45.0, "rsi_state": rsi_state, "changes": {"20d": -4.0},
        "supports": [{"label": "Minimum za 60 dní", "pct": -3.0}],
        "resistances": [{"label": "50denní průměr", "pct": 2.5}, {"label": "200denní průměr", "pct": 6.0}],
        "sma50_pct": 2.5 if score < 0 else -2.5,
        "sma200_pct": 15.0 if score < 0 else -15.0,  # far away: not among the 3 nearest levels
    }


def test_fundament_and_trend_agreeing_bearish_gives_short_with_levels():
    v = build_verdict(FUND_BEARISH, _tech(-70), [], None, "2026-10-28")
    assert v["action"] == "short"
    assert v["direction_text"] == "ZLATO: DOLŮ" and v["action_text"] == "Swing: hledat prodej (short)."
    assert v["confidence"] in ("vysoká", "střední")
    assert v["resistance"]["label"] == "50denní průměr"
    assert any("FOMC" in r for r in v["risks"])
    assert any("nad 200denní průměr (+15,0 %)" in c for c in v["change_view"])  # even when not a "nearest" level
    assert any("50denním průměrem" in c for c in v["change_view"])
    assert [f["key"] for f in v["factors"]] == ["fundament", "technika"]  # no COT/news/markets given
    assert all(f["direction"] == "down" for f in v["factors"])
    assert v["summary"] == "2 z 2 faktorů ukazuje dolů, 0 nahoru."


def test_fundament_and_trend_disagreeing_says_wait():
    v = build_verdict(FUND_BEARISH, _tech(+70), None, None, None)
    assert v["action"] == "wait"
    assert "proti sobě" in v["headline"]


def test_neutral_everything_says_no_edge():
    fund = {**FUND_BEARISH, "score": 50.0}
    v = build_verdict(fund, _tech(0), None, None, None)
    assert v["action"] == "wait"
    assert v["direction_text"] == "ZLATO: BEZ JASNÉHO SMĚRU"


def test_oversold_short_waits_for_bounce_instead_of_selling_the_low():
    v = build_verdict(FUND_BEARISH, _tech(-70, rsi_state="přeprodáno"), None, None, None)
    assert v["action"] == "short"
    assert "přeprodaný" in v["timing"]


def test_missing_technicals_still_gives_fundamental_based_read_and_says_so():
    v = build_verdict(FUND_BEARISH, None, None, None, None)
    assert v["action"] == "short"
    assert "technika" not in v["components"]
    assert [f["key"] for f in v["factors"]] == ["fundament"]


def test_levels_at_the_same_price_are_merged_into_one_zone():
    from app.market.technical import _merge_close_levels
    merged = _merge_close_levels(
        [{"label": "Cenová zóna", "pct": -1.0, "touches": 1},
         {"label": "Roční minimum", "pct": -1.2, "touches": 1},
         {"label": "Cenová zóna", "pct": -1.3, "touches": 1},
         {"label": "Cenová zóna", "pct": -4.0, "touches": 1}],
        within_pct=0.6,
    )
    assert merged == [{"label": "Roční minimum", "pct": -1.0, "touches": 3}, {"label": "Cenová zóna", "pct": -4.0, "touches": 1}]


def test_technical_groups_have_signals_and_czech_sentences():
    closes = [100 * (0.998 ** i) for i in range(300)]
    t = analyze(_dates(300), closes)
    assert [g["key"] for g in t["groups"]] == ["trend", "momentum", "volatility"]
    for g in t["groups"]:
        for it in g["items"]:
            assert it["signal"] in (-1, 0, 1) and it["text"]
    assert t["tech_score"] < -30  # steady fall (RSI "přeprodáno" pulls it slightly back, as it should)
    assert t["trend_label"].startswith("Silný klesající")


def test_short_right_on_top_of_support_is_flagged_as_risky():
    tech = _tech(-70)
    tech["supports"] = [{"label": "Roční minimum", "pct": -0.9}]
    v = build_verdict(FUND_BEARISH, tech, None, None, None)
    assert v["action"] == "short"
    assert any("nad podporou" in r for r in v["risks"])


def test_correlation_reason_counts_brakes_and_helps():
    corr = [
        {"available": True, "label": "Americký dolar (index)", "corr_now": -0.5, "move20": 1.7, "unit": "%", "effect": -1, "unusual": False},
        {"available": True, "label": "Bitcoin", "corr_now": 0.45, "move20": 7.3, "unit": "%", "effect": 1, "unusual": False},
        {"available": True, "label": "Ropa WTI", "corr_now": 0.1, "move20": 11.0, "unit": "%", "effect": 0, "unusual": False},
    ]
    v = build_verdict(FUND_BEARISH, _tech(-70), corr, None, None)
    trhy = next(f for f in v["factors"] if f["key"] == "trhy")
    assert trhy["sentence"] == "Zlato brzdí: americký dolar; pomáhá: bitcoin."
    assert trhy["detail"] == "1 brzdí, 1 pomáhá"


def test_cot_and_news_enter_the_verdict_as_factors():
    cot = {"signal": -0.6, "cot_index_3y": 63.0, "extreme": "neutral",
           "texts": ["Pozice fondů mluví spíše pro pokles zlata.", "Fondy za poslední 4 týdny prodávají (−17 481 kontraktů)."]}
    news = {"score": -0.4, "count": 8, "hours": 72, "bullish": 2, "bearish": 6, "top": []}
    v = build_verdict(FUND_BEARISH, _tech(-70), None, None, None, cot=cot, news=news)
    keys = [f["key"] for f in v["factors"]]
    assert keys == ["fundament", "technika", "cot", "zpravy"]
    assert next(f for f in v["factors"] if f["key"] == "zpravy")["sentence"].startswith("Za poslední 3 dny 2 zpráv")
    assert v["action"] == "short" and v["confidence"] == "vysoká"


def test_too_few_news_are_not_a_factor():
    news = {"score": 0.9, "count": 2, "hours": 72, "bullish": 2, "bearish": 0, "top": []}
    v = build_verdict(FUND_BEARISH, _tech(-70), None, None, None, news=news)
    assert "zpravy" not in [f["key"] for f in v["factors"]]
