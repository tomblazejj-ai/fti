"""Market state for every calendar: trading day, weekend, holiday, trading break, stale data,
provider outage and the CET/CEST change (user's spec 2026-11-01)."""

import datetime as dt

import pytest

from app.data import bars, market_hours as mh, quality, universe

UTC = dt.timezone.utc


def at(y, m, d, hh, mm, tz=UTC):
    return dt.datetime(y, m, d, hh, mm, tzinfo=tz).astimezone(UTC)


def st(code, t, crypto="online"):
    return mh.state(universe.get(code), t, crypto_status_fn=lambda: crypto)["state"]


def test_holiday_rules():
    assert mh.easter(2026) == dt.date(2026, 4, 5) and mh.easter(2027) == dt.date(2027, 3, 28)
    h26 = mh.nyse_holidays(2026)
    assert {dt.date(2026, 1, 1), dt.date(2026, 4, 3), dt.date(2026, 7, 3), dt.date(2026, 11, 26), dt.date(2026, 12, 25)} <= h26
    assert dt.date(2026, 11, 27) in mh.nyse_early_closes(2026) and dt.date(2026, 12, 24) in mh.nyse_early_closes(2026)
    assert dt.date(2026, 12, 28) in mh.lse_holidays(2026)  # Boxing Day 26 Dec 2026 is a Saturday → Monday 28th
    assert dt.date(2026, 4, 6) in mh.xetra_holidays(2026)  # Easter Monday
    assert {dt.date(2026, 3, 20), dt.date(2026, 9, 22), dt.date(2026, 9, 23), dt.date(2026, 5, 6)} <= mh.tse_holidays(2026)


@pytest.mark.parametrize("code,t,expected", [
    # ordinary trading day, Wednesday 28 Oct 2026
    ("EURUSD", at(2026, 10, 28, 14, 0), mh.OPEN),
    ("XAUUSD", at(2026, 10, 28, 14, 0), mh.OPEN),
    ("US500", at(2026, 10, 28, 14, 0), mh.OPEN),  # 10:00 New York
    ("US500", at(2026, 10, 28, 12, 0), mh.PRE),  # 08:00 New York
    ("US500", at(2026, 10, 28, 21, 30), mh.POST),  # 17:30 New York
    ("US500.CFD", at(2026, 10, 28, 21, 30), mh.BREAK),  # 17:30 New York: Globex daily break
    ("XAUUSD", at(2026, 10, 28, 21, 30), mh.BREAK),
    ("JP225", at(2026, 10, 28, 3, 0), mh.BREAK),  # 12:00 Tokyo lunch break
    ("JP225", at(2026, 10, 28, 1, 0), mh.OPEN),  # 10:00 Tokyo
    ("GER40", at(2026, 10, 28, 10, 0), mh.OPEN),
    ("UK100", at(2026, 10, 28, 17, 0), mh.CLOSED),
    # weekend
    ("EURUSD", at(2026, 10, 31, 12, 0), mh.CLOSED),
    ("XAUUSD", at(2026, 11, 1, 8, 0), mh.CLOSED),
    ("US100", at(2026, 10, 31, 15, 0), mh.CLOSED),
    ("BTCUSD", at(2026, 10, 31, 12, 0), mh.OPEN),  # crypto trades on weekends
    # holidays
    ("US500", at(2026, 11, 26, 16, 0), mh.HOLIDAY),  # Thanksgiving
    ("XAUUSD", at(2026, 12, 25, 12, 0), mh.HOLIDAY),
    ("XAUUSD", at(2026, 4, 3, 12, 0), mh.HOLIDAY),  # Good Friday
    ("EURUSD", at(2027, 1, 1, 12, 0), mh.HOLIDAY),
    ("GER40", at(2026, 12, 24, 10, 0), mh.HOLIDAY),
])
def test_market_states(code, t, expected):
    assert st(code, t) == expected


