"""The one authoritative price of an instrument ("quote") for every module that shows a price:
ticker, overview cards, detail, AI context, alerts. It always comes from app/data/bars.py — the
instrument's own feeds — so a module can never show a different price for the same instrument
than the chart and the analysis use.
"""

from __future__ import annotations

import datetime as dt

from app.data import bars as bars_mod
from app.data import universe

TICKER_CODES = ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "US500", "US100", "USOIL", "BTCUSD", "ETHUSD", "PAXGUSD")


def quote(code: str, now: dt.datetime | None = None) -> dict:
    """{code, symbol, available, price, change_pct, source, provider, quality, market, last_quote, proxy, kind_cs, notes}.
    The change is measured against the previous close of the SAME feed (never across two sources)."""
    inst = universe.get(code)
    if inst is None:
        return {"code": code, "available": False, "notes": ["Neznámý instrument."]}
    bs = None
    for tf in ("M15", "H1", "D1"):
        bs = bars_mod.get_bars(code, tf, now=now)
        if bs.ok:
            break
    base = {"code": inst.code, "symbol": inst.symbol, "name": inst.name, "digits": inst.digits if inst.digits < 4 else 4}
    if bs is None or not bs.ok:
        return {**base, "available": False, "market": bs.market if bs else {}, "notes": (bs.notes if bs else [])[:2]}
    d1 = bs if bs.tf == "D1" else bars_mod.get_bars(code, "D1", now=now)
    prev = None
    if d1.ok and d1.provider == bs.provider and len(d1.bars) >= 2:
        last_day = dt.datetime.fromtimestamp(d1.bars[-1][0], dt.timezone.utc).date()
        today = (now or dt.datetime.now(dt.timezone.utc)).date()
        prev = d1.bars[-2][4] if (bs.tf != "D1" and last_day == today) or bs.tf == "D1" else d1.bars[-1][4]
    price = bs.last_quote["price"]
    return {**base, "available": True, "price": price, "change_pct": round((price / prev - 1) * 100, 2) if prev else None,
            "itype": inst.itype, "itype_cs": universe.ITYPE_CS.get(inst.itype, inst.itype), "reference": bs.last_quote.get("reference", False),
            "source": bs.source, "provider": bs.provider, "quality": bs.quality, "market": bs.market, "last_quote": bs.last_quote,
            "proxy": bs.proxy, "kind_cs": universe.KIND_CS.get(bs.kind, bs.kind), "tf": bs.tf, "notes": bs.notes[:2]}
