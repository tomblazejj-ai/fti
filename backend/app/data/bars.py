"""Price bars of one instrument on one timeframe — the single entry point every module uses
(charts, indicators, structure, zones, scanner, AI tools, backtests).

`get_bars(code, tf)` walks the instrument's own feeds (app/data/universe.py) in priority order
and returns the first that works, with its provenance and data-quality label. It never uses
another instrument's data: when every feed of XAUUSD fails, XAUUSD is UNAVAILABLE — it is not
filled with PAXG. Every fetched bar is also stored in its provider's own history (table market_bars), so
history grows; collect_history() keeps a second provider's history too (Dukascopy for XAUUSD).
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import httpx

from app.data import health, quality, settings_store, universe
from app.data.universe import TF_MINUTES

log = logging.getLogger(__name__)
NEW_YORK = ZoneInfo("America/New_York")

Bar = tuple  # (t_utc_seconds, open, high, low, close, volume|None)

KRAKEN_URL = "https://api.kraken.com/0/public/OHLC"
KRAKEN_TF = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440, "W1": 10080}
DAILY_ONLY = ("ecb", "fred", "eia", "nbp", "cboe", "treasury")
TTL = {"M1": 30, "M5": 60, "M15": 120, "M30": 180, "H1": 300, "H4": 600, "D1": 900, "W1": 1800, "MN1": 3600}

# what each feed's price IS, its rhythm, and whether it stands in for the instrument (proxy)
FEED_KIND = {
    "mt5": ("broker_quote", "tick"),
    "oanda": ("broker_quote", "tick"),
    "kraken": ("exchange_quote", "tick"),
    "ecb": ("fixing_daily", "daily"),
    "fred": ("index_daily", "daily"),
    "eia": ("spot_daily", "daily"),
    "cboe": ("index_daily", "daily"),
    "nbp": ("reference_daily", "daily"),
    "treasury": ("official_daily", "daily"),
    "dukascopy": ("delayed_bank_quote", "tick"),
}
DUKASCOPY_DAYS = {"M1": 2, "M5": 4, "M15": 7, "M30": 10, "H1": 14, "H4": 45, "D1": 200, "W1": 200}  # history it builds up
FEED_NAME = {
    "mt5": "MetaTrader 5 (broker)", "oanda": "OANDA v20", "kraken": "Kraken", "ecb": "ECB referenční kurzy",
    "fred": "FRED (St. Louis Fed)", "eia": "EIA (US Energy Information Administration)", "cboe": "CBOE",
    "nbp": "NBP (Polská národní banka)", "treasury": "US Treasury", "dukascopy": "Dukascopy Bank (zpožděné kotace)",
}


# What each provider offers at all (the rest offer every timeframe). Monitoring judges a source only by this:
# a timeframe it does not have is skipped and noted, never counted as the provider's error.
SUPPORTED_TF = {**{p: ("D1", "W1", "MN1") for p in DAILY_ONLY}, "dukascopy": tuple(DUKASCOPY_DAYS)}
# The quality a provider delivers when it works as it should: daily sources publish once a day, Dukascopy ~1 h late.
EXPECTED_QUALITY = {**{p: quality.DELAYED for p in DAILY_ONLY}, "dukascopy": quality.DELAYED}


def _unsupported_text(provider: str, tf: str) -> str:
    if provider in DAILY_ONLY:
        return f"{FEED_NAME[provider]} má jen denní data, ne {tf}."
    return f"{FEED_NAME.get(provider, provider)}: rámec {tf} zdroj nenabízí."


class FeedError(RuntimeError):
    pass


class FeedRejected(FeedError):
    """The source answered, but its data failed FTI's quality check — counted apart from outages."""


class FeedPending(FeedError):
    """Nothing to show yet, without any failure (a history still filling up)."""


@dataclass
class BarSet:
    code: str
    tf: str
    bars: list[Bar]
    provider: str | None = None
    feed_symbol: str | None = None
    source: str = ""
    kind: str = "unavailable"
    proxy: bool = False
    close_only: bool = False
    quality: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    tried: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    market: dict = field(default_factory=dict)  # market state of the instrument (app/data/market_hours.py)
    last_quote: dict = field(default_factory=dict)  # the last real price, its time and whether it is tradable now

    @property
    def ok(self) -> bool:
        return bool(self.bars)

    def describe(self) -> dict:
        inst = universe.get(self.code)
        return {
            "code": self.code, "tf": self.tf, "provider": self.provider, "feed_symbol": self.feed_symbol, "source": self.source,
            "kind": self.kind, "kind_cs": universe.KIND_CS.get(self.kind, self.kind), "proxy": self.proxy,
            "close_only": self.close_only, "quality": self.quality, "notes": self.notes, "tried": self.tried,
            "bars": len(self.bars), "last_time": self.bars[-1][0] if self.bars else None,
            "instrument": universe.identity(inst) if inst else None, "meta": self.meta,
            "market": self.market, "last_quote": self.last_quote,
        }


