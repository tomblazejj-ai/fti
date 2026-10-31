import datetime as dt

from app.scoring.base import bias_from_score, bullish_bearish_label, decay_factor, signed_total_to_score
from app.scoring.xauusd import (
    SUPPORTED_HORIZONS,
    MacroPoint,
    NewsDataPoint,
    NewsSignal,
    XauInputs,
    compute_xauusd_score,
)

NOW = dt.datetime(2026, 9, 27, 12, 0, tzinfo=dt.timezone.utc)


def _neutral_point() -> MacroPoint:
    return MacroPoint(actual=100.0, previous=100.0, period="2026-09-01")


def _all_neutral_inputs(**overrides) -> XauInputs:
    base = dict(
        real_yield_10y=_neutral_point(),
        usd_index=_neutral_point(),
        fed_funds_target=_neutral_point(),
        core_cpi=_neutral_point(),
        core_pce=_neutral_point(),
        gdp=_neutral_point(),
        unemployment=_neutral_point(),
        nfp=_neutral_point(),
    )
    base.update(overrides)
    return XauInputs(**base)


def test_all_neutral_inputs_yield_neutral_bias_on_every_horizon():
    for horizon in SUPPORTED_HORIZONS:
        result = compute_xauusd_score(_all_neutral_inputs(), horizon=horizon, now=NOW)
        assert result.bias == "NEUTRAL", horizon
        assert 45 <= result.score <= 55, horizon
        assert result.direction == "NEUTRAL"


def test_rejects_unsupported_horizon():
    try:
        compute_xauusd_score(_all_neutral_inputs(), horizon="1-year", now=NOW)
        assert False, "expected ValueError"
    except ValueError:
        pass


def _bull_inputs(**overrides) -> XauInputs:
    base = dict(
        real_yield_10y=MacroPoint(actual=1.6, previous=1.9, period="2026-09-26"),  # daily, no decay
        usd_index=MacroPoint(actual=99.0, previous=101.0, period="2026-09-26"),
        fed_funds_target=MacroPoint(actual=5.0, previous=5.25, period="2026-09-26"),
        core_cpi=MacroPoint(actual=3.0, previous=3.4, period="2026-09-10"),
        core_pce=MacroPoint(actual=2.8, previous=3.1, period="2026-09-10"),
        gdp=_neutral_point(),
        unemployment=_neutral_point(),
        nfp=_neutral_point(),
        fed_tone_news=NewsSignal(
            "fed_tone",
            [NewsDataPoint(sentiment=0.8, published_at=NOW - dt.timedelta(hours=6), item_id=1, description="dovish presser")],
        ),
    )
    base.update(overrides)
    return XauInputs(**base)


def test_bull_case_dovish_fed_falling_yields_cooling_inflation_gives_long_on_short_horizon():
    result = compute_xauusd_score(_bull_inputs(), horizon="1-10d", now=NOW)
    assert result.bias == "LONG"
    assert result.direction == "BULLISH"
    assert result.score > 65
    assert any(d.startswith(("Reálné výnosy", "Inflace", "Fed")) for d in result.drivers)


def _bear_inputs(**overrides) -> XauInputs:
    base = dict(
        real_yield_10y=MacroPoint(actual=2.2, previous=1.9, period="2026-09-26"),
        usd_index=MacroPoint(actual=103.0, previous=101.0, period="2026-09-26"),
        fed_funds_target=MacroPoint(actual=5.5, previous=5.25, period="2026-09-26"),
        core_cpi=MacroPoint(actual=3.8, previous=3.4, period="2026-09-10"),
        core_pce=MacroPoint(actual=3.5, previous=3.1, period="2026-09-10"),
        gdp=_neutral_point(),
        unemployment=_neutral_point(),
        nfp=_neutral_point(),
        fed_tone_news=NewsSignal(
            "fed_tone",
            [NewsDataPoint(sentiment=-0.8, published_at=NOW - dt.timedelta(hours=6), item_id=2, description="hawkish presser")],
        ),
    )
    base.update(overrides)
    return XauInputs(**base)


