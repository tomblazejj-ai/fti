import pytest

from app.ingestion.transforms import InsufficientHistoryError, SeriesSpec, derive


def _monthly(values, start_year=2025, start_month=1):
    out = []
    for i, v in enumerate(values):
        total = start_year * 12 + (start_month - 1) + i
        out.append({"date": f"{total // 12:04d}-{total % 12 + 1:02d}-01", "value": v})
    return out


def test_yoy_uses_same_month_a_year_earlier_not_the_raw_level():
    # index rises every month (as CPI does), but YoY inflation DECELERATES
    values = [100.0] * 12 + [103.0, 102.9]  # Jan25..Dec25 = 100, Jan26 = 103 (3.0% YoY), Feb26 = 102.9 (2.9%)
    point = derive(_monthly(values), SeriesSpec("core_cpi", "CPILFESL", "M", "yoy", "% YoY"))
    assert point.actual == pytest.approx(2.9)
    assert point.previous == pytest.approx(3.0)
    assert point.period == "2026-02-01" and point.previous_period == "2026-01-01"


def test_yoy_without_a_year_of_history_is_insufficient_not_guessed():
    with pytest.raises(InsufficientHistoryError):
        derive(_monthly([100.0, 101.0, 102.0]), SeriesSpec("core_cpi", "CPILFESL", "M", "yoy", "% YoY"))


def test_mom_diff_turns_employment_level_into_monthly_change():
    point = derive(_monthly([159_000.0, 159_150.0, 159_200.0]), SeriesSpec("nfp", "PAYEMS", "M", "mom_diff", "k"))
    assert point.actual == pytest.approx(50.0)
    assert point.previous == pytest.approx(150.0)


def test_qoq_annualized_growth():
    point = derive(_monthly([100.0, 101.0, 101.5], start_month=1), SeriesSpec("gdp", "GDPC1", "Q", "qoq_ann", "%"))
    assert point.previous == pytest.approx((1.01 ** 4 - 1) * 100)
    assert point.actual == pytest.approx(((101.5 / 101.0) ** 4 - 1) * 100)


def test_level_lookback_compares_with_n_observations_earlier():
    obs = [{"date": f"2026-09-{d:02d}", "value": float(d)} for d in range(1, 26)]
    point = derive(obs, SeriesSpec("real_yield_10y", "DFII10", "D", "level", "%", lookback=20))
    assert point.actual == 25.0 and point.previous == 5.0
    assert point.previous_period == "2026-09-05"


def test_level_lookback_with_too_little_history_is_insufficient():
    obs = [{"date": "2026-09-01", "value": 1.0}, {"date": "2026-09-02", "value": 2.0}]
    with pytest.raises(InsufficientHistoryError):
        derive(obs, SeriesSpec("real_yield_10y", "DFII10", "D", "level", "%", lookback=20))