# --- caching -----------------------------------------------------------------------------------
_cache: dict[tuple, tuple[float, list[Bar], dict]] = {}
_lock = threading.Lock()


def _cached(key: tuple, ttl: float, fn):
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1], hit[2]
    bars, meta = fn()
    with _lock:
        _cache[key] = (time.monotonic(), bars, meta)
    return bars, meta


def clear_cache() -> None:
    with _lock:
        _cache.clear()
        _stored.clear()


_stored: dict[tuple, float] = {}  # cache key -> time of the answer that is already in the database


def _first_use(key: tuple) -> bool:
    """True once per answer of a source: bars served again from the in-memory cache are already stored, so they are
    not written again (that alone took ~20 s of every data audit)."""
    with _lock:
        hit = _cache.get(key)
        stamp = hit[0] if hit else None
        if stamp is not None and _stored.get(key) == stamp:
            return False
        _stored[key] = stamp
        return True


# --- helpers -----------------------------------------------------------------------------------
def fx_closed(t_utc: int) -> bool:
    """Inside the spot FX / spot gold weekly break (Fri 17:00 – Sun 17:00 New York)."""
    ny = dt.datetime.fromtimestamp(t_utc, dt.timezone.utc).astimezone(NEW_YORK)
    wd, h = ny.weekday(), ny.hour
    return (wd == 4 and h >= 17) or wd == 5 or (wd == 6 and h < 17)


def validate(bars: list[Bar]) -> tuple[list[Bar], int]:
    """Drop impossible bars (non-positive, high < open/close, low > open/close, time not increasing)."""
    out, dropped, last_t = [], 0, None
    for b in bars:
        t, o, h, lo, c = b[:5]
        if min(o, h, lo, c) <= 0 or h < max(o, c) - 1e-12 or lo > min(o, c) + 1e-12 or (last_t is not None and t <= last_t):
            dropped += 1
            continue
        out.append(b)
        last_t = t
    return out, dropped


def resample(bars: list[Bar], tf: str) -> list[Bar]:
    """Aggregate daily (or finer) bars to W1 (weeks from Monday) or MN1 (calendar months)."""
    groups: dict[tuple, list[Bar]] = {}
    order: list[tuple] = []
    for b in bars:
        d = dt.datetime.fromtimestamp(b[0], dt.timezone.utc)
        if tf == "W1":
            monday = (d - dt.timedelta(days=d.weekday())).date()
            key = (monday.year, monday.month, monday.day)
        elif tf == "MN1":
            key = (d.year, d.month, 1)
        else:
            raise ValueError(tf)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(b)
    out = []
    for key in order:
        g = groups[key]
        t0 = int(dt.datetime(*key, tzinfo=dt.timezone.utc).timestamp())
        vols = [x[5] for x in g if len(x) > 5 and x[5] is not None]
        out.append((t0, g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[-1][4], sum(vols) if vols else None))
    return out


def daily_closes_to_bars(closes: dict[str, float]) -> list[Bar]:
    out = []
    for d in sorted(closes):
        v = closes[d]
        if v is None:
            continue
        t = int(dt.datetime.fromisoformat(d[:10]).replace(tzinfo=dt.timezone.utc).timestamp())
        out.append((t, v, v, v, v, None))
    return out


# --- feeds -------------------------------------------------------------------------------------
def _kraken(symbol: str, tf: str, inst: universe.Instrument) -> tuple[list[Bar], dict]:
    if tf == "MN1":
        daily, meta = _kraken(symbol, "D1", inst)
        return resample(daily, "MN1"), meta
    minutes = KRAKEN_TF[tf]
    try:
        with httpx.Client(timeout=20.0, headers={"User-Agent": "FTI/1.0 (personal analysis)"}) as c:
            body = c.get(KRAKEN_URL, params={"pair": symbol, "interval": minutes}).json()
    except (httpx.HTTPError, ValueError) as exc:
        raise FeedError(f"Kraken {symbol}: {exc}") from exc
    if body.get("error"):
        raise FeedError("Kraken: " + "; ".join(body["error"]))
    rows = next((v for k, v in (body.get("result") or {}).items() if k != "last"), None)
    if not rows:
        raise FeedError(f"Kraken {symbol}: žádné svíčky")
    bars = [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[6])) for r in rows]
    if inst.session == "fx" and minutes < 10080:
        if minutes >= 1440:
            bars = [b for b in bars if dt.datetime.fromtimestamp(b[0], dt.timezone.utc).weekday() < 5]
        else:
            bars = [b for b in bars if not fx_closed(b[0])]
    return bars, {"symbol": symbol, "volume": "objem obchodů na burze Kraken" if inst.asset == "crypto"
                  else "objem na Krakenu (jen tato burza, ne celý trh)"}


