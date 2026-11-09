"""TickBase — a check and backup of the current gold price next to Dukascopy (never its replacement).

The answers below have the shape of TickBase's documented and live answers (8. 11. 2026): /v1/status is public,
/v1/metals/latest needs the key."""

import datetime as dt
import json

import httpx
import pytest

from app.connectors import tickbase
from app.data import quality, secrets, store

NOW = dt.datetime(2026, 11, 5, 14, 30, tzinfo=dt.timezone.utc)  # Thursday, gold market open
KEY = "tb_live_" + "x" * 24

STATUS = {"now": "2026-11-05T14:30:00Z", "status": "open",
          "sources": [{"asset": "fx", "as_of": "2026-08-14T23:59:56Z", "age_seconds": 7000000, "market_state": "closed"},
                      {"asset": "metal", "symbol": "XAU", "as_of": "2026-11-05T14:29:10Z", "age_seconds": 50, "market_state": "open"}]}


def latest_body(price=4001.20, bid=4001.00, ask=4001.40, as_of="2026-11-05T14:29:10Z"):
    return {"metal": "XAU", "currency": "USD", "price": price, "unit": "troy_ounce", "bid": bid, "ask": ask, "ch": 3.1,
            "chp": 0.08, "as_of": as_of, "derived": False, "pivot": "USD"}