def test_fx_opens_sunday_17_new_york_across_the_dst_change():
    # 1 Nov 2026: US summer time ended at 02:00 → New York is UTC-5, so 17:00 NY = 22:00 UTC (23:00 SEČ)
    assert st("EURUSD", at(2026, 11, 1, 21, 59)) == mh.CLOSED
    assert st("EURUSD", at(2026, 11, 1, 22, 0)) == mh.OPEN
    # in summer (UTC-4) the same moment is 21:00 UTC
    assert st("EURUSD", at(2026, 7, 5, 21, 0)) == mh.OPEN
    assert st("EURUSD", at(2026, 7, 5, 20, 59)) == mh.CLOSED
    # Prague label follows CET/CEST
    assert mh.prague(at(2026, 10, 24, 12, 0)).endswith("SELČ") and mh.prague(at(2026, 10, 26, 12, 0)).endswith("SEČ")


def test_crypto_exchange_maintenance_and_unknown_status():
    assert st("BTCUSD", at(2026, 10, 28, 12, 0), crypto="maintenance") == mh.BREAK
    assert st("BTCUSD", at(2026, 10, 28, 12, 0), crypto=None) == mh.UNKNOWN


def _h1(last_open: dt.datetime, n=120):
    t0 = int(last_open.timestamp()) - (n - 1) * 3600
    return [(t0 + i * 3600, 1.1, 1.101, 1.099, 1.1005, 10.0) for i in range(n)]


def test_open_market_without_new_quotes_is_stale_not_live(monkeypatch):
    now = at(2026, 10, 28, 14, 0)
    monkeypatch.setattr(bars, "_kraken", lambda symbol, tf, inst: (_h1(now - dt.timedelta(hours=6)), {"symbol": symbol}))
    bs = bars.get_bars("BTCUSD", "H1", now=now, store=False)
    monkeypatch.setattr(mh, "_kraken_status", lambda now, fn=None: "online")
    bs = bars.get_bars("BTCUSD", "H1", now=now, store=False)
    assert bs.market["state"] == mh.OPEN
    assert bs.quality["status"] == quality.STALE and not bs.last_quote["tradable_now"]
    assert "nepřináší nové kotace" in bs.quality["text"]


def test_closed_market_shows_the_last_real_quote_with_its_time(monkeypatch):
    now = at(2026, 11, 1, 8, 0)  # Sunday
    last_bar = at(2026, 10, 30, 20, 0)  # Friday 16:00 New York
    monkeypatch.setattr(bars, "_kraken", lambda symbol, tf, inst: (_h1(last_bar), {"symbol": symbol}))
    bs = bars.get_bars("EURUSD", "H1", now=now, store=False)
    assert bs.market["state"] == mh.CLOSED
    assert bs.quality["status"] == quality.PROXY  # Kraken's EUR/USD book is a labelled proxy …
    assert "poslední kotace pá 30. 10. 2026" in bs.quality["text"]  # … and the text says it is the last quote
    assert bs.last_quote["tradable_now"] is False and bs.last_quote["time"].startswith("2026-10-30T21:00")


def test_live_quote_on_an_open_market(monkeypatch):
    now = at(2026, 10, 28, 14, 10)
    monkeypatch.setattr(mh, "_kraken_status", lambda now, fn=None: "online")
    monkeypatch.setattr(bars, "_kraken", lambda symbol, tf, inst: (_h1(at(2026, 10, 28, 14, 0)), {"symbol": symbol}))
    bs = bars.get_bars("BTCUSD", "H1", now=now, store=False)
    assert bs.quality["status"] == quality.LIVE and bs.last_quote["tradable_now"] is True


def test_provider_outage_is_reported_not_filled(monkeypatch):
    def down(symbol, tf, inst):
        raise bars.FeedError("Kraken: timeout")

    monkeypatch.setattr(bars, "_kraken", down)
    bs = bars.get_bars("BTCUSD", "H1", now=at(2026, 10, 28, 14, 0), store=False)
    assert not bs.ok and bs.quality["status"] == quality.UNAVAILABLE
    assert any("timeout" in t["error"] for t in bs.tried)