def _ecb(symbol: str, tf: str) -> tuple[list[Bar], dict]:
    from app.connectors import ecb

    base, quote = symbol.split("/")
    rates = ecb.fetch_history(dt.datetime.now(dt.timezone.utc))

    def per_eur(day: dict, ccy: str) -> float | None:
        return 1.0 if ccy == "EUR" else day.get(ccy)

    closes = {}
    for d, day in rates.items():
        rb, rq = per_eur(day, base), per_eur(day, quote)
        if rb and rq:
            closes[d] = rq / rb
    if not closes:
        raise FeedError(f"ECB nemá kurz {symbol}")
    return daily_closes_to_bars(closes), {"symbol": symbol, "volume": None}


def _fred(symbol: str, tf: str) -> tuple[list[Bar], dict]:
    from app.connectors import fred

    try:
        obs = fred.fetch_observations(symbol, history_days=4000)
    except fred.FredUnavailableError as exc:
        raise FeedError(str(exc)) from exc
    return daily_closes_to_bars({o["date"]: o["value"] for o in obs}), {"symbol": symbol, "volume": None,
                                                                         "via": fred.LAST_SOURCE.get(symbol, "FRED")}


def _eia(symbol: str, tf: str) -> tuple[list[Bar], dict]:
    from app.connectors import official_alt

    try:
        closes = official_alt.eia_daily(symbol)
    except official_alt.OfficialUnavailable as exc:
        raise FeedError(str(exc)) from exc
    return daily_closes_to_bars(closes), {"symbol": symbol, "volume": None}


def _cboe(symbol: str, tf: str) -> tuple[list[Bar], dict]:
    from app.connectors import official_alt

    try:
        rows = official_alt.cboe_history(symbol)
    except official_alt.OfficialUnavailable as exc:
        raise FeedError(str(exc)) from exc
    return rows, {"symbol": symbol, "volume": None}


def _nbp(symbol: str, tf: str) -> tuple[list[Bar], dict]:
    from app.connectors import nbp

    try:
        prices = nbp.fetch_gold_usd(dt.datetime.now(dt.timezone.utc))
    except nbp.NbpUnavailableError as exc:
        raise FeedError(str(exc)) from exc
    return daily_closes_to_bars(prices), {"symbol": "NBP cena zlata → USD/oz", "volume": None}


def _treasury(symbol: str, tf: str) -> tuple[list[Bar], dict]:
    from app.connectors import official_alt

    try:
        return daily_closes_to_bars(official_alt.treasury(symbol, years=6)), {"symbol": symbol, "volume": None}
    except official_alt.OfficialUnavailable as exc:
        raise FeedError(str(exc)) from exc


def _mt5(symbol: str, tf: str, code: str) -> tuple[list[Bar], dict]:
    from app.data import mt5

    if not mt5.enabled():
        raise FeedError("MT5 není zapnutý (Nastavení → zdroje dat).")
    try:
        return mt5.fetch_bars(code, tf)
    except mt5.Mt5Unavailable as exc:
        raise FeedError(str(exc)) from exc


def _oanda(symbol: str, tf: str) -> tuple[list[Bar], dict]:
    from app.data import oanda

    if not oanda.token():
        raise FeedError("OANDA není připojena (chybí token).")
    try:
        return oanda.fetch_bars(symbol, tf)
    except oanda.OandaUnavailable as exc:
        raise FeedError(str(exc)) from exc


MAX_ZERO_VOLUME_SHARE = 0.5  # a Kraken FX book where most recent bars have no trades is not a quote
MAX_FIXING_DEVIATION_PCT = 0.5  # Kraken FX vs the ECB reference rate at fixing time


