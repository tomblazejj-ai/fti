"""Gold's daily history without MT5 (Ú1, 8.–9. 11. 2026): the daily candles of Dukascopy were built from 200 days of
minute files — about 140 trading days with a one-hour Sunday stub each week, so the daily technique (SMA200 needs 210)
never ran without the broker. Now the older history comes from the monthly hour files (one request a month, cached for
good) and the candles lie on the broker's grid: a day runs 17:00 → 17:00 New York, H4 lies inside it, a week starts
Saturday 17:00 New York — in summer and winter time and under the US rules before and after 2007."""

import datetime as dt
import lzma
import struct

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.connectors import dukascopy
from app.data import bars, market_hours, migrations, store
from app.db import Base
from app.market import technical
from app.models import MarketBar

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 8, 12, 0, tzinfo=UTC)  # Sunday noon: the market is closed
REAL_BARS = dukascopy.bars
REAL_SAVE = store.save_bars


def utc(*a) -> int:
    return int(dt.datetime(*a, tzinfo=UTC).timestamp())


def _open(t: dt.datetime) -> bool:
    """Simplified gold week in UTC: Sunday 22:00 → Friday 21:00 (enough for the test, the real calendar is not needed)."""
    wd, h = t.weekday(), t.hour
    return wd < 4 or (wd == 4 and h < 21) or (wd == 6 and h >= 22)


def _price(t: dt.datetime) -> float:
    return 4000.0 + t.timetuple().tm_yday + t.hour / 100


def _rec(offset: int, p: float) -> bytes:
    return struct.pack(">5i1f", offset, int(round(p * 1000)), int(round((p + 0.05) * 1000)), int(round((p - 0.5) * 1000)),
                       int(round((p + 0.5) * 1000)), 1.0)


def _month_file(year: int, month: int) -> bytes:
    start = dt.datetime(year, month, 1, tzinfo=UTC)
    end = dt.datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=UTC)
    recs, t = [], start
    while t < end:
        if _open(t):
            recs.append(_rec(int((t - start).total_seconds()), _price(t)))
        t += dt.timedelta(hours=1)
    return lzma.compress(b"".join(recs), format=lzma.FORMAT_ALONE)


def _minute_file(day: dt.date) -> bytes:
    """Every 30 minutes; both records of an hour carry the hour's price, so a day from minute files equals the same
    day from the month file — the two sources can be compared exactly."""
    recs = []
    for m in range(0, 1440, 30):
        t = dt.datetime(day.year, day.month, day.day, tzinfo=UTC) + dt.timedelta(minutes=m)
        if _open(t):
            recs.append(_rec(m * 60, _price(t)))
    return lzma.compress(b"".join(recs), format=lzma.FORMAT_ALONE)


