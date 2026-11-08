"""Indicative spot price of gold and silver from gold-api.com (free, no key, commercial use allowed).

What it is — and is not:
  * the real XAU/XAG spot price in USD per troy ounce, NOT PAXG or any other proxy;
  * gold-api.com names neither its source nor the quote time ("updatedAt" is the time of our request),
    so FTI shows it as ORIENTAČNÍ (INDICATIVE): never live, never tradable, with the time FTI received it;
  * used only when no broker feed (MT5 / OANDA) delivers the instrument;
  * if the price has not moved for STUCK_MINUTES while the market is open, the source is taken as stuck (STALE).
"""

from __future__ import annotations

import datetime as dt
import threading
import time

import httpx

from app.data import market_hours, quality, universe

URL = "https://api.gold-api.com/price/{symbol}"
SYMBOLS = {"XAUUSD": "XAU", "XAGUSD": "XAG"}
SOURCE = "gold-api.com (orientační — zdroj ani čas kotace neuvádí)"
KIND_CS = "orientační spotová cena (čas kotace neověřen)"
TTL = 60.0
STUCK_MINUTES = 10
_transport: httpx.BaseTransport | None = None  # tests inject a mock
_cache: dict[str, tuple[float, dict | None]] = {}
_moves: dict[str, tuple[float, dt.datetime]] = {}  # code -> (price, since when unchanged)
_lock = threading.Lock()


def _fetch(code: str) -> dict | None:
    """{price, received_at} or None. Cached TTL seconds; a failure is never guessed over."""
    with _lock:
        hit = _cache.get(code)
        if hit and time.monotonic() - hit[0] < TTL:
            return hit[1]
    out = None
    try:
        with httpx.Client(timeout=10.0, transport=_transport, headers={"User-Agent": "FTI/1.0 (personal analysis)"}) as c:
            r = c.get(URL.format(symbol=SYMBOLS[code]))
        body = r.json() if r.status_code == 200 else {}
        price = float(body.get("price"))
        if body.get("symbol") == SYMBOLS[code] and price > 0:
            out = {"price": price, "received_at": dt.datetime.now(dt.timezone.utc)}
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        out = None
    with _lock:
        _cache[code] = (time.monotonic(), out)
    return out


def clear() -> None:
    with _lock:
        _cache.clear()
        _moves.clear()


def quote(code: str, now: dt.datetime | None = None) -> dict | None:
    """A quote in the shape of prices.quote(), or None when gold-api has nothing for this instrument."""
    inst = universe.get(code)
    if inst is None or code not in SYMBOLS:
        return None
    got = _fetch(code)
    if got is None:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    market = market_hours.state(inst, now)
    is_open = market.get("state") == market_hours.OPEN
    with _lock:
        prev = _moves.get(code)
        if prev is None or prev[0] != got["price"]:
            _moves[code] = (got["price"], got["received_at"])
        since = _moves[code][1]
    received_cs = market_hours.prague(got["received_at"])
    stuck = is_open and (now - since) >= dt.timedelta(minutes=STUCK_MINUTES)
    if stuck:
        status = quality.STALE
        text = (f"Trh je otevřený, ale cena se nezměnila od {market_hours.prague(since)} — zdroj zřejmě stojí. "
                "Hodnota je jen orientační.")
    else:
        status = quality.INDICATIVE
        text = (f"Orientační cena přijatá {received_cs}. Zdroj neuvádí čas kotace ani odkud cena pochází, "
                "proto to není ověřená živá kotace.")
        if not is_open:
            text = f"{market.get('label', 'Trh zavřen').capitalize()} — orientační poslední cena přijatá {received_cs}."
    q = {"status": status, "freshness": status, "label": quality.LABELS_CS[status], "as_of": got["received_at"].isoformat(),
         "age_hours": 0.0, "text": text}
    last = {"price": got["price"], "time": None, "time_cs": f"čas kotace zdroj neuvádí (přijato {received_cs})",
            "received_at": got["received_at"].isoformat(), "fetched_at": got["received_at"].isoformat(), "age_minutes": None,
            "tradable_now": False, "time_verified": False, "reference": False, "indicative": True, "kind_cs": KIND_CS,
            "timezone": "UTC (zobrazeno v čase Prahy SEČ/SELČ)",
            "note": "Orientační cena bez ověřeného času kotace — ne obchodovatelná kotace."}
    return {"code": inst.code, "symbol": inst.symbol, "name": inst.name, "digits": inst.digits if inst.digits < 4 else 4,
            "available": True, "price": got["price"], "change_pct": None, "itype": inst.itype,
            "itype_cs": universe.ITYPE_CS.get(inst.itype, inst.itype), "reference": False, "indicative": True,
            "source": SOURCE, "provider": "goldapi", "quality": q, "market": market, "last_quote": last, "proxy": False,
            "kind_cs": KIND_CS, "tf": None,
            "notes": ["Broker (MT5 / OANDA) není připojený — zobrazuje se orientační cena gold-api.com bez času kotace."]}
