"""Acceptance tests of the XAUUSD / PAXG fix (user's spec 2026-11-01, "KRITICKÁ OPRAVA FTI"):
XAUUSD only ever gets XAUUSD data; PAXG is a separate, labelled instrument; an outage is shown,
never filled with another instrument."""

import datetime as dt
import sys
import types

import pytest
from fastapi.testclient import TestClient

from app.data import bars, mt5, quality, settings_store, universe

NOW = dt.datetime(2026, 10, 28, 14, 0, tzinfo=dt.timezone.utc)  # a Wednesday, markets open


def _paxg_bars(n=300, start=1793000000, step=3600, price=4100.0):
    return [(start + i * step, price, price + 2, price - 2, price + 1, 5.0) for i in range(n)]


def test_xauusd_and_paxg_are_separate_instruments():
    xau, paxg = universe.get("XAUUSD"), universe.get("PAXGUSD")
    assert xau.code != paxg.code and xau.symbol == "XAU/USD" and paxg.symbol == "PAXG/USD"
    assert all(sym != "PAXGUSD" for _, sym in xau.feeds), "XAUUSD must never list a PAXG feed"
    assert paxg.proxy and "není to XAU/USD" in paxg.proxy_note.replace("Není", "není")
    assert not xau.proxy
    # no instrument borrows another instrument's Kraken pair
    kraken_pairs = [sym for i in universe.INSTRUMENTS for p, sym in i.feeds if p == "kraken"]
    assert len(kraken_pairs) == len(set(kraken_pairs))


def test_xauusd_is_unavailable_when_its_feeds_fail_even_if_paxg_works(monkeypatch):
    calls = []

    def kraken_ok(symbol, tf, inst):
        calls.append(symbol)
        return _paxg_bars(), {"symbol": symbol}

    monkeypatch.setattr(bars, "_kraken", kraken_ok)
    bs = bars.get_bars("XAUUSD", "H1", now=NOW, store=False)
    assert not bs.ok and bs.bars == []
    assert bs.quality["status"] == quality.UNAVAILABLE
    assert "PAXGUSD" not in calls, "XAUUSD must not even ask for PAXG"
    assert any("MT5" in t["error"] or "MetaTrader" in t["name"] for t in bs.tried)


def test_paxg_comes_from_kraken_and_is_labelled_as_a_proxy(monkeypatch):
    monkeypatch.setattr(bars, "_kraken", lambda symbol, tf, inst: (_paxg_bars(start=int(NOW.timestamp()) - 299 * 3600), {"symbol": symbol}))
    bs = bars.get_bars("PAXGUSD", "H1", now=NOW, store=False)
    assert bs.ok and bs.provider == "kraken" and bs.proxy
    assert bs.quality["status"] == quality.PROXY
    assert bs.kind == "token"
    assert any("PAXG" in n for n in bs.notes)


def test_nbp_reference_is_never_an_xauusd_price(monkeypatch):
    """NBP's daily gold price lags the market by 1-2 days (verified 2026-11-01): never XAUUSD's price."""
    from app.connectors import nbp

    monkeypatch.setattr(nbp, "fetch_gold_usd", lambda now, client=None, sleep_fn=None, cache_file=None:
                        {(dt.date(2026, 1, 1) + dt.timedelta(days=i)).isoformat(): 4000 + i for i in range(300)})
    assert all(p != "nbp" for p, _ in universe.get("XAUUSD").feeds)
    for tf in ("H1", "D1", "W1"):
        bs = bars.get_bars("XAUUSD", tf, now=NOW, store=False)
        assert not bs.ok and bs.quality["status"] == quality.UNAVAILABLE
    assert any("NBP" in n and "nepoužívá" in n for n in bs.notes)


def _fake_mt5(rows, tick_time=None):
    m = types.SimpleNamespace()
    for i, tf in enumerate(universe.TIMEFRAMES):
        setattr(m, f"TIMEFRAME_{tf}", i)
    m.initialize = lambda path=None, timeout=None: True
    m.shutdown = lambda: None
    m.last_error = lambda: (0, "ok")
    m.symbol_info = lambda name: object() if name == "XAUUSD_ecn" else None
    m.symbol_select = lambda name, on: True
    m.copy_rates_from_pos = lambda symbol, frame, start, count: rows
    m.symbol_info_tick = lambda symbol: types.SimpleNamespace(time=tick_time) if tick_time else None
    m.account_info = lambda: types.SimpleNamespace(company="Purple Trading", server="PurpleTrading-Demo")
    m.terminal_info = lambda: types.SimpleNamespace(company="Purple Trading")
    return m


