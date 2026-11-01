"""Price truth across FTI (user's spec 2026-11-01): one value, source and quote time everywhere;
proxy never shown as the instrument; a fixing never shown as a live quote; stale data never
current; a closed market recognised; the real time of the last trade used, not the API's bar."""

import datetime as dt

from fastapi.testclient import TestClient

from app.data import bars, market_hours, prices, quality

UTC = dt.timezone.utc


def _hourly(last_open: dt.datetime, price=1.10, n=120, vol=50.0):
    t0 = int(last_open.timestamp()) - (n - 1) * 3600
    return [(t0 + i * 3600, price, price + 0.001, price - 0.001, price, vol) for i in range(n)]


def _ecb(day: str, usd: float, jpy: float):
    return {day: {"USD": usd, "JPY": jpy, "GBP": 0.83, "CAD": 1.56, "SEK": 10.9, "CHF": 0.92}}


def test_ticker_and_detail_show_the_same_value_source_and_quote_time(monkeypatch):
    from app.main import app

    now = dt.datetime.now(UTC)
    last = now.replace(minute=0, second=0, microsecond=0)
    monkeypatch.setattr(market_hours, "_kraken_status", lambda now, fn=None: "online")
    monkeypatch.setattr(bars, "_kraken", lambda symbol, tf, inst: (_hourly(last, 78000.0), {"symbol": symbol}))
    monkeypatch.setattr(bars, "kraken_last_trade", lambda symbol: now.timestamp() - 20)
    client = TestClient(app)
    tick = next(q for q in client.get("/api/tickers").json()["live"] if q["symbol"] == "BTCUSD")
    q = prices.quote("BTCUSD")
    assert tick["price"] == round(q["price"], tick["digits"]) and tick["source"] == q["source"]
    assert tick["as_of"] == q["last_quote"]["time"] and tick["time_verified"] is True
    assert q["last_quote"]["tradable_now"] is True and q["quality"]["status"] == quality.LIVE


def test_fixing_is_never_a_live_quote(monkeypatch):
    from app.connectors import ecb

    rates = _ecb("2026-10-30", 1.1172, 175.68)
    rates.update(_ecb("2026-10-29", 1.1180, 176.0))
    monkeypatch.setattr(ecb, "fetch_history", lambda now, client=None: rates)
    now = dt.datetime(2026, 10, 30, 18, 0, tzinfo=UTC)  # Friday, FX open
    bs = bars.get_bars("USDJPY", "D1", now=now, store=False)
    assert bs.provider == "ecb" and bs.kind == "fixing_daily"
    lq = bs.last_quote
    assert lq["reference"] is True and lq["tradable_now"] is False and lq["time_verified"] is True
    assert lq["time"].startswith("2026-10-30T13:15")  # 14:15 Frankfurt (CET) = 13:15 UTC
    assert bs.quality["status"] != quality.LIVE
    assert "ne cena trhu" in lq["note"]


def test_proxy_is_never_the_instrument(monkeypatch):
    now = dt.datetime(2026, 10, 28, 14, 0, tzinfo=UTC)
    monkeypatch.setattr(market_hours, "_kraken_status", lambda now, fn=None: "online")
    monkeypatch.setattr(bars, "_kraken", lambda symbol, tf, inst: (_hourly(now, 4000.0), {"symbol": symbol}))
    monkeypatch.setattr(bars, "kraken_last_trade", lambda symbol: now.timestamp() - 30)
    paxg = bars.get_bars("PAXGUSD", "H1", now=now, store=False)
    xau = bars.get_bars("XAUUSD", "H1", now=now, store=False)
    assert paxg.ok and paxg.proxy and paxg.quality["status"] == quality.PROXY
    assert not xau.ok and xau.provider is None  # PAXG data never become XAUUSD


def test_open_market_with_an_old_last_trade_is_stale(monkeypatch):
    now = dt.datetime(2026, 10, 28, 14, 0, tzinfo=UTC)  # Wednesday, FX open
    monkeypatch.setattr(bars, "_kraken", lambda symbol, tf, inst: (_hourly(now), {"symbol": symbol}))
    monkeypatch.setattr(bars, "validate_kraken_fx", lambda code, b, ecb_rates=None: None)
    monkeypatch.setattr(bars, "kraken_last_trade", lambda symbol: now.timestamp() - 3 * 3600)  # API still returns bars …
    bs = bars.get_bars("EURUSD", "H1", now=now, store=False)
    assert bs.market["state"] == market_hours.OPEN
    assert bs.quality["status"] == quality.STALE and bs.last_quote["tradable_now"] is False  # … but nothing traded for 3 h


def test_closed_market_shows_the_exact_last_trade(monkeypatch):
    now = dt.datetime(2026, 11, 1, 9, 0, tzinfo=UTC)  # Sunday
    last_trade = dt.datetime(2026, 10, 30, 20, 58, 41, tzinfo=UTC)
    monkeypatch.setattr(bars, "_kraken", lambda symbol, tf, inst: (_hourly(dt.datetime(2026, 10, 30, 20, 0, tzinfo=UTC)), {"symbol": symbol}))
    monkeypatch.setattr(bars, "validate_kraken_fx", lambda code, b, ecb_rates=None: None)
    monkeypatch.setattr(bars, "kraken_last_trade", lambda symbol: last_trade.timestamp())
    bs = bars.get_bars("EURUSD", "H1", now=now, store=False)
    assert bs.market["state"] == market_hours.CLOSED
    assert bs.last_quote["time"] == last_trade.isoformat() and bs.last_quote["time_verified"] is True
    assert bs.last_quote["tradable_now"] is False and "pá 30. 10. 2026 21:58" in bs.last_quote["time_cs"]


def test_daily_value_without_a_known_time_says_so(monkeypatch):
    from app.connectors import official_alt

    monkeypatch.setattr(official_alt, "eia_daily", lambda series: {"2026-10-26": 101.0, "2026-10-27": 103.37})
    bs = bars.get_bars("USOIL", "D1", now=dt.datetime(2026, 10, 28, 15, 0, tzinfo=UTC), store=False)
    assert bs.ok and bs.last_quote["time_verified"] is False
    assert "čas zdroj neuvádí" in bs.last_quote["time_cs"] and bs.last_quote["tradable_now"] is False