def validate_kraken_fx(code: str, bars: list[Bar], ecb_rates: dict | None = None) -> None:
    """Kraken's FX books are thin; some pairs (USD/JPY, EUR/JPY on 2026-10-30) show prices with no
    trades behind them, 1–2 % away from the market. Raise FeedError when the recent bars are mostly
    trade-less or the price at the ECB fixing time (14:15 CET) deviates from the ECB rate."""
    recent = [b for b in bars[-48:] if not fx_closed(b[0])]
    if recent:
        zero = sum(1 for b in recent if not b[5]) / len(recent)
        if zero > MAX_ZERO_VOLUME_SHARE:
            raise FeedRejected(f"Kraken {code}: {zero:.0%} posledních svíček bez jediného obchodu — kotace nespolehlivá.")
    if ecb_rates is None:
        try:
            from app.connectors import ecb

            ecb_rates = ecb.fetch_history(dt.datetime.now(dt.timezone.utc))
        except Exception:  # noqa: BLE001 — without the reference the volume check alone decides
            return
    base, quote = code[:3], code[3:]
    by_time = {b[0]: b for b in bars}
    for day in sorted(ecb_rates, reverse=True)[:5]:
        r = ecb_rates[day]
        rb, rq = (1.0 if base == "EUR" else r.get(base)), (1.0 if quote == "EUR" else r.get(quote))
        if not rb or not rq:
            return
        fixing = dt.datetime.fromisoformat(day).replace(hour=14, minute=15, tzinfo=market_tz())
        hour_open = int(fixing.astimezone(dt.timezone.utc).replace(minute=0).timestamp())
        bar = by_time.get(hour_open)
        if bar is None:
            continue
        dev = (bar[4] / (rq / rb) - 1) * 100
        if abs(dev) > MAX_FIXING_DEVIATION_PCT:
            raise FeedRejected(f"Kraken {code}: cena v čase fixingu ECB {day} se liší o {dev:+.2f} % — kotace nespolehlivá.")
        return


def market_tz():
    from zoneinfo import ZoneInfo

    return ZoneInfo("Europe/Berlin")  # ECB fixing at 14:15 Frankfurt time (CET/CEST)


def _fetch(provider: str, symbol: str, tf: str, inst: universe.Instrument, now: dt.datetime | None = None) -> tuple[list[Bar], dict]:
    if provider in DAILY_ONLY:
        if tf not in ("D1", "W1", "MN1"):
            raise FeedError(f"{FEED_NAME[provider]} má jen denní data, ne {tf}.")
        fn = {"ecb": _ecb, "fred": _fred, "eia": _eia, "cboe": _cboe, "nbp": _nbp, "treasury": _treasury}[provider]
        daily, meta = fn(symbol, "D1")
        return (daily if tf == "D1" else resample(daily, tf)), meta
    if provider == "kraken":
        bars, meta = _kraken(symbol, tf, inst)
        if inst.asset == "forex":
            # validate on hourly bars (volume + fixing time), whatever timeframe was asked for
            check = bars if tf == "H1" else _kraken(symbol, "H1", inst)[0]
            validate_kraken_fx(inst.code, check)
        return bars, meta
    if provider == "mt5":
        return _mt5(symbol, tf, inst.underlying if inst.itype == "cfd" else inst.code)
    if provider == "oanda":
        return _oanda(symbol, tf)
    if provider == "dukascopy":
        from app.connectors import dukascopy

        if tf not in DUKASCOPY_DAYS:
            raise FeedError(f"Dukascopy: rámec {tf} FTI nepodporuje.")
        sec = 86400 if tf in ("D1", "W1") else TF_MINUTES[tf] * 60
        try:
            got, meta = _cached(("dukascopy", symbol, sec, DUKASCOPY_DAYS[tf]), 300.0,
                                lambda: dukascopy.bars(symbol, sec, DUKASCOPY_DAYS[tf], now))
        except dukascopy.DukascopyUnavailable as exc:
            raise FeedError(str(exc)) from exc
        if not got:
            raise FeedPending("Dukascopy zatím nedodal žádná data (historie se doplňuje po několika souborech).")
        return (dukascopy.keep_whole(resample(got, "W1"), 7 * 86400, meta.get("covered") or []) if tf == "W1" else got), meta
    raise FeedError(f"Neznámý zdroj {provider}")


_last_trade: dict[str, tuple[float, float | None]] = {}


def kraken_last_trade(symbol: str) -> float | None:
    """Unix time of the last real trade on Kraken (exact). None when unknown."""
    hit = _last_trade.get(symbol)
    if hit and time.monotonic() - hit[0] < 30:
        return hit[1]
    t = None
    try:
        with httpx.Client(timeout=15.0, headers={"User-Agent": "FTI/1.0 (personal analysis)"}) as c:
            body = c.get("https://api.kraken.com/0/public/Trades", params={"pair": symbol, "count": 1}).json()
        rows = next((v for k, v in (body.get("result") or {}).items() if k != "last"), None)
        if rows:
            t = float(rows[-1][2])
    except Exception:  # noqa: BLE001 — unknown, never guessed
        t = None
    _last_trade[symbol] = (time.monotonic(), t)
    return t


REFERENCE_KINDS = ("fixing_daily", "reference_daily", "monthly_avg")
# the official closing time of a daily value, when the market's calendar defines it
CLOSE_TIME = {"us_cash": ((16, 0), "America/New_York"), "tse": ((15, 30), "Asia/Tokyo"), "xetra": ((17, 30), "Europe/Berlin"),
              "lse": ((16, 30), "Europe/London")}


