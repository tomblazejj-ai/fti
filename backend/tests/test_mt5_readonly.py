"""MT5 is only a market-data source (user's decision 2026-11-01): no order, position or deal function may
ever be called, FTI never starts the terminal itself, and nothing else in FTI depends on it."""

import re
from pathlib import Path

import pytest

from app.data import mt5, settings_store

SRC = Path(mt5.__file__).read_text(encoding="utf-8")
FORBIDDEN = ("order_send", "order_check", "order_calc", "orders_get", "orders_total", "positions_get", "positions_total",
             "history_orders", "history_deals", "TRADE_ACTION", "ORDER_TYPE", "market_book_add")


def test_no_trading_function_anywhere_in_the_mt5_module():
    called = set(re.findall(r"mt5\.([a-z_]+)\(", SRC))
    assert not [f for f in FORBIDDEN if f in SRC]
    assert called <= {"initialize", "shutdown", "last_error", "symbol_info", "symbol_info_tick", "symbol_select",
                      "copy_rates_from_pos", "copy_rates_range", "account_info", "terminal_info"}


def test_no_other_module_calls_mt5_trading_functions():
    root = Path(mt5.__file__).resolve().parents[1]
    hits = [str(p) for p in root.rglob("*.py") if any(f in p.read_text(encoding="utf-8") for f in FORBIDDEN[:8])]
    assert hits == []


def test_fti_never_starts_the_terminal(monkeypatch):
    class Fake:
        initialized = False

        def initialize(self, **kw):
            Fake.initialized = True
            return True

        def shutdown(self):
            pass

    monkeypatch.setattr(settings_store, "get", lambda path, default=None: {"enabled": True, "terminal_path": "C:/MT5/terminal64.exe"}
                        if path == "mt5" else default)
    monkeypatch.setattr(mt5, "terminal_running", lambda path: False)
    mt5._state["path"] = None
    with pytest.raises(mt5.Mt5Unavailable, match="nespouští"):
        mt5._connect(Fake())
    assert Fake.initialized is False


def test_server_time_follows_us_daylight_saving_per_candle():
    import datetime as dt

    utc = dt.timezone.utc
    # Fri 30 Oct 2026: New York on summer time → server UTC+3; Mon 2 Nov 2026: winter time → server UTC+2
    fri_close = dt.datetime(2026, 10, 30, 21, 0, tzinfo=utc)
    mon = dt.datetime(2026, 11, 2, 10, 0, tzinfo=utc)
    assert mt5.server_to_utc(int(fri_close.timestamp()) + 3 * 3600, ("ny7", 0)) == int(fri_close.timestamp())
    assert mt5.server_to_utc(int(mon.timestamp()) + 2 * 3600, ("ny7", 0)) == int(mon.timestamp())
    assert mt5.server_to_utc(int(mon.timestamp()) + 3600, ("fixed", 1.0)) == int(mon.timestamp())
