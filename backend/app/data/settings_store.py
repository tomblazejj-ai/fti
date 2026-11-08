"""User settings that are not secrets: data-source choices, analysis rules, score weights,
AI budget, risk defaults. Stored in backend/fti_settings.json on this PC (git-ignored).

Secrets (API keys) live in backend/.env — see app/data/secrets.py.
"""

from __future__ import annotations

import copy
import json
import threading

from app.config import BACKEND_DIR

SETTINGS_FILE = BACKEND_DIR / "fti_settings.json"
_lock = threading.Lock()

DEFAULTS: dict = {
    # Real broker feeds stay OFF until the user turns them on (they touch the user's own terminal/account).
    "mt5": {
        "enabled": False,
        "terminal_path": "",  # e.g. C:\\Program Files\\Purple Trading MT5 Terminal\\terminal64.exe
        "symbols": {},  # FTI code -> broker symbol, e.g. {"XAUUSD": "XAUUSD_ecn"}
        "server_utc_offset_hours": None,  # None = detect from the last tick while the market is open
    },
    "oanda": {"environment": "practice"},  # practice | live (read-only market data either way)
    "structure": {
        "pivot_left": 3,  # a swing high needs `left` lower highs before it …
        "pivot_right": 3,  # … and `right` after it (confirmation delay)
        "break_by": "close",  # close | wick: what counts as a break of a swing level
        "min_break_atr": 0.0,  # how far beyond the level (in ATR) the break must reach
        "mss_displacement_atr": 1.5,  # CHOCH with a candle this large (range/ATR) is also an MSS
    },
    "fvg": {"min_size_atr": 0.1},
    "zones": {"base_max_candles": 3, "base_max_range_atr": 0.8, "impulse_min_atr": 1.5, "impulse_min_body": 0.6},
    "order_blocks": {"displacement_atr": 1.5, "max_lookback": 10},
    "liquidity": {"equal_tolerance_atr": 0.1, "min_touches": 2},
    "scoring": {
        # group -> weight (normalised over the groups that have data, so they need not sum to 1)
        "weights": {"technical": 0.30, "structure": 0.15, "fundamental": 0.20, "intermarket": 0.10, "cot": 0.08,
                    "sentiment": 0.05, "seasonality": 0.04, "news": 0.08},
    },
    "ai": {
        # FTI costs nothing (user's rule): no paid AI. "none" = reports built by the deterministic engine;
        # "groq" = Groq FREE plan (key GROQ_API_KEY); "ollama" = a free open-source model on this PC, if installed.
        "provider": "none",
        "local_model": "",
        "auto_analyses": False,
        # FTI's own ceilings on top of Groq Free (app/ai/guard.py); they can only be lowered, never raised past the hard caps
        "daily_request_cap": 80,
        "daily_token_cap": 100000,
        "per_minute_cap": 6,
    },
    # variant A: the PC sends its results to the user's own Cloudflare Worker (D1) for the phone; off until set up
    "cloud": {"url": "", "enabled": False},
    # preferred data provider per instrument, e.g. {"XAUUSD": "dukascopy"}; the others stay as fallbacks with their own history
    "preferred_feeds": {},
    "risk": {"account_size": 10000.0, "account_ccy": "USD", "risk_pct": 1.0, "daily_limit_pct": 3.0, "weekly_limit_pct": 6.0},
    "events": {"no_trade_minutes_before": 60},
    "watchlist": ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "US500", "US100", "USOIL", "BTCUSD"],
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    try:
        stored = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = {}
    return _merge(DEFAULTS, stored if isinstance(stored, dict) else {})


def get(path: str, default=None):
    node = load()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def update(patch: dict) -> dict:
    """Merge a partial update into the stored settings; unknown top-level keys are rejected."""
    unknown = set(patch) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"Neznámé nastavení: {', '.join(sorted(unknown))}")
    with _lock:
        try:
            stored = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        merged = _merge(stored if isinstance(stored, dict) else {}, patch)
        SETTINGS_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return load()