def feed_identity(provider: str, inst: universe.Instrument) -> dict:
    """What this feed's numbers really are for this instrument (product, venue, proxy or not)."""
    kind, rhythm = FEED_KIND[provider]
    proxy, why = inst.proxy, inst.proxy_note
    if provider in ("mt5", "oanda"):
        kind = "cfd" if inst.itype == "cfd" else "broker_quote"
    elif provider == "kraken":
        if inst.asset == "forex":
            kind, proxy = "crypto_fx_quote", True
            why = "Kotace páru na kryptoburze Kraken (tenká kniha, jiné hodiny), ne mezibankovní forex — orientační náhrada."
        elif inst.itype == "token":
            kind = "token"
    elif provider == "ecb":
        why = "Referenční kurz ECB: jedna hodnota denně (~14:15 SEČ), ne tržní kotace."
    elif provider == "nbp":
        why = "Denní referenční cena zlata NBP přepočtená na USD/oz — není to kotace XAU/USD, jen denní reference."
    elif provider == "fred" and inst.itype == "cash_index":
        why = "Oficiální denní závěr indexu (přes FRED) — bez maxima a minima dne."
    if inst.itype == "monthly_price":
        kind, rhythm = "monthly_avg", "monthly"
        why = "Měsíční průměrná cena (IMF/Světová banka přes FRED) — jedna hodnota za měsíc."
    return {"kind": kind, "rhythm": rhythm, "proxy": proxy, "why": why}


def _quality(provider: str, inst: universe.Instrument, bars: list[Bar], tf: str, now: dt.datetime,
             market: dict | None = None, feed_symbol: str | None = None) -> tuple[dict, bool, str, dict]:
    """(quality label, proxy, kind, last quote) of a bar set, judged against the market state:
    an OPEN market whose last bar is old means the source stopped → STALE; a closed market shows
    the last real quote as HISTORICAL with its time, never as a current tradable price."""
    from app.data import market_hours

    ident = feed_identity(provider, inst)
    kind, rhythm, proxy = ident["kind"], ident["rhythm"], ident["proxy"]
    if not bars:
        return quality.classify(None, now, rhythm), proxy, kind, {}
    market = market or {}
    last = bars[-1][0]
    tf_s = TF_MINUTES[tf] * 60
    trading = market.get("state") == market_hours.OPEN
    time_verified = False
    last_price = bars[-1][4]
    if provider == "dukascopy":
        q, quote_t, time_verified, last_price = _dukascopy_quality(inst, bars, tf_s, now, trading, market, proxy)
    elif rhythm == "tick":
        bar_end = min(last + tf_s, now.timestamp())
        trade_t = kraken_last_trade(feed_symbol) if provider == "kraken" and feed_symbol else None
        if trade_t is not None:
            # the exact time of the last real trade decides freshness — not the bar the API returns
            time_verified = True
            age = now.timestamp() - trade_t
            if trading and age <= max(900, 2 * 60 * min(TF_MINUTES[tf], 15)):
                q, quote_t = quality.classify(now, now, "tick", proxy=proxy), dt.datetime.fromtimestamp(trade_t, dt.timezone.utc)
                q = {**q, "text": f"Poslední obchod {market_hours.prague(quote_t)}."}
            elif trading:
                quote_t = dt.datetime.fromtimestamp(trade_t, dt.timezone.utc)
                q = quality.classify(quote_t, now, "tick", proxy=proxy)
                q = {**q, "status": quality.STALE, "label": quality.LABELS_CS[quality.STALE],
                     "text": f"Trh je otevřený, ale poslední obchod byl {market_hours.prague(quote_t)} — data jsou zastaralá."}
            else:
                quote_t = dt.datetime.fromtimestamp(trade_t, dt.timezone.utc)
                q = quality.classify(quote_t, now, "weekly", proxy=proxy)
                q = {**q, "status": quality.PROXY if proxy else quality.HISTORICAL,
                     "label": quality.LABELS_CS[quality.PROXY if proxy else quality.HISTORICAL],
                     "text": f"{market.get('label', 'Trh zavřen').capitalize()} — poslední obchod {market_hours.prague(quote_t)}."}
        elif trading and now.timestamp() - last <= 2 * tf_s + 120:
            q, quote_t = quality.classify(now, now, "tick", proxy=proxy), now  # the forming bar keeps updating
        elif trading:
            q = quality.classify(dt.datetime.fromtimestamp(bar_end, dt.timezone.utc), now, "tick", proxy=proxy)
            q = {**q, "status": quality.STALE, "label": quality.LABELS_CS[quality.STALE],
                 "text": "Trh je otevřený, ale zdroj nepřináší nové kotace — data jsou zastaralá."}
            quote_t = dt.datetime.fromtimestamp(bar_end, dt.timezone.utc)
        else:
            quote_t = dt.datetime.fromtimestamp(bar_end, dt.timezone.utc)
            q = quality.classify(quote_t, now, "weekly", proxy=proxy)  # last quote of a closed session
            q = {**q, "status": quality.PROXY if proxy else quality.HISTORICAL,
                 "label": quality.LABELS_CS[quality.PROXY if proxy else quality.HISTORICAL],
                 "text": f"{market.get('label', 'Trh zavřen').capitalize()} — poslední kotace {market_hours.prague(quote_t)}."}
    else:
        quote_t = dt.datetime.fromtimestamp(last, dt.timezone.utc)
        cal = market_hours.calendar_for(inst)
        if kind == "fixing_daily":  # ECB reference rates are set at 14:15 Frankfurt time
            from zoneinfo import ZoneInfo

            quote_t = dt.datetime(quote_t.year, quote_t.month, quote_t.day, 14, 15, tzinfo=ZoneInfo("Europe/Berlin")).astimezone(dt.timezone.utc)
            time_verified = True
        elif cal in CLOSE_TIME and kind == "index_daily":
            from zoneinfo import ZoneInfo

            (hh, mm), tz = CLOSE_TIME[cal]
            quote_t = dt.datetime(quote_t.year, quote_t.month, quote_t.day, hh, mm, tzinfo=ZoneInfo(tz)).astimezone(dt.timezone.utc)
            time_verified = True
        q = quality.classify(quote_t, now, rhythm, proxy=proxy)
    tradable = rhythm == "tick" and trading and q["status"] not in (quality.STALE,) and provider != "dukascopy"
    reference = kind in REFERENCE_KINDS
    if rhythm == "tick" or time_verified:
        time_cs = market_hours.prague(quote_t)
    elif rhythm == "monthly":
        time_cs = f"měsíc {quote_t.month}/{quote_t.year}"
    else:
        time_cs = f"hodnota k {quote_t.day}. {quote_t.month}. {quote_t.year} (čas zdroj neuvádí)"
    lq = {"price": last_price, "time": quote_t.isoformat(), "time_cs": time_cs,
          "age_minutes": round((now - quote_t).total_seconds() / 60), "tradable_now": tradable,
          "time_verified": time_verified, "reference": reference, "fetched_at": now.isoformat(),
          "timezone": "UTC (zobrazeno v čase Prahy SEČ/SELČ)",
          "kind_cs": universe.KIND_CS.get(kind, kind),
          "note": None if tradable else ("Referenční hodnota (fixing/průměr), ne cena trhu." if reference else
                                         "Denní hodnota, ne aktuální kotace." if rhythm != "tick" else
                                         "Kotace se zpožděním (~1 h), ne aktuální obchodovatelná cena." if provider == "dukascopy" else
                                         "Trh neobchoduje nebo zdroj stojí — poslední cena není aktuální kotace.")}
    return q, proxy, kind, lq


