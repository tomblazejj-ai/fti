"""Orientační (indicative) gold price from gold-api.com: the real XAU/USD spot, never PAXG, never shown
as live or tradable, with the time FTI received it; stuck while the market is open → STALE; only
used when no broker feed delivers XAUUSD."""

import datetime as dt

import httpx
import pytest

from app.ai import facts
from app.data import bars, indicative, market_hours, prices, quality

UTC = dt.timezone.utc
OPEN = dt.datetime(2026, 11, 3, 14, 0, tzinfo=UTC)  # Tuesday afternoon, metals open
WEEKEND = dt.datetime(2026, 11, 1, 12, 0, tzinfo=UTC)  # Sunday noon, closed


def _gold(monkeypatch, price=3876.4, at=OPEN):
    got = {"price": price, "received_at": at}
    monkeypatch.setattr(indicative, "_fetch", lambda code: dict(got) if code in ("XAUUSD", "XAGUSD") else None)
    return got


def test_without_a_broker_xauusd_gets_the_indicative_spot_price_never_paxg(monkeypatch):
    _gold(monkeypatch)
    q = prices.quote("XAUUSD", now=OPEN)
    assert q["available"] and q["price"] == 3876.4 and q["provider"] == "goldapi" and q["indicative"] is True
    assert q["quality"]["status"] == quality.INDICATIVE and q["quality"]["label"] == "orientační"
    assert q["proxy"] is False and "gold-api.com" in q["source"] and "PAXG" not in q["source"]
    lq = q["last_quote"]
    assert lq["time"] is None and lq["time_verified"] is False and lq["tradable_now"] is False
    assert "čas kotace zdroj neuvádí" in lq["time_cs"] and lq["received_at"]


def test_closed_market_says_so(monkeypatch):
    _gold(monkeypatch, at=WEEKEND)
    q = prices.quote("XAUUSD", now=WEEKEND)
    assert q["market"]["state"] != market_hours.OPEN and q["quality"]["status"] == quality.INDICATIVE
    assert "orientační poslední cena" in q["quality"]["text"]


def test_a_price_that_does_not_move_while_the_market_is_open_is_stale(monkeypatch):
    got = _gold(monkeypatch)
    t0 = dt.datetime.now(UTC)
    got["received_at"] = t0
    monkeypatch.setattr(market_hours, "state", lambda inst, now, crypto_status_fn=None: {"state": market_hours.OPEN, "label": "trh otevřen"})
    assert indicative.quote("XAUUSD", now=t0)["quality"]["status"] == quality.INDICATIVE
    later = indicative.quote("XAUUSD", now=t0 + dt.timedelta(minutes=11))
    assert later["quality"]["status"] == quality.STALE and "zdroj zřejmě stojí" in later["quality"]["text"]


def test_gold_api_down_means_unavailable_not_a_guess(monkeypatch):
    q = prices.quote("XAUUSD", now=OPEN)  # conftest: gold-api returns nothing
    assert q["available"] is False


def test_a_broker_feed_wins_over_the_indicative_price(monkeypatch):
    _gold(monkeypatch)
    now = OPEN
    t0 = int(now.timestamp()) - 3600 * 50
    h1 = [(t0 + i * 3600, 3870.0, 3871.0, 3869.0, 3870.5, 10.0) for i in range(50)]
    monkeypatch.setattr(bars, "_oanda", lambda symbol, tf: (h1 if tf != "D1" else [], {"symbol": symbol}))
    q = prices.quote("XAUUSD", now=now)
    assert q.get("provider") != "goldapi"


def test_only_gold_and_silver_and_the_right_symbol(monkeypatch):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"symbol": "XAG", "price": 46.1, "updatedAt": "2026-11-01T14:47:35Z"})

    monkeypatch.undo()  # use the real _fetch with a mock server
    indicative.clear()
    monkeypatch.setattr(indicative, "_transport", httpx.MockTransport(handler))
    assert indicative.quote("BTCUSD") is None and seen == []
    assert indicative._fetch("XAUUSD") is None  # server answered with silver for gold — refused
    assert seen == ["https://api.gold-api.com/price/XAU"]


def test_ai_facts_call_it_indicative(monkeypatch):
    _gold(monkeypatch)
    p = facts.Packet()
    facts._quote_facts(p, "XAUUSD", lambda code: prices.quote(code, now=OPEN))
    assert "orientační cena bez času kotace" in p.facts[0]["zdroj"]
