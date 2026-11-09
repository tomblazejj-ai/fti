"""MN1 (monthly candles) on the broker's grid: the month starts on the 1st 00:00 server time (New York + 7 h) =
17:00 New York on the last day of the previous month — the same rule as D1 and W1, through one bucket() function."""

import datetime as dt
from zoneinfo import ZoneInfo

from app.api.routes_dashboard import _day_labels
from app.connectors import dukascopy
from app.data.market_hours import trading_month_start, trading_week_start
from app.live.engine import aggregate
from app.live.instruments import DERIVED

NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc


def ts(y, m, d, h=0, mi=0, tz=UTC) -> int:
    return int(dt.datetime(y, m, d, h, mi, tzinfo=tz).timestamp())


def test_month_starts_17_new_york_on_the_last_day_before():
    # 2. 11. 2026 (Monday, after the US switch to winter time on 1. 11.) belongs to November,
    # whose candle starts on 31. 10. 17:00 New York (still summer time: 21:00 UTC)
    assert trading_month_start(ts(2026, 11, 2, 15)) == ts(2026, 10, 31, 17, tz=NY) == ts(2026, 10, 31, 21)
    # 1. 12. 2026 is a Tuesday: the December candle starts on Monday 30. 11. 17:00 New York (winter: 22:00 UTC)
    assert trading_month_start(ts(2026, 12, 1, 3)) == ts(2026, 11, 30, 22)
    # 30. 11. 2026 21:59 UTC = 16:59 New York is still November, 22:00 UTC already December
    assert trading_month_start(ts(2026, 11, 30, 21, 59)) == ts(2026, 10, 31, 21)
    assert trading_month_start(ts(2026, 11, 30, 22, 0)) == ts(2026, 11, 30, 22)


def test_month_whose_first_day_is_a_saturday_or_a_monday():
    # 1. 8. 2026 is a Saturday: Friday 31. 7. until 17:00 New York is July, the Sunday open (trading date Monday 3. 8.)
    # is August, whose candle starts on 31. 7. 17:00 New York
    assert trading_month_start(ts(2026, 7, 31, 20, 59)) == ts(2026, 6, 30, 17, tz=NY)
    assert trading_month_start(ts(2026, 8, 2, 22, 5)) == ts(2026, 7, 31, 17, tz=NY)
    # 1. 6. 2026 is a Monday: the Sunday 31. 5. evening session is already June
    assert trading_month_start(ts(2026, 5, 31, 22, 5)) == ts(2026, 5, 31, 17, tz=NY)


def test_one_bucket_function_for_month_and_week():
    for t in (ts(2026, 3, 9, 12), ts(2026, 11, 2, 15), ts(2026, 12, 31, 23)):
        assert dukascopy.bucket(t, dukascopy.MONTH) == trading_month_start(t)
        assert dukascopy.bucket(t, dukascopy.WEEK) == trading_week_start(t)
    # D1 and H4 unchanged
    t = ts(2026, 11, 9, 14)
    assert dukascopy.bucket(t, 86400) == ts(2026, 11, 8, 22)
    assert dukascopy.bucket(t, 14400) == ts(2026, 11, 9, 14)


def test_monthly_groups_trading_days_and_keeps_only_whole_months():
    days = []
    t = ts(2026, 9, 29, 21)  # trading days 30. 9. … 3. 11. 2026 (17:00 New York the evening before)
    while t < ts(2026, 11, 3, 23):
        d = dt.datetime.fromtimestamp(t, UTC).astimezone(NY)
        if (d + dt.timedelta(hours=7)).weekday() < 5:
            days.append((t, 100.0, 110.0, 90.0, 105.0))
        t = dukascopy.bucket(t + 30 * 3600, 86400)
    months = dukascopy.monthly(days)
    assert [m[0] for m in months] == [ts(2026, 8, 31, 17, tz=NY), ts(2026, 9, 30, 17, tz=NY), ts(2026, 10, 31, 17, tz=NY)]
    october = months[1]
    assert october[1:5] == (100.0, 110.0, 90.0, 105.0)
    assert dukascopy.month_span(october[0]) == ts(2026, 10, 31, 21) - ts(2026, 9, 30, 21)  # 31 days
    # the data begin on 30. 9.: September is cut and left out; October is whole; November is the newest, still filling
    covered = [(ts(2026, 9, 29, 21), ts(2026, 11, 3, 22))]
    kept = dukascopy.keep_whole(months, dukascopy.month_span, covered)
    assert [m[0] for m in kept] == [ts(2026, 9, 30, 17, tz=NY), ts(2026, 10, 31, 17, tz=NY)]


def test_live_engine_derives_w1_and_mn1_from_its_daily_candles():
    assert set(DERIVED) == {"W1", "MN1"}
    daily = [(ts(2026, 10, 29, 21), 1, 2, 0.5, 1.5), (ts(2026, 10, 30, 21), 1.5, 3, 1, 2), (ts(2026, 11, 1, 22), 2, 2.5, 1.8, 2.2)]
    months = aggregate(daily, DERIVED["MN1"])
    assert months == [(ts(2026, 9, 30, 21), 1, 3, 0.5, 2), (ts(2026, 10, 31, 21), 2, 2.5, 1.8, 2.2)]
    weeks = aggregate(daily, DERIVED["W1"])
    assert [w[0] for w in weeks] == [trading_week_start(daily[0][0]), trading_week_start(daily[2][0])]


def test_monthly_candles_are_named_by_their_first_day():
    rows = [[ts(2026, 10, 31, 21), 1, 1, 1, 1, None, None], [ts(2026, 11, 30, 22), 1, 1, 1, 1, None, None]]
    assert _day_labels(rows, "MN1") == ["2026-11-01", "2026-12-01"]