@pytest.fixture()
def tb(monkeypatch):
    """A fake TickBase that records every request; the key is set, the cache and the usage counter live in memory."""
    calls: list[httpx.Request] = []
    answers = {"/v1/status": (200, STATUS), "/v1/metals/latest": (200, latest_body())}
    cache: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        code, body = answers[req.url.path]
        return httpx.Response(code, json=body)

    monkeypatch.setattr(tickbase, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(secrets, "get", lambda name: KEY if name == tickbase.KEY else "")
    monkeypatch.setattr(store, "cache_put", lambda key, payload, source="", session=None: cache.__setitem__(key, payload))
    monkeypatch.setattr(store, "cache_get", lambda key, session=None: (cache.get(key), None))
    monkeypatch.setattr(store, "load_bars", lambda *a, **k: [])
    tickbase.clear()
    return {"calls": calls, "answers": answers, "cache": cache}


def m1(t: dt.datetime, close: float) -> tuple:
    ts = int(t.replace(second=0).timestamp())
    return (ts, close - 1, close + 1, close - 2, close, 10.0)


def test_latest_sends_key_only_as_bearer_header_and_parses_quote(tb):
    q = tickbase.latest("XAU", NOW)
    req = tb["calls"][-1]
    assert req.url.path == "/v1/metals/latest" and req.url.params["metal"] == "XAU"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in str(req.url)  # never in the address (logs, proxies)
    assert q["price"] == 4001.20 and q["bid"] == 4001.00 and q["as_of"].startswith("2026-11-05T14:29:10")
    assert q["used_this_month"] == 1 and q["cached"] is False


def test_latest_respects_interval_and_monthly_cap(tb, monkeypatch):
    tickbase.latest("XAU", NOW)
    again = tickbase.latest("XAU", NOW)
    assert again["cached"] is True and len(tb["calls"]) == 1  # one request per MIN_INTERVAL_S
    tickbase.clear()
    tb["cache"][tickbase.USAGE_KEY] = {"month": "2026-11", "count": tickbase.MONTHLY_CAP}
    with pytest.raises(tickbase.TickBaseBudget):
        tickbase.latest("XAU", NOW)
    assert len(tb["calls"]) == 1  # the cap stops the request before it is sent
    assert tickbase.MONTHLY_CAP * 2 <= tickbase.FREE_MONTHLY  # PC and cloud on one free key stay under 5 000


def test_without_key_nothing_is_requested(tb, monkeypatch):
    monkeypatch.setattr(secrets, "get", lambda name: "")
    with pytest.raises(tickbase.TickBaseNoKey):
        tickbase.latest("XAU", NOW)
    assert tb["calls"] == []


def test_rejected_key_and_limit_are_named_without_the_key(tb):
    tb["answers"]["/v1/metals/latest"] = (401, {"error": {"code": "invalid_api_key", "message": "Invalid", "status": 401}})
    with pytest.raises(tickbase.TickBaseKeyRejected) as e:
        tickbase.latest("XAU", NOW)
    assert KEY not in str(e.value) and "401" in str(e.value)
    tickbase.clear()
    tb["answers"]["/v1/metals/latest"] = (429, {"error": {"code": "quota_exceeded", "status": 429}})
    with pytest.raises(tickbase.TickBaseLimit):
        tickbase.latest("XAU", NOW)


def test_check_agrees_with_dukascopy_in_the_same_minute(tb, monkeypatch):
    monkeypatch.setattr(store, "load_bars", lambda *a, **k: [m1(dt.datetime(2026, 11, 5, 14, 29, tzinfo=dt.timezone.utc), 4000.10)])
    out = tickbase.check(NOW)
    assert out["state"] == "ok" and out["freshness"]["status"] == quality.NRT
    assert out["comparison"]["state"] == "match" and out["comparison"]["diff"] == pytest.approx(1.10)  # price vs Dukascopy bid
    assert "shoda" in out["text"] and "1,10" in out["text"] and out["spread_ok"] is True
    assert out["feed"]["as_of"] == "2026-11-05T14:29:10Z"
    assert tb["cache"][tickbase.CHECK_KEY]["state"] == "ok"
    assert out["quote"]["price"] == 4001.20  # on this PC the price is kept


def test_check_reports_a_real_disagreement(tb, monkeypatch):
    monkeypatch.setattr(store, "load_bars", lambda *a, **k: [m1(dt.datetime(2026, 11, 5, 14, 29, tzinfo=dt.timezone.utc), 3980.00)])
    out = tickbase.check(NOW)
    assert out["comparison"]["state"] == "mismatch" and "ROZPOR" in out["text"]


def test_check_without_dukascopy_minute_does_not_invent_a_comparison(tb):
    out = tickbase.check(NOW)
    assert out["comparison"]["state"] == "no_reference" and "diff" not in out["comparison"]


def test_stale_feed_while_market_open_is_stale(tb):
    tb["answers"]["/v1/metals/latest"] = (200, latest_body(as_of="2026-11-01T00:16:10Z"))
    out = tickbase.check(NOW)
    assert out["freshness"]["status"] == quality.STALE and "zdroj stojí" in out["freshness"]["text"]


def test_closed_market_feed_that_stopped_before_the_close_is_stale():
    sunday = dt.datetime(2026, 11, 8, 14, 26, tzinfo=dt.timezone.utc)
    as_of = dt.datetime(2026, 11, 1, 0, 16, 10, tzinfo=dt.timezone.utc)  # the real TickBase status of 8. 11. 2026
    last_trade = dt.datetime(2026, 11, 6, 22, 0, tzinfo=dt.timezone.utc)  # Dukascopy's last minute + 1
    v = tickbase.freshness(as_of, sunday, False, last_trade)
    assert v["status"] == quality.STALE and "zastavil dřív" in v["text"]
    ok = tickbase.freshness(dt.datetime(2026, 11, 6, 21, 58, tzinfo=dt.timezone.utc), sunday, False, last_trade)
    assert ok["status"] == quality.DELAYED


def test_public_cloud_export_never_carries_tickbase_price(tb, monkeypatch):
    monkeypatch.setenv("FTI_PUBLIC_EXPORT", "1")
    out = tickbase.check(NOW)
    assert "quote" not in out and "4001,2" not in json.dumps(out) and "4001.2" not in json.dumps(out)
    assert tickbase.quote("XAUUSD", NOW) is None


def test_backup_quote_only_when_fresh_and_never_for_other_instruments(tb):
    q = tickbase.quote("XAUUSD", NOW)
    assert q["provider"] == "tickbase" and q["price"] == 4001.20 and q["last_quote"]["time_verified"] is True
    assert q["quality"]["status"] == quality.NRT and q["last_quote"]["tradable_now"] is False
    assert tickbase.quote("EURUSD", NOW) is None
    tickbase.clear()
    tb["answers"]["/v1/metals/latest"] = (200, latest_body(as_of="2026-11-05T13:00:00Z"))
    assert tickbase.quote("XAUUSD", NOW) is None  # 90 min old with the market open: no backup, next fallback


def test_prices_quote_prefers_tickbase_over_indicative_when_no_feed(tb, monkeypatch):
    from app.data import bars as bars_mod
    from app.data import indicative, prices

    class NoBars:
        ok = False
        market: dict = {}
        notes = ["v testu nic"]

    monkeypatch.setattr(bars_mod, "get_bars", lambda code, tf, now=None: NoBars())
    monkeypatch.setattr(indicative, "quote", lambda code, now=None: {"provider": "goldapi"})
    assert prices.quote("XAUUSD", NOW)["provider"] == "tickbase"
    monkeypatch.setattr(secrets, "get", lambda name: "")
    assert prices.quote("XAUUSD", NOW)["provider"] == "goldapi"


def test_key_format_is_checked_before_saving(monkeypatch, tmp_path):
    monkeypatch.setattr(secrets, "ENV_FILE", tmp_path / ".env")
    with pytest.raises(ValueError, match="tb_live_"):
        secrets.set_key("TICKBASE_API_KEY", "sk-wrong-key-1234567")
    secrets.set_key("TICKBASE_API_KEY", KEY)
    assert f"TICKBASE_API_KEY={KEY}" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_public_files_never_carry_tickbase_prices():
    """Phone/cloud files are public: a TickBase backup quote and the check's price copy are removed, the check stays."""
    from app import export_static

    body = {"markets": [{"code": "XAUUSD", "price": {"value": 4001.2, "source": "TickBase (záloha — Dukascopy ani broker teď cenu nedodávají)"}},
                        {"code": "EURUSD", "price": {"value": 1.1, "source": "Dukascopy"}}],
            "tickers": [{"code": "XAUUSD", "provider": "tickbase", "price": 4001.2, "last_quote": {"price": 4001.2}}],
            "tickbase": {"source": "TickBase", "state": "ok", "quote": {"price": 4001.2}, "comparison": {"state": "match", "diff": 0.9}}}
    out = export_static._without_tickbase_prices(body)
    text = json.dumps(out, ensure_ascii=False)
    assert "4001.2" not in text and "4001,2" not in text
    assert out["markets"][1]["price"]["value"] == 1.1  # other sources untouched
    assert out["tickbase"]["comparison"]["state"] == "match" and "quote" not in out["tickbase"]
    assert out["tickers"][0]["available"] is False


def test_quote_from_closed_market_is_compared_with_the_last_trade_before_it(tb, monkeypatch):
    """TickBase's real state on 8. 11.: last gold quote Sunday 1. 11. 00:16 UTC (market closed) — the same moment at
    Dukascopy is Friday's last minute, not a minute of the weekend that does not exist."""
    fri = [m1(dt.datetime(2026, 10, 30, 20, 58, tzinfo=dt.timezone.utc), 3999.0),
           m1(dt.datetime(2026, 10, 30, 20, 59, tzinfo=dt.timezone.utc), 4000.0)]
    monkeypatch.setattr(store, "load_bars", lambda *a, **k: fri)
    ref = tickbase._reference(dt.datetime(2026, 11, 1, 0, 16, 10, tzinfo=dt.timezone.utc))
    assert ref["close"] == 4000.0 and ref["t"].startswith("2026-10-30T20:59") and "zavřený" in ref["match"]
    assert tickbase._reference(dt.datetime(2026, 11, 5, 14, 29, 10, tzinfo=dt.timezone.utc)) is None  # open market: same minute only


# --- regressions from the authenticated test of 8. 11. 2026: TickBase's real answer has this SHAPE; the numbers are
# synthetic with the same properties (price = middle of bid and ask, spread 1.495 %) — its terms forbid sharing raw answers ---
REAL = {"metal": "XAU", "currency": "USD", "price": 3900.00, "bid": 3870.85, "ask": 3929.15, "as_of": "2026-11-01T00:16:10Z"}
SUNDAY = dt.datetime(2026, 11, 8, 15, 56, 44, tzinfo=dt.timezone.utc)


def test_last_trading_moment_comes_from_the_calendar_without_any_feed():
    assert tickbase.last_trading_moment(SUNDAY) == dt.datetime(2026, 11, 6, 22, 0, tzinfo=dt.timezone.utc)
    assert tickbase.last_trading_moment(NOW) == NOW  # open market


def test_week_old_tickbase_price_is_never_the_backup_even_with_dukascopy_down(tb, monkeypatch):
    """The real case: Dukascopy down, no candles at all, TickBase answers its 1. 11. price on Sunday 8. 11. —
    FTI used it as 'se zpožděním' before the fix. Now it is refused and the next fallback is used."""
    from app.data import bars as bars_mod
    from app.data import indicative, prices

    tb["answers"]["/v1/metals/latest"] = (200, REAL)

    class NoBars:
        ok = False
        market: dict = {}
        notes = ["výpadek"]

    monkeypatch.setattr(bars_mod, "get_bars", lambda code, tf, now=None: NoBars())
    monkeypatch.setattr(indicative, "quote", lambda code, now=None: {"provider": "goldapi"})
    assert tickbase.quote("XAUUSD", SUNDAY) is None
    assert prices.quote("XAUUSD", SUNDAY)["provider"] == "goldapi"


def test_implausible_spread_is_flagged_and_never_a_backup(tb):
    tb["answers"]["/v1/metals/latest"] = (200, {**REAL, "as_of": "2026-11-05T14:29:10Z"})  # fresh time, 58 USD spread
    assert tickbase.quote("XAUUSD", NOW) is None
    out = tickbase.check(NOW)
    assert out["spread_pct"] == 1.495 and out["spread_ok"] is False and "rozpětí" in out["text"].lower()


def test_reference_falls_back_to_coarser_dukascopy_candles(tb, monkeypatch):
    """Dukascopy M1 for 30. 10. is not stored, H1 is: Friday's last H1 close is the price at TickBase's weekend time."""
    h1 = (int(dt.datetime(2026, 10, 30, 20, 0, tzinfo=dt.timezone.utc).timestamp()), 3880.0, 3885.0, 3870.0, 3874.585, None)
    monkeypatch.setattr(store, "load_bars", lambda code, tf, provider, since=None, session=None: [h1] if tf == "H1" else [])
    ref = tickbase._reference(dt.datetime(2026, 11, 1, 0, 16, 10, tzinfo=dt.timezone.utc))
    assert ref["tf"] == "H1" and ref["close"] == 3874.585 and "zavřený" in ref["match"]
    cmp = tickbase.compare(3900.00, ref)
    assert cmp["state"] == "mismatch" and cmp["diff"] == pytest.approx(25.415, abs=0.01)


def test_freshness_fails_closed():
    """Without knowing when the market last traded, or past 4 days, a closed-market quote is stale — never 'delayed'."""
    as_of = dt.datetime(2026, 11, 6, 21, 58, tzinfo=dt.timezone.utc)
    assert tickbase.freshness(as_of, SUNDAY, False, None)["status"] == quality.STALE
    assert tickbase.freshness(as_of, as_of + dt.timedelta(days=5), False, as_of)["status"] == quality.STALE


def test_raw_answer_of_8_11_is_parsed_verbatim_and_other_units_are_refused(tb):
    """The real body's shape: no high/low, no derived — price is exactly the middle of bid and ask, nothing is recomputed."""
    raw = {"metal": "XAU", "currency": "USD", "price": 3900.00, "unit": "troy_ounce", "bid": 3870.85, "ask": 3929.15,
           "as_of": "2026-11-01T00:16:10Z"}
    tb["answers"]["/v1/metals/latest"] = (200, raw)
    q = tickbase.latest("XAU", NOW)
    assert (q["price"], q["bid"], q["ask"]) == (3900.00, 3870.85, 3929.15)
    assert q["price"] == pytest.approx((q["bid"] + q["ask"]) / 2) and tickbase.spread_pct(q) == 1.495
    tickbase.clear()
    tb["answers"]["/v1/metals/latest"] = (200, {**raw, "unit": "gram"})
    with pytest.raises(tickbase.TickBaseError, match="jednotku"):
        tickbase.latest("XAU", NOW)


# --- price polling only while TickBase's PUBLIC status shows current gold data (user's decision 8. 11. 2026) ---
STALE_STATUS = {"now": "2026-11-08T16:00:00Z", "status": "closed",
                "sources": [{"asset": "metal", "symbol": "XAU", "as_of": "2026-11-01T00:16:10Z", "age_seconds": 661000, "market_state": "closed"}]}


def priced(calls):
    return [c for c in calls if c.url.path == "/v1/metals/latest"]


def test_stale_public_status_pauses_price_requests_but_keeps_watching(tb):
    tb["answers"]["/v1/status"] = (200, STALE_STATUS)
    out = tickbase.check(SUNDAY)
    assert out["state"] == "paused" and out["price_polling"] == "paused" and "vypnuté" in out["text"]
    assert out["feed"]["as_of"] == "2026-11-01T00:16:10Z"  # availability is still checked
    assert priced(tb["calls"]) == [] and all("authorization" not in c.headers for c in tb["calls"])  # no quota spent
    assert tickbase.quote("XAUUSD", SUNDAY) is None and priced(tb["calls"]) == []


def test_unknown_status_closes_the_gate(tb):
    tb["answers"]["/v1/status"] = (503, {"error": {"code": "upstream_unavailable", "status": 503}})
    out = tickbase.check(NOW)
    assert out["state"] == "paused" and priced(tb["calls"]) == []


def test_fresh_public_status_opens_the_gate_again(tb):
    out = tickbase.check(NOW)  # STATUS: gold data 50 s old, market open
    assert out["price_polling"] == "on" and len(priced(tb["calls"])) == 1