def _dukascopy_quality(inst, bars, tf_s, now, trading, market, proxy):
    """Dukascopy publishes ticks per hour about an hour late: the price is DELAYED with the exact time of
    the last tick (or of the last traded minute), STALE when the market is open but nothing new came."""
    from app.connectors import dukascopy
    from app.data import market_hours

    lt = dukascopy.last_tick(inst.code)
    if lt:
        quote_t, price, verified = dt.datetime.fromtimestamp(lt[0], dt.timezone.utc), lt[1], True
    else:
        quote_t, price, verified = dt.datetime.fromtimestamp(min(bars[-1][0] + tf_s, now.timestamp()), dt.timezone.utc), bars[-1][4], False
    when = market_hours.prague(quote_t)
    if trading and now - quote_t <= dt.timedelta(hours=3):
        status, text = quality.DELAYED, f"Kotace banky Dukascopy se zpožděním asi 1 h — poslední {when}."
    elif trading:
        status, text = quality.STALE, f"Trh je otevřený, ale poslední kotace Dukascopy je z {when} — zdroj teď nedodává."
    else:
        status, text = quality.HISTORICAL, f"{market.get('label', 'Trh zavřen').capitalize()} — poslední kotace {when}."
    q = {"status": status, "freshness": status, "label": quality.LABELS_CS[status], "as_of": quote_t.isoformat(),
         "age_hours": round((now - quote_t).total_seconds() / 3600, 1), "text": text}
    return q, quote_t, verified, price


def _ordered_feeds(inst: universe.Instrument, tf: str) -> list[tuple[str, str]]:
    """Broker feeds first; for daily and longer frames an official daily reference beats a proxy."""
    feeds = list(inst.feeds)
    if tf in ("D1", "W1", "MN1"):
        feeds.sort(key=lambda f: 0 if f[0] in ("mt5", "oanda") else 1 if f[0] in DAILY_ONLY else 2)
    preferred = (settings_store.get("preferred_feeds", {}) or {}).get(inst.code)
    if preferred:  # the user's choice goes first; the others stay as fallbacks (each keeps its own history)
        feeds.sort(key=lambda f: 0 if f[0] == preferred else 1)
    return feeds


