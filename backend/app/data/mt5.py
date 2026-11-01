"""MetaTrader 5 terminal on this PC as a data source — through MetaQuotes' official
`MetaTrader5` Python package (pip install MetaTrader5). Read-only: this module only reads
quotes and candles; it never calls any order function.

OFF until the user turns it on in Settings (settings "mt5.enabled") and picks a terminal:
`initialize(path=…)` attaches to that terminal and starts it when it is not running, which
touches the user's own trading software. The data are the BROKER's quotes (e.g. Purple
Trading XAUUSD_ecn), labelled as such; tick volume is that broker's, not market volume.

Candle times from MT5 are in the trade server's clock, not UTC. The offset is taken from the
last tick while the market is open, else from settings, else the common "New York + 7 h"
server clock (UTC+2 in winter, UTC+3 in summer).
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from app.data import settings_store

TERMINALS_DIR = Path.home() / "AppData" / "Roaming" / "MetaQuotes" / "Terminal"
NEW_YORK = ZoneInfo("America/New_York")
_lock = threading.Lock()
_state: dict = {"path": None, "offset": None, "offset_at": 0.0}

# FTI code -> symbol names brokers commonly use (first that exists on the terminal wins)
ALIASES: dict[str, tuple[str, ...]] = {
    "US500": ("US500", "SPX500", "US500.cash", "SP500", "USA500"),
    "US100": ("US100", "NAS100", "USTEC", "US100.cash", "NDX100"),
    "US30": ("US30", "DJ30", "WS30", "US30.cash", "DOW30"),
    "GER40": ("GER40", "DE40", "DAX40", "GER40.cash", "DE30", "GER30"),
    "UK100": ("UK100", "FTSE100", "UK100.cash"),
    "JP225": ("JP225", "JPN225", "NIKKEI225", "JP225.cash"),
    "USOIL": ("USOIL", "WTI", "XTIUSD", "USOIL.cash", "CL-OIL"),
    "UKOIL": ("UKOIL", "BRENT", "XBRUSD", "UKOIL.cash"),
    "NATGAS": ("NATGAS", "XNGUSD", "NGAS", "NATGAS.cash"),
    "COPPER": ("COPPER", "XCUUSD", "HG"),
}
SUFFIXES = ("", "_ecn", ".ecn", ".c", "+", "p", "m", ".m", ".pro", ".r", ".raw", "-ECN")


class Mt5Unavailable(RuntimeError):
    pass


def discover_terminals() -> list[dict]:
    """MT5 terminals installed on this PC (from MetaQuotes' data folders), for the Settings page."""
    out = []
    try:
        dirs = [d for d in TERMINALS_DIR.iterdir() if d.is_dir()]
    except OSError:
        return out
    for d in dirs:
        origin = d / "origin.txt"
        try:
            raw = origin.read_bytes()
        except OSError:
            continue
        text = raw.decode("utf-16", errors="ignore") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "ignore")
        install = text.strip().strip("\x00")
        exe = Path(install) / "terminal64.exe"
        if not exe.exists():
            continue  # MT4 terminals and removed installs
        servers = []
        try:
            servers = sorted(p.name for p in (d / "bases").iterdir()
                             if p.is_dir() and p.name not in ("Default", "Custom", "Chats", "signals", "Signals"))
        except OSError:
            pass
        out.append({"name": Path(install).name, "path": str(exe), "servers": servers})
    return sorted(out, key=lambda x: x["name"])


def _module():
    try:
        import MetaTrader5 as mt5  # type: ignore[import-not-found]
    except ImportError as exc:
        raise Mt5Unavailable("Knihovna MetaTrader5 není nainstalovaná.") from exc
    return mt5


def enabled() -> bool:
    cfg = settings_store.get("mt5", {}) or {}
    return bool(cfg.get("enabled") and cfg.get("terminal_path"))


def _connect(mt5):
    cfg = settings_store.get("mt5", {}) or {}
    if not cfg.get("enabled"):
        raise Mt5Unavailable("Zdroj MT5 je vypnutý (zapíná se v Nastavení).")
    path = cfg.get("terminal_path") or ""
    if not path:
        raise Mt5Unavailable("Není vybraný terminál MT5.")
    if _state["path"] != path:
        if _state["path"]:
            mt5.shutdown()
        if not mt5.initialize(path=path, timeout=15000):
            err = mt5.last_error()
            _state["path"] = None
            raise Mt5Unavailable(f"Terminál MT5 se nepodařilo připojit: {err}")
        _state["path"] = path


def _ny7_offset(t: dt.datetime) -> float:
    """Server clock = New York + 7 h (most MT5 brokers: UTC+2 winter, UTC+3 summer)."""
    ny = t.astimezone(NEW_YORK)
    return (ny.utcoffset().total_seconds() / 3600) + 7


def _offset_hours(mt5, symbol: str) -> float:
    cfg = settings_store.get("mt5", {}) or {}
    if cfg.get("server_utc_offset_hours") is not None:
        return float(cfg["server_utc_offset_hours"])
    now = time.time()
    tick = mt5.symbol_info_tick(symbol)
    if tick is not None and getattr(tick, "time", 0):
        diff = (tick.time - now) / 3600
        rounded = round(diff * 2) / 2
        if abs(diff - rounded) < 0.1 and -12 <= rounded <= 14:  # a tick from the last few minutes
            _state["offset"], _state["offset_at"] = rounded, now
            return rounded
    if _state["offset"] is not None and now - _state["offset_at"] < 7 * 86400:
        return float(_state["offset"])
    return _ny7_offset(dt.datetime.now(dt.timezone.utc))


def resolve_symbol(mt5, code: str, configured: str | None = None) -> str:
    if configured:
        if mt5.symbol_info(configured) is None:
            raise Mt5Unavailable(f"Symbol {configured} na terminálu není.")
        return configured
    for base in ALIASES.get(code, (code,)):
        for suffix in SUFFIXES:
            name = base + suffix
            if mt5.symbol_info(name) is not None:
                return name
    raise Mt5Unavailable(f"Terminál nemá symbol pro {code}.")


def fetch_bars(code: str, tf: str, count: int = 1000) -> tuple[list[tuple], dict]:
    """(bars [(t_utc, o, h, l, c, tick_volume)], meta) for one FTI instrument, newest last."""
    mt5 = _module()
    with _lock:
        _connect(mt5)
        cfg = settings_store.get("mt5", {}) or {}
        symbol = resolve_symbol(mt5, code, (cfg.get("symbols") or {}).get(code))
        mt5.symbol_select(symbol, True)
        frame = getattr(mt5, f"TIMEFRAME_{tf}", None)
        if frame is None:
            raise Mt5Unavailable(f"Timeframe {tf} MT5 nezná.")
        rates = mt5.copy_rates_from_pos(symbol, frame, 0, count)
        if rates is None or len(rates) == 0:
            raise Mt5Unavailable(f"MT5 nevrátil svíčky {symbol} {tf}: {mt5.last_error()}")
        offset = _offset_hours(mt5, symbol)
        acc = mt5.account_info()
        term = mt5.terminal_info()
    shift = int(round(offset * 3600))
    bars = [(int(r["time"]) - shift, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), float(r["tick_volume"]))
            for r in rates]
    broker = getattr(acc, "company", None) or getattr(term, "company", None) or "broker"
    server = getattr(acc, "server", None) or ""
    return bars, {"symbol": symbol, "broker": broker, "server": server, "server_utc_offset_hours": offset,
                  "volume": "tick volume brokera (ne celkový objem trhu)"}