def test_mt5_feed_gives_real_xauusd_in_utc_with_the_broker_named(monkeypatch):
    server_offset = 2  # server clock = UTC+2
    base = int(NOW.timestamp()) - 99 * 3600
    rows = [{"time": base + i * 3600 + server_offset * 3600, "open": 4000.0, "high": 4005.0, "low": 3995.0, "close": 4001.0,
             "tick_volume": 120} for i in range(100)]
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5(rows))
    cfg = {"enabled": True, "terminal_path": "C:/x/terminal64.exe", "symbols": {}, "server_utc_offset_hours": server_offset}
    monkeypatch.setattr(settings_store, "get", lambda path, default=None: cfg if path == "mt5" else default)
    mt5._state.update({"path": None, "offset": None, "offset_at": 0.0})
    bs = bars.get_bars("XAUUSD", "H1", now=NOW, store=False)
    assert bs.ok and bs.provider == "mt5"
    assert bs.feed_symbol == "XAUUSD_ecn" and "Purple Trading" in bs.source
    assert bs.bars[0][0] == base, "server time must be converted to UTC"
    assert bs.quality["status"] == quality.LIVE and not bs.proxy
    assert "tick volume" in bs.meta["volume"]


def test_mt5_stays_off_until_the_user_enables_it(monkeypatch):
    monkeypatch.setitem(sys.modules, "MetaTrader5", _fake_mt5([]))
    monkeypatch.setattr(settings_store, "get", lambda path, default=None: {"enabled": False} if path == "mt5" else default)
    bs = bars.get_bars("XAUUSD", "H1", now=NOW, store=False)
    assert not bs.ok
    assert any("není zapnutý" in t["error"] for t in bs.tried)


def test_candles_endpoint_never_serves_paxg_for_xauusd(monkeypatch):
    from app.main import app

    monkeypatch.setattr(bars, "_kraken", lambda symbol, tf, inst: (_paxg_bars(), {"symbol": symbol}))
    client = TestClient(app)
    r = client.get("/api/instruments/XAUUSD/candles", params={"tf": "H1"})
    assert r.status_code == 503
    assert "XAU/USD" in r.json()["detail"]
    p = client.get("/api/instruments/PAXGUSD/candles", params={"tf": "H1"}).json()
    assert p["code"] == "PAXGUSD" and p["proxy"] is True and p["instrument"]["symbol"] == "PAXG/USD"


def test_gold_cycle_uses_only_xauusd_bars(monkeypatch):
    from app.market import service

    monkeypatch.setattr(bars, "_kraken", lambda symbol, tf, inst: (_paxg_bars(), {"symbol": symbol}))
    warnings: list[str] = []
    candles, info = service.gold_bars(NOW, warnings)
    assert candles == {}  # Kraken would have answered for PAXG — XAUUSD must stay empty
    assert all(i["provider"] is None for i in info.values())
    assert any("XAUUSD" in w for w in warnings)


@pytest.mark.parametrize("hours,rhythm,expected", [
    (0.01, "tick", quality.LIVE),
    (0.25, "tick", quality.DELAYED),  # a quote 15 min old is delayed …
    (2, "tick", quality.STALE),  # … two hours old while the market is open: stale
    (48, "tick", quality.STALE),
    (30, "daily", quality.DELAYED),
    (24 * 10, "daily", quality.STALE),
    (24 * 40, "monthly", quality.HISTORICAL),
    (24 * 150, "monthly", quality.STALE),
])
def test_quality_labels_never_call_old_data_live(hours, rhythm, expected):
    t = NOW - dt.timedelta(hours=hours)
    assert quality.classify(t, NOW, rhythm)["status"] == expected


def test_fred_failure_falls_back_to_the_official_publisher_and_says_so(monkeypatch):
    import httpx

    from app.connectors import fred, official_alt

    monkeypatch.undo()  # use the real fallback, but no network: stub BLS only
    monkeypatch.setattr(fred, "RETRIES", 0)
    monkeypatch.setattr(fred.secrets, "get", lambda name: "")
    monkeypatch.setattr(official_alt, "bls_all", lambda: {"CPILFESL": {"2026-08-01": 337.0, "2026-09-01": 338.9}})

    class Boom:
        def get(self, *a, **k):
            raise httpx.ConnectError("down")

        def close(self):
            pass

    obs = fred.fetch_observations("CPILFESL", client=Boom(), sleep_fn=lambda s: None, history_days=400)
    assert obs[-1] == {"date": "2026-09-01", "value": 338.9}
    assert fred.LAST_SOURCE["CPILFESL"].startswith("BLS")