def test_bear_case_hawkish_fed_rising_yields_hot_inflation_gives_short():
    result = compute_xauusd_score(_bear_inputs(), horizon="1-10d", now=NOW)
    assert result.bias == "SHORT"
    assert result.direction == "BEARISH"
    assert result.score < 35


def test_missing_macro_data_is_reported_not_fabricated():
    inp = _all_neutral_inputs(real_yield_10y=MacroPoint(actual=None, previous=None))
    result = compute_xauusd_score(inp, horizon="1-10d", now=NOW)
    real_yield_pillar = next(p for p in result.pillars if p.name == "real_yields")
    assert real_yield_pillar.data_quality == "unavailable"
    assert real_yield_pillar.raw_signal == 0.0
    assert any("chybí data" in r for r in real_yield_pillar.reasons)


def test_every_pillar_has_source_and_impact_and_quality():
    result = compute_xauusd_score(_bull_inputs(), horizon="1-10d", now=NOW)
    for p in result.pillars:
        assert p.source, f"pillar {p.name} has no source"
        assert p.impact in ("bullish", "bearish", "neutral")
        assert p.data_quality in ("ok", "partial", "unavailable")
        assert p.reasons, f"pillar {p.name} has no explanation"


def test_positioning_pillar_unwired_is_neutral_and_flagged_as_risk():
    inp = _all_neutral_inputs(positioning=None)
    result = compute_xauusd_score(inp, horizon="1-10d", now=NOW)
    positioning_pillar = next(p for p in result.pillars if p.name == "positioning")
    assert positioning_pillar.data_quality == "unavailable"
    assert any("COT" in r for r in result.risks)


def test_positioning_wired_with_real_data_is_ok_quality_and_scores():
    inp = _all_neutral_inputs(positioning=MacroPoint(actual=230000.0, previous=200000.0, period="2026-09-22"))
    result = compute_xauusd_score(inp, horizon="1-10d", now=NOW)
    positioning_pillar = next(p for p in result.pillars if p.name == "positioning")
    assert positioning_pillar.data_quality == "ok"
    assert positioning_pillar.raw_signal > 0
    assert not any("COT" in r for r in result.risks)


def test_stale_monthly_data_decays_more_on_intraday_than_on_long_horizon():
    """A CPI print from ~50 days ago should barely move the intraday score
    but should still count meaningfully on the 1-3m view — that is the
    entire point of horizon-specific decay (see xauusd.py module docstring).
    """
    old_period = (NOW.date() - dt.timedelta(days=50)).isoformat()
    inp = _all_neutral_inputs(
        core_cpi=MacroPoint(actual=2.0, previous=3.4, period=old_period),  # sharp cooling, but old news
        core_pce=MacroPoint(actual=2.0, previous=3.1, period=old_period),
    )
    intraday = compute_xauusd_score(inp, horizon="intraday", now=NOW)
    long_view = compute_xauusd_score(inp, horizon="1-3m", now=NOW)

    intraday_inflation = next(p for p in intraday.pillars if p.name == "inflation")
    long_inflation = next(p for p in long_view.pillars if p.name == "inflation")

    assert abs(intraday_inflation.raw_signal) < abs(long_inflation.raw_signal)


def test_horizons_are_not_just_copies_of_each_other():
    inp = _bull_inputs()
    scores = {h: compute_xauusd_score(inp, horizon=h, now=NOW).score for h in SUPPORTED_HORIZONS}
    assert len(set(scores.values())) > 1, f"all horizons produced the same score: {scores}"


def test_fresh_news_matters_more_intraday_than_stale_news_on_1_3m_relatively():
    fresh_bullish = NewsSignal(
        "geopolitics", [NewsDataPoint(sentiment=1.0, published_at=NOW - dt.timedelta(hours=2), item_id=10, description="war escalates")]
    )
    inp = _all_neutral_inputs(geopolitics_news=fresh_bullish)
    intraday = compute_xauusd_score(inp, horizon="intraday", now=NOW)
    geo_intraday = next(p for p in intraday.pillars if p.name == "geopolitics")
    assert geo_intraday.raw_signal > 0.9  # near-full weight, essentially no age yet


