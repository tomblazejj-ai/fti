"""One authoritative price per instrument: the ticker, the chart and the analysis show the same
number from the same feed; an instrument without its own data is shown as unavailable."""

import datetime as dt

from fastapi.testclient import TestClient

from app.data import bars, market_hours, prices


def _bars(price, n=200):
    now = int(dt.datetime.now(dt.timezone.utc).timestamp()) // 900 * 900
    return [(now - (n - 1 - i) * 900, price, price + 1, price - 1, price + i * 0.01, 3.0) for i in range(n)]


def test_ticker_chart_and_quote_agree_and_gold_is_never_filled(monkeypatch):
    from app.main import app

    monkeypatch.setattr(market_hours, "_kraken_status", lambda now, fn=None: "online")
    monkeypatch.setattr(bars, "_kraken", lambda symbol, tf, inst: (_bars(78000.0), {"symbol": symbol}))
    monkeypatch.setattr(bars, "validate_kraken_fx", lambda code, b, ecb_rates=None: None)
    client = TestClient(app)
    t = client.get("/api/tickers").json()
    btc = next(q for q in t["live"] if q["symbol"] == "BTCUSD")
    chart = client.get("/api/instruments/BTCUSD/candles", params={"tf": "M15"}).json()
    assert btc["price"] == round(chart["candles"][-1][4], btc["digits"]) == round(prices.quote("BTCUSD")["price"], btc["digits"])
    assert btc["source"] == chart["source"]
    # XAUUSD has no feed in tests: listed as unavailable, never priced from PAXG (which Kraken would answer)
    assert all(q["symbol"] != "XAUUSD" for q in t["live"])
    assert any(u["symbol"] == "XAUUSD" for u in t["unavailable"])
    paxg = next(q for q in t["live"] if q["symbol"] == "PAXGUSD")
    assert paxg["proxy"] is True and paxg["label"] == "PAXG/USD"


def test_kraken_fx_without_trades_or_off_the_fixing_is_rejected():
    import pytest

    t0 = int(dt.datetime(2026, 10, 28, 0, 0, tzinfo=dt.timezone.utc).timestamp())
    dead = [(t0 + i * 3600, 159.8, 159.8, 159.8, 159.8, 0.0) for i in range(48)]
    with pytest.raises(bars.FeedError, match="bez jediného obchodu"):
        bars.validate_kraken_fx("USDJPY", dead, ecb_rates={})
    live = [(t0 + i * 3600, 159.8, 159.9, 159.7, 159.8, 120.0) for i in range(48)]
    # ECB 28 Oct: USD 1.16, JPY 182.4 → USD/JPY 157.24; Kraken 159.8 at 13:00 UTC is 1.6 % away
    with pytest.raises(bars.FeedError, match="fixingu ECB"):
        bars.validate_kraken_fx("USDJPY", live, ecb_rates={"2026-10-28": {"USD": 1.16, "JPY": 182.4}})
    ok = [(t0 + i * 3600, 157.3, 157.4, 157.2, 157.3, 120.0) for i in range(48)]
    bars.validate_kraken_fx("USDJPY", ok, ecb_rates={"2026-10-28": {"USD": 1.16, "JPY": 182.4}})
