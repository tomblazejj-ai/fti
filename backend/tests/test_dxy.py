import datetime as dt

from app.connectors.kraken import Candle
from app.market import dxy

UTC = dt.timezone.utc
# ECB reference rates of 2026-10-02 (units per 1 EUR)
ECB_DAY = {"USD": 1.1225, "JPY": 176.99, "GBP": 0.85033, "CAD": 1.5984, "SEK": 11.29, "CHF": 0.9279}


def test_ice_formula_from_ecb_rates_matches_the_verified_value():
    q = dxy.ecb_usd_crosses(ECB_DAY)
    assert round(q["USDJPY"], 2) == 157.67
    value = dxy.dxy_value(q["EURUSD"], q["USDJPY"], q["GBPUSD"], q["USDCAD"], q["USDSEK"], q["USDCHF"])
    assert abs(value - 102.08) < 0.01


def test_jpy_sek_use_the_latest_fixing_on_or_before_the_day():
    fix = dxy._JpySek({"2026-10-01": {**ECB_DAY, "JPY": 170.0}, "2026-10-02": ECB_DAY})
    assert round(fix.at("2026-10-03")[0], 2) == 157.67  # weekend → Friday's fixing
    assert round(fix.at("2026-10-01")[0], 2) == round(170.0 / 1.1225, 2)


def _c(t, o, h, l, c):
    return Candle(t, o, h, l, c)


def test_combined_candle_high_is_the_dollar_strongest_point():
    t = dt.datetime(2026, 10, 2, 12, tzinfo=UTC)
    parts = {
        "EURUSD": [_c(t, 1.12, 1.13, 1.11, 1.12)],
        "GBPUSD": [_c(t, 1.32, 1.33, 1.31, 1.32)],
        "USDCAD": [_c(t, 1.42, 1.43, 1.41, 1.42)],
        "USDCHF": [_c(t, 0.83, 0.84, 0.82, 0.83)],
    }
    fix = dxy._JpySek({"2026-10-02": ECB_DAY})
    [k] = dxy.combine(parts, fix)
    assert k.low < k.open == k.close < k.high
    # dollar strongest = EUR and GBP at their (cleaned) lows, CAD and CHF at their (cleaned) highs
    q = dxy.ecb_usd_crosses(ECB_DAY)
    c = {p: dxy.clean_wicks(v)[0] for p, v in parts.items()}
    expected_high = dxy.dxy_value(c["EURUSD"].low, q["USDJPY"], c["GBPUSD"].low, c["USDCAD"].high, q["USDSEK"], c["USDCHF"].high)
    assert abs(k.high - expected_high) < 1e-9


def _series(prices, start=dt.datetime(2026, 1, 1, tzinfo=UTC)):
    return [_c(start + dt.timedelta(days=i), p, p, p, p) for i, p in enumerate(prices)]


def test_correlation_sees_gold_moving_against_the_dollar():
    import math
    dollar = [100 + math.sin(i / 3) for i in range(80)]
    gold = [4000 - 20 * math.sin(i / 3) for i in range(80)]
    corr, beta, n = dxy.correlation(_series(gold), _series(dollar), 60)
    assert corr is not None and corr < -0.9 and beta < 0 and n == 60


def test_stray_kraken_prints_do_not_become_dxy_wicks():
    t0 = dt.datetime(2026, 9, 23, tzinfo=UTC)
    bars = [_c(t0 + dt.timedelta(hours=4 * i), 1.3240, 1.3245, 1.3235, 1.3242) for i in range(20)]
    bars.append(_c(t0 + dt.timedelta(hours=80), 1.32416, 1.70, 1.32368, 1.32383))  # real Kraken GBP/USD print
    cleaned = dxy.clean_wicks(bars)
    assert cleaned[-1].high < 1.33 and cleaned[-1].open == 1.32416 and cleaned[-1].close == 1.32383
    assert cleaned[0].high <= 1.3245