def get_bars(code: str, tf: str, now: dt.datetime | None = None, store: bool = True) -> BarSet:
    inst = universe.get(code)
    if inst is None:
        return BarSet(code, tf, [], notes=[f"Instrument {code} FTI nezná."], quality=quality.classify(None, now or _now(), "daily"))
    if tf not in TF_MINUTES:
        return BarSet(code, tf, [], notes=[f"Timeframe {tf} není podporovaný."], quality=quality.classify(None, now or _now(), "daily"))
    now = now or _now()
    tried: list[dict] = []
    for provider, symbol in _ordered_feeds(inst, tf):
        if tf not in SUPPORTED_TF.get(provider, (tf,)):
            # the provider does not offer this timeframe at all: noted for the user, never counted as its error
            tried.append({"provider": provider, "name": FEED_NAME.get(provider, provider), "error": _unsupported_text(provider, tf),
                          "unsupported": True})
            health.unsupported(f"feed:{provider}", FEED_NAME.get(provider, provider), tf)
            continue
        key = (code, provider, symbol, tf)
        t0 = time.monotonic()
        try:
            bars, meta = _cached(key, TTL[tf], lambda p=provider, s=symbol: _fetch(p, s, tf, inst, now))
        except FeedError as exc:
            tried.append({"provider": provider, "name": FEED_NAME.get(provider, provider), "error": str(exc)})
            if isinstance(exc, FeedRejected):
                health.record(f"feed:{provider}", FEED_NAME.get(provider, provider), ok=False, error=str(exc), kind="rejected")
            elif not isinstance(exc, FeedPending) and (provider not in ("mt5", "oanda") or "není" not in str(exc)):
                health.record(f"feed:{provider}", FEED_NAME.get(provider, provider), ok=False, error=str(exc))  # a real outage
            continue
        except Exception as exc:  # noqa: BLE001 — an unexpected source failure is reported, never hidden
            log.exception("feed %s %s %s failed", provider, symbol, tf)
            tried.append({"provider": provider, "name": FEED_NAME.get(provider, provider), "error": f"chyba: {exc}"})
            health.record(f"feed:{provider}", FEED_NAME.get(provider, provider), ok=False, error=str(exc))
            continue
        ms = (time.monotonic() - t0) * 1000
        bars, dropped = validate(bars)
        if not bars:
            tried.append({"provider": provider, "name": FEED_NAME[provider], "error": "zdroj vrátil jen neplatné svíčky"})
            health.record(f"feed:{provider}", FEED_NAME[provider], ok=False, error="zdroj vrátil jen neplatné svíčky", kind="rejected")
            continue
        from app.data import market_hours

        mstate = market_hours.state(inst, now)
        q, proxy, kind, lq = _quality(provider, inst, bars, tf, now, mstate, symbol)
        health.record(f"feed:{provider}", FEED_NAME[provider], ok=True, ms=ms, records=len(bars),
                      data_as_of=dt.datetime.fromtimestamp(bars[-1][0], dt.timezone.utc).isoformat(),
                      quality=q.get("status"), expected=EXPECTED_QUALITY.get(provider, quality.LIVE))
        ident = feed_identity(provider, inst)
        notes = []
        if dropped:
            notes.append(f"Vyřazeno {dropped} neplatných svíček.")
        if ident["why"]:
            notes.append(ident["why"])
        if provider in DAILY_ONLY and provider not in ("nbp", "ecb"):
            notes.append(f"{FEED_NAME[provider]}: jen denní hodnoty (bez maxima a minima dne), intradenní rámce nejsou k dispozici.")
        if inst.itype == "cfd":
            notes.extend(inst.notes)
        if provider == "dukascopy":
            cov = meta.get("coverage") or {}
            if cov.get("pct") is not None:
                notes.append(f"Úplnost minutových dat Dukascopy za {cov['days']} obchodních dní: {cov['pct']} % "
                             f"({cov['missing']} minut chybí, nejdelší mezera {cov['longest_gap_min']} min) — chybějící se nedoplňují.")
            if meta.get("missing_files"):
                notes.append(f"Historie se ještě doplňuje: chybí {meta['missing_files']} souborů (stahují se postupně).")
            if meta.get("volume_note"):
                notes.append(meta["volume_note"])
        source = FEED_NAME[provider] + (f" · {meta.get('broker')} {meta.get('symbol')}" if provider in ("mt5", "oanda") else
                                        f" · {meta.get('symbol') or symbol}")
        bs = BarSet(code, tf, bars, provider, meta.get("symbol") or symbol, source, kind, proxy, provider in DAILY_ONLY, q,
                    notes, tried, meta, mstate, lq)
        if store and _first_use(key):
            _store(bs)
        return bs
    q = quality.classify(None, now, "daily")
    reasons = "; ".join(f"{t['name']}: {t['error']}" for t in tried) or "žádný zdroj"
    notes = [f"Pro {inst.symbol} {tf} teď není žádný zdroj dat ({reasons})."]
    notes += list(inst.notes)
    from app.data import market_hours

    return BarSet(code, tf, [], quality=q, notes=notes, tried=tried, market=market_hours.state(inst, now))


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _store(bs: BarSet) -> None:
    """Keep the bars (closed ones are final; the forming bar is overwritten next time)."""
    try:
        from app.data import store

        meta = bs.meta or {}
        origin = (f"{meta.get('broker')} / {meta.get('server')}" if bs.provider in ("mt5", "oanda") and meta.get("broker")
                  else FEED_NAME.get(bs.provider or "", bs.provider or ""))
        extra = {"complete_until": meta["complete_until"]} if meta.get("complete_until") else {}  # a delayed source's data edge
        store.save_bars(bs.code, bs.tf, bs.bars, bs.provider or "",
                        meta={"feed_symbol": bs.feed_symbol, "quality": (bs.quality or {}).get("status"), "origin": origin, **extra})
    except Exception:  # noqa: BLE001 — storing history must never break a chart
        log.exception("storing bars failed")