def test_scenarios_are_present_with_supports_would_change_and_risks():
    result = compute_xauusd_score(_bull_inputs(), horizon="1-10d", now=NOW)
    for key in ("base", "bull", "bear"):
        scenario = result.scenarios[key]
        assert scenario.narrative
        assert scenario.supports
        assert scenario.would_change or key == "base"  # base may have empty depending on data, others always populated by construction
        assert scenario.key_risks


def test_invalidation_never_asks_a_pillar_to_flip_into_its_own_current_state():
    """Regression test for a live-smoke-test bug: scenario bucketing used a
    different threshold (0.15) than PillarResult.impact (0.1), so a mildly
    bearish pillar could land in the "neutral" bucket and produce the
    nonsensical instruction "flip from bearish to bearish".
    """
    inp = _all_neutral_inputs(positioning=MacroPoint(actual=193000.0, previous=200000.0, period="2026-09-22"))
    for horizon in SUPPORTED_HORIZONS:
        result = compute_xauusd_score(inp, horizon=horizon, now=NOW)
        for item in result.invalidation:
            for gen, acc in (("býčího", "býčí"), ("medvědího", "medvědí"), ("neutrálního", "neutrální")):
                assert f"z {gen} na {acc}" not in item, item


def test_invalidation_lists_concrete_conditions_and_next_fomc_date():
    result = compute_xauusd_score(_bull_inputs(), horizon="1-10d", now=NOW)
    assert result.invalidation
    assert any("FOMC" in item for item in result.invalidation)


def test_decay_factor_never_drops_below_floor_and_equals_one_at_zero_age():
    assert decay_factor(0, 5, floor=0.3) == 1.0
    assert decay_factor(10_000, 5, floor=0.3) >= 0.3
    assert decay_factor(10_000, 5, floor=0.3) < 0.31


def test_bullish_bearish_label_mapping():
    assert bullish_bearish_label("LONG") == "BULLISH"
    assert bullish_bearish_label("SHORT") == "BEARISH"
    assert bullish_bearish_label("NEUTRAL") == "NEUTRAL"


def test_signed_total_to_score_midpoint_and_bounds():
    assert signed_total_to_score(0.0) == 50.0
    assert signed_total_to_score(100.0) == 100.0
    assert signed_total_to_score(-100.0) == 0.0
    assert signed_total_to_score(200.0) == 100.0  # clamped, never overshoots


def test_bias_from_score_thresholds():
    assert bias_from_score(65.0) == "LONG"
    assert bias_from_score(64.9) == "NEUTRAL"
    assert bias_from_score(35.0) == "SHORT"
    assert bias_from_score(35.1) == "NEUTRAL"


def test_partial_pillar_that_moved_the_score_is_evidence_and_risk_names_only_the_gap():
    """Live-data regression: Fed had a real rate change (FRED) but no tone
    news. Its −6 pts counted in the score, yet it was reported as "not
    assessed" and the rate reading itself was listed as a data-gap risk.
    """
    inp = _all_neutral_inputs(fed_funds_target=MacroPoint(actual=4.0, previous=3.75, period="2026-09-27", previous_period="2026-06-29"))
    result = compute_xauusd_score(inp, horizon="1-10d", now=NOW)
    fed = next(p for p in result.pillars if p.name == "fed")
    assert fed.data_quality == "partial"
    assert fed.points < 0 and fed.has_evidence
    assert any("Fed" in s for s in result.scenarios["bear"].supports) or any("DFEDTARU" in s for s in result.scenarios["bear"].supports)
    assert not any("DFEDTARU" in r for r in result.risks)
    assert any("Fed tón" in r for r in result.risks)
    assert result.pillar_breakdown_json()["fed"]["gaps"] == [fed.gaps[0]]


def test_tiny_change_is_worded_as_practically_unchanged():
    from app.scoring.base import trend_signal
    _, reason, _ = trend_signal(3.3441, 3.3436, higher_is_bullish=False, reason_label="Core PCE", scale=0.2, mode="absolute")
    assert "prakticky beze změny" in reason