@pytest.fixture()
def feed(monkeypatch, tmp_path):
    monkeypatch.setattr(dukascopy, "bars", REAL_BARS)  # conftest replaces it for all other tests
    monkeypatch.setattr(dukascopy, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(dukascopy, "MIN_INTERVAL", 0.0)
    dukascopy.reset()
    bars.clear_cache()
    state = {"seen": [], "absent": set()}

    def handler(request):
        path = request.url.path
        state["seen"].append(path)
        parts = path.split("/")  # /datafeed/XAUUSD/2026/09/BID_candles_hour_1.bi5 (month 0-based)
        if any(a in path for a in state["absent"]):
            return httpx.Response(404)
        if path.endswith("BID_candles_hour_1.bi5"):
            return httpx.Response(200, content=_month_file(int(parts[3]), int(parts[4]) + 1))
        if path.endswith("BID_candles_min_1.bi5"):
            return httpx.Response(200, content=_minute_file(dt.date(int(parts[3]), int(parts[4]) + 1, int(parts[5]))))
        return httpx.Response(404)

    monkeypatch.setattr(dukascopy, "_transport", httpx.MockTransport(handler))
    return state


def _days(d1):
    return [market_hours.trading_date(b[0]) for b in d1]


# --- the trading day ----------------------------------------------------------------------------------------------

def test_trading_day_follows_new_york_close_in_summer_and_winter_time():
    # summer time (EDT, UTC-4): Friday's day runs Thursday 21:00 → Friday 21:00 UTC
    assert market_hours.trading_date(utc(2026, 10, 30, 20, 59)) == dt.date(2026, 10, 30)
    assert market_hours.trading_day_start(utc(2026, 10, 30, 12)) == utc(2026, 10, 29, 21)
    # winter time (EST, UTC-5) from Sunday 1. 11.: the Sunday evening open belongs to Monday, 22:00 UTC
    assert market_hours.trading_date(utc(2026, 11, 1, 22, 30)) == dt.date(2026, 11, 2)
    assert market_hours.trading_day_start(utc(2026, 11, 2, 15)) == utc(2026, 11, 1, 22)
    # spring 2026 (second Sunday of March, 8. 3.): Friday still EST, Monday already EDT
    assert market_hours.trading_day_start(utc(2026, 3, 6, 12)) == utc(2026, 3, 5, 22)
    assert market_hours.trading_day_start(utc(2026, 3, 9, 12)) == utc(2026, 3, 8, 21)
    # a daily bar of a 00:00 UTC source (ECB, FRED) keeps its own date
    assert market_hours.trading_date(utc(2026, 11, 5)) == dt.date(2026, 11, 5)
    # the week starts Saturday 17:00 New York (Sunday 00:00 broker time), like the broker's weekly candle
    assert market_hours.trading_week_start(utc(2026, 11, 4, 12)) == utc(2026, 10, 31, 21)
    assert market_hours.trading_week_start(utc(2026, 3, 11, 12)) == utc(2026, 3, 7, 22)  # Saturday before the switch: EST
    # the weekend itself: the week turns at Saturday 17:00 New York (not at Monday), Friday evening is still the old week
    assert market_hours.trading_week_start(utc(2026, 10, 31, 21)) == utc(2026, 10, 31, 21)
    assert market_hours.trading_week_start(utc(2026, 11, 1, 12)) == utc(2026, 10, 31, 21)
    assert market_hours.trading_week_start(utc(2026, 10, 31, 20, 59)) == utc(2026, 10, 24, 21)
    assert market_hours.trading_week_start(utc(2026, 10, 30, 22)) == utc(2026, 10, 24, 21)


def test_trading_day_uses_the_us_rules_valid_at_the_time():
    # until 2006 summer time ended on the last Sunday of October and began on the first Sunday of April
    assert market_hours.trading_day_start(utc(2006, 10, 27, 12)) == utc(2006, 10, 26, 21)  # EDT
    assert market_hours.trading_day_start(utc(2006, 10, 30, 12)) == utc(2006, 10, 29, 22)  # EST (new rules: still EDT)
    assert market_hours.trading_day_start(utc(2006, 3, 13, 12)) == utc(2006, 3, 12, 22)    # EST (new rules: EDT)
    assert market_hours.trading_day_start(utc(2006, 4, 3, 12)) == utc(2006, 4, 2, 21)      # EDT from 2. 4. 2006
    # from 2007: first Sunday of November / second Sunday of March
    assert market_hours.trading_day_start(utc(2007, 10, 29, 12)) == utc(2007, 10, 28, 21)  # still EDT
    assert market_hours.trading_day_start(utc(2007, 11, 5, 12)) == utc(2007, 11, 4, 22)


def test_h4_lies_inside_the_trading_day_in_both_seasons():
    for day_start in (utc(2026, 10, 29, 21), utc(2026, 11, 2, 22), utc(2026, 3, 5, 22), utc(2026, 3, 8, 21)):
        h4 = sorted({dukascopy.bucket(day_start + s, 14400) for s in range(0, 86400, 900)})
        assert h4 == [day_start + i * 14400 for i in range(6)]  # 17, 21, 01, 05, 09, 13 h New York
        assert dukascopy.bucket(day_start + 86400, 14400) == day_start + 86400  # the next day starts a new H4
    assert dukascopy.bucket(utc(2026, 11, 3, 10, 37), 3600) == utc(2026, 11, 3, 10)  # hour and less: plain UTC grid


def test_month_file_is_asked_only_once_it_is_surely_published():
    assert dukascopy.file_months(dt.datetime(2026, 11, 2, 12, tzinfo=UTC), 2) == [(2026, 9), (2026, 8)]
    assert dukascopy.file_months(dt.datetime(2026, 11, 4, 0, tzinfo=UTC), 1) == [(2026, 10)]
    assert dukascopy.file_months(dt.datetime(2026, 1, 10, tzinfo=UTC), 2) == [(2025, 12), (2025, 11)]


# --- daily history from the month files ----------------------------------------------------------------------------

def test_daily_history_from_month_files_five_candles_a_week(feed):
    d1, meta = dukascopy.bars("XAUUSD", 86400, 200, now=NOW, budget=[100], months=15)
    assert len(d1) >= 210  # SMA200 with its slope — impossible with 200 days of minute files
    assert meta["missing_files"] == 0
    days = _days(d1)
    assert len(days) == len(set(days))  # one candle per trading day
    assert all(d.weekday() < 5 for d in days)  # no Saturday or Sunday candle
    assert all(b[0] == market_hours.trading_day_start(b[0]) for b in d1)
    per_week: dict = {}
    for d in days:
        per_week[d.isocalendar()[:2]] = per_week.get(d.isocalendar()[:2], 0) + 1
    whole = [n for wk, n in per_week.items() if wk not in (min(per_week), max(per_week))]
    assert whole and all(n == 5 for n in whole)  # every week inside the window has exactly five (no holidays in the mock)
    # both daylight-saving switches inside the data: the candle starts at 17:00 New York on either side
    by_day = {d: b for d, b in zip(days, d1)}
    assert by_day[dt.date(2026, 10, 30)][0] == utc(2026, 10, 29, 21) and by_day[dt.date(2026, 11, 2)][0] == utc(2026, 11, 1, 22)
    assert by_day[dt.date(2026, 3, 6)][0] == utc(2026, 3, 5, 22) and by_day[dt.date(2026, 3, 9)][0] == utc(2026, 3, 8, 21)
    # Monday opens with Sunday evening's first hour; Friday closes with its last hour before the weekend
    assert by_day[dt.date(2026, 11, 2)][1] == pytest.approx(_price(dt.datetime(2026, 11, 1, 22, tzinfo=UTC)))
    assert by_day[dt.date(2026, 10, 30)][4] == pytest.approx(_price(dt.datetime(2026, 10, 30, 20, tzinfo=UTC)) + 0.05)
    # minute files only after the newest month file (October), month files for the 15 finished months, no tick files
    # on a Sunday morning (the market is closed — nothing to ask)
    minute_days = [p for p in feed["seen"] if p.endswith("BID_candles_min_1.bi5")]
    assert minute_days and all("/2026/10/" in p for p in minute_days)  # 0-based: 10 = November
    assert len([p for p in feed["seen"] if p.endswith("BID_candles_hour_1.bi5")]) == 15
    assert not [p for p in feed["seen"] if p.endswith("h_ticks.bi5")]
    # a second call reads everything from the disk cache and gives exactly the same candles
    before = len(feed["seen"])
    again, _ = dukascopy.bars("XAUUSD", 86400, 200, now=NOW, budget=[100], months=15)
    assert again == d1 and len(feed["seen"]) == before


def test_month_files_and_minute_files_give_the_same_days(feed):
    from_months, _ = dukascopy.bars("XAUUSD", 86400, 200, now=NOW, budget=[200], months=15)
    from_minutes, _ = dukascopy.bars("XAUUSD", 86400, 45, now=NOW, budget=[200], months=0)
    m = {b[0]: b for b in from_months}
    common = [b for b in from_minutes if b[0] in m]
    assert len(common) >= 25  # all of October and November so far
    assert all(b[1:5] == pytest.approx(m[b[0]][1:5]) for b in common)


def test_a_month_without_file_is_left_out_never_stitched(feed):
    feed["absent"].add("/2026/05/BID_candles_hour_1.bi5")  # June 2026 (0-based month)
    d1, meta = dukascopy.bars("XAUUSD", 86400, 200, now=NOW, budget=[100], months=15)
    days = _days(d1)
    assert meta["missing_files"] == 1
    assert not [d for d in days if (d.year, d.month) == (2026, 6)]
    # a trading day starts at 17:00 New York the evening before: 1. 6. starts on 31. 5. 21:00 UTC but ends in June, and
    # 1. 7. starts on 30. 6. 21:00 UTC — both are cut by the missing file and left out; the days around them stay
    assert dt.date(2026, 5, 29) in days and dt.date(2026, 6, 1) not in days
    assert dt.date(2026, 7, 1) not in days and dt.date(2026, 7, 2) in days
    w1 = dukascopy.keep_whole(dukascopy.weekly(d1), 7 * 86400, meta["covered"])
    assert not [w for w in w1 if utc(2026, 5, 30) <= w[0] < utc(2026, 7, 4)]  # no week stitched over the hole


def test_nested_timeframes_agree(feed):
    """H1 and H4 inside each trading day of the minute files rebuild the day's candle exactly; D1 rebuild W1."""
    d1, _ = dukascopy.bars("XAUUSD", 86400, 200, now=NOW, budget=[100], months=15)
    h1, _ = dukascopy.bars("XAUUSD", 3600, 7, now=NOW, budget=[100])
    h4, _ = dukascopy.bars("XAUUSD", 14400, 7, now=NOW, budget=[100])

    def rebuild(parts):
        return (parts[0][1], max(p[2] for p in parts), min(p[3] for p in parts), parts[-1][4])

    checked = 0
    for day in d1:
        for finer in (h1, h4):
            inside = [b for b in finer if day[0] <= b[0] < day[0] + 86400]
            if day[0] >= h1[0][0] and inside:
                assert all(b[0] + (3600 if finer is h1 else 14400) <= day[0] + 86400 for b in inside)  # none crosses the day end
                assert rebuild(inside) == pytest.approx(day[1:5])
                checked += 1
    assert checked >= 8  # Monday–Friday of the last week, H1 and H4
    for week in dukascopy.weekly(d1):
        inside = [b for b in d1 if week[0] <= b[0] < week[0] + 7 * 86400]
        assert rebuild(inside) == pytest.approx(week[1:5])


# --- the feed used by FTI: limited downloads per call, repeated loading, storage ------------------------------------

def test_daily_history_fills_up_over_a_few_cycles_and_then_serves_the_technique(feed):
    """One call may download only NEW_FILES_PER_CALL files: the history grows newest first, every intermediate state
    holds only whole days, and after a few cycles the daily technique runs without MT5 (MT5 and OANDA are off in tests)."""
    lengths = []
    for _ in range(8):
        bars.clear_cache()
        bs = bars.get_bars("XAUUSD", "D1", now=NOW, store=False)
        if not bs.bars:
            lengths.append(0)
            continue
        assert bs.provider == "dukascopy"
        days = _days(bs.bars)
        assert len(days) == len(set(days)) and all(d.weekday() < 5 for d in days)
        lengths.append(len(bs.bars))
    assert lengths == sorted(lengths) and lengths[-1] >= technical.MIN_HISTORY
    assert lengths.index(lengths[-1]) <= 6  # 6 minute files + 15 month files at 4 a call = 6 calls
    w1 = bars.get_bars("XAUUSD", "W1", now=NOW, store=False)
    assert w1.provider == "dukascopy" and len(w1.bars) >= 60
    candles = bars.to_candles(bs)
    result = technical.analyze([market_hours.trading_date(c.time).isoformat() for c in candles], [c.close for c in candles],
                               unit="USD")
    assert result["as_of"] == "2026-11-06" and result["trend"]  # Friday's trading day, the daily trend is computed


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(store, "SessionLocal", Session)
    monkeypatch.setattr(store, "save_bars", REAL_SAVE)  # conftest stubs it out for all other tests
    monkeypatch.setattr(bars, "DUKASCOPY_DAYS", {**bars.DUKASCOPY_DAYS, "H4": 7, "H1": 3, "M15": 2, "M5": 2, "M1": 2})
    return Session


def _stored(Session, tf):
    with Session() as s:
        return [(r.t, r.o, r.h, r.l, r.c, r.closed) for r in
                s.query(MarketBar).filter_by(code="XAUUSD", provider="dukascopy", tf=tf).order_by(MarketBar.t)]


def test_repeated_collection_stores_each_candle_once_and_no_candle_for_a_missing_month(feed, db):
    feed["absent"].add("/2026/05/BID_candles_hour_1.bi5")  # June 2026 has no file
    for _ in range(12):
        bars.collect_history(now=NOW)
    d1, w1, h4 = _stored(db, "D1"), _stored(db, "W1"), _stored(db, "H4")
    assert len(d1) >= 200 and w1 and h4
    days = _days(d1)
    assert len(days) == len(set(days)) and all(d.weekday() < 5 for d in days)  # one row per trading day, no weekend row
    assert not [d for d in days if (d.year, d.month) == (2026, 6)]  # nothing invented for the missing month
    assert all(t == market_hours.trading_day_start(t) for t, *_ in d1)
    assert all(t == market_hours.trading_week_start(t) for t, *_ in w1)
    assert all((t - market_hours.trading_day_start(t)) % 14400 == 0 for t, *_ in h4)
    assert all(r[5] for r in d1)  # Sunday noon: every trading day is over, all are closed
    for _ in range(3):  # loading again changes nothing
        bars.collect_history(now=NOW)
    assert _stored(db, "D1") == d1 and _stored(db, "W1") == w1 and _stored(db, "H4") == h4


def test_migration_moves_old_utc_grid_candles_aside_without_changing_prices():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    old_d1, new_d1 = utc(2026, 11, 3), utc(2026, 11, 2, 22)
    old_h4, new_h4 = utc(2026, 11, 3, 4), utc(2026, 11, 3, 2)
    rows_in = (("D1", old_d1), ("W1", utc(2026, 11, 2)), ("D1", new_d1), ("H4", old_h4), ("H4", new_h4), ("H1", old_d1))
    with engine.begin() as c:
        for tf, t in rows_in:
            c.execute(text("INSERT INTO market_bars (code, provider, feed_symbol, tf, t, o, h, l, c, closed, received_at, origin) "
                           "VALUES ('XAUUSD', 'dukascopy', 'XAUUSD', :tf, :t, 4000, 4010, 3990, 4005, 1, '2026-11-03', 'x')"),
                      {"tf": tf, "t": t})
    assert "2026-11-09_dukascopy_ny_close_grid" in migrations.apply_all(engine)
    assert migrations.apply_all(engine) == []  # recorded: runs exactly once
    with engine.connect() as c:
        rows = c.execute(text("SELECT provider, tf, t, o, h, l, c FROM market_bars ORDER BY provider, tf, t")).all()
        detail = c.execute(text("SELECT details FROM schema_migrations WHERE name = '2026-11-09_dukascopy_ny_close_grid'")).scalar()
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("dukascopy", "D1", new_d1), ("dukascopy", "H1", old_d1), ("dukascopy", "H4", new_h4),
        ("dukascopy-utc", "D1", old_d1), ("dukascopy-utc", "H4", old_h4), ("dukascopy-utc", "W1", utc(2026, 11, 2))]
    assert {tuple(r[3:]) for r in rows} == {(4000, 4010, 3990, 4005)}  # no price changed, nothing deleted
    assert '"D1": 1' in detail and '"H4": 1' in detail and '"W1": 1' in detail


def test_chart_names_each_daily_and_weekly_candle_by_its_trading_day():
    """The chart showed the local date of a candle's start: Monday's candle (Sunday 22:00 UTC) appeared as Sunday."""
    from app.api.routes_dashboard import _day_labels

    rows = [[utc(2026, 11, 1, 22)], [utc(2026, 10, 29, 21)], [utc(2026, 11, 5)]]  # broker Monday, broker Friday, ECB day
    assert _day_labels(rows, "D1") == ["2026-11-02", "2026-10-30", "2026-11-05"]
    weeks = [[utc(2026, 10, 31, 21)], [utc(2026, 11, 2)]]  # broker week (Saturday 17:00 New York), a Monday-UTC week
    assert _day_labels(weeks, "W1") == ["2026-11-02", "2026-11-02"]
    assert _day_labels(rows, "H1") is None