# Feeds whose history FTI keeps even while another feed of the instrument is shown first (every provider has its own
# history, ETAPA 1). get_bars() asks Dukascopy only when MT5 and OANDA fail, so without this its history stayed empty —
# and Dukascopy is the one XAUUSD feed that also works without the PC (MT5 runs only on Windows).
COLLECT = {"XAUUSD": ("dukascopy", ("D1", "H4", "H1", "M15", "M5", "M1"))}


def collect_history(now: dt.datetime | None = None) -> dict:
    """Store the COLLECT feeds' bars, whatever feed is shown. All timeframes share one download budget per run
    (Dukascopy: a few new files, a growing pause after a failure); finished files come from the disk cache.
    Missing files stay missing — gaps are reported by store.gaps(), never filled."""
    from app.connectors import dukascopy
    from app.data import store

    now = now or _now()
    budget = [dukascopy.NEW_FILES_PER_CALL]
    report: dict = {}
    for code, (provider, tfs) in COLLECT.items():
        inst = universe.get(code)
        symbol = dict(inst.feeds).get(provider) if inst else None
        if not symbol:
            continue
        for tf in tfs:
            sec = 86400 if tf == "D1" else TF_MINUTES[tf] * 60
            t0 = time.monotonic()
            try:
                got, meta = dukascopy.bars(symbol, sec, DUKASCOPY_DAYS[tf], now, budget=budget)
            except dukascopy.DukascopyUnavailable as exc:
                health.record(f"feed:{provider}", FEED_NAME[provider], ok=False, error=str(exc))
                report[f"{code} {tf}"] = {"error": str(exc)}
                continue
            ms = (time.monotonic() - t0) * 1000
            if not got:
                continue
            from app.data import market_hours

            mstate = market_hours.state(inst, now)
            q = _dukascopy_quality(inst, got, sec, now, mstate.get("state") == market_hours.OPEN, mstate, False)[0]
            sets = [(tf, got)] + ([("W1", dukascopy.keep_whole(resample(got, "W1"), 7 * 86400, meta.get("covered") or []))]
                                  if tf == "D1" else [])
            for tf_out, rows in sets:
                rows, dropped = validate(rows)
                stored = store.save_bars(code, tf_out, rows, provider, meta={
                    "feed_symbol": symbol, "quality": q["status"], "origin": FEED_NAME[provider],
                    "complete_until": meta.get("complete_until")})
                report[f"{code} {tf_out}"] = {"bars": stored, "dropped": dropped, "missing_files": meta.get("missing_files"),
                                              "complete_until": meta.get("complete_until"), "outage": meta.get("outage")}
            health.record(f"feed:{provider}", FEED_NAME[provider], ok=True, ms=ms, records=len(got),
                          data_as_of=dt.datetime.fromtimestamp(got[-1][0], dt.timezone.utc).isoformat(),
                          quality=q["status"], expected=EXPECTED_QUALITY.get(provider, quality.LIVE))
    return report


def to_candles(bs: BarSet):
    """BarSet → the Candle objects of the older modules (mtf, technical, dxy)."""
    from app.connectors.kraken import Candle

    return [Candle(dt.datetime.fromtimestamp(b[0], dt.timezone.utc), b[1], b[2], b[3], b[4]) for b in bs.bars]
