"""TickBase Market Data API (thetickbase.com) — an independent CHECK and BACKUP of the current gold price.

Role in FTI (user's decision 2026-11-08): Dukascopy stays the main source of candles. TickBase only
  * checks the current XAU/USD price against Dukascopy in the same minute; a disagreement is shown, never averaged away;
  * stands in for the current price when no candle feed delivers XAUUSD, labelled with TickBase's own quote time;
    it is never turned into candles and never shown as live when it is old.

Verified 8. 11. 2026 in the official docs (thetickbase.com/docs, terms of 21. 5. 2026) and with real requests:
  * prices need a key ("tb_live_…", header Authorization: Bearer) from a free account; /v1/status and /v1/symbols are
    public and need no key;
  * free plan: 5 000 requests a month, 30 a minute, 30 days of history, 1 key; OHLC and time series are paid, never used;
  * /v1/metals/latest?metal=XAU → metal, currency, price, bid, ask, as_of (ISO UTC), derived; /v1/symbols lists XAU only;
  * the terms forbid sharing "raw API responses" → FTI keeps its own comparison and shows the price only on this PC
    (the public cloud export gets the result of the check, not TickBase's price).

FTI's own budget: at most one price request per MIN_INTERVAL_S and MONTHLY_CAP a month per installation (PC and cloud
on one key stay under the free 5 000). The key never leaves the backend and never appears in an error text.
"""

from __future__ import annotations

import datetime as dt
import os
import threading
import time

import httpx

from app.data import health, market_hours, quality, secrets, universe

BASE = "https://api.thetickbase.com/v1"
KEY = "TICKBASE_API_KEY"
FREE_MONTHLY = 5000
MONTHLY_CAP = 2400
MIN_INTERVAL_S = 15 * 60
FRESH_S, DELAYED_S = 300, 900  # TickBase's own status page: fresh < 5 min, delayed < 15 min
MATCH_PCT, WARN_PCT = 0.05, 0.15  # |difference| to Dukascopy: ≤ 0.05 % agrees (~2 $ at 4 000 $), > 0.15 % disagrees
NEAR_S = 120  # a Dukascopy minute at most this far from TickBase's quote time counts as the same moment
MAX_SPREAD_PCT = 0.1  # gold spot bid/ask is ~0.01 %; TickBase answered 1.5 % on 8. 11. 2026 — not a market quote
TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}
MAX_AGE_CLOSED = dt.timedelta(days=4)  # no gold market is shut longer (a long weekend with a holiday)
USER_AGENT = "FTI/1.0 (personal analysis)"
HEALTH_KEY, HEALTH_NAME = "feed:tickbase", "TickBase (kontrola a záloha ceny zlata)"
ROLE_CS = "kontrolní a záložní zdroj aktuální ceny zlata — hlavním zdrojem svíček zůstává Dukascopy"
USAGE_KEY = "tickbase:usage"
CHECK_KEY = "tickbase:check"
METALS = {"XAUUSD": "XAU"}

_transport: httpx.BaseTransport | None = None  # tests inject a mock
_lock = threading.Lock()
_mem: dict[str, tuple[float, dict]] = {}  # metal -> (monotonic time, last good price answer)
_feed: dict[str, tuple[float, dict]] = {}  # metal -> (monotonic time, verdict of the PUBLIC status: may prices be asked?)
FEED_TTL_S = 30 * 60  # the public status is asked again after this (it costs no quota)


class TickBaseError(RuntimeError):
    code = "unavailable"


class TickBaseNoKey(TickBaseError):
    code = "no_key"


class TickBaseKeyRejected(TickBaseError):
    code = "invalid_key"


class TickBaseLimit(TickBaseError):
    code = "limit"


class TickBaseBudget(TickBaseError):
    code = "budget"


def public_export() -> bool:
    """True in the cloud run, whose results anyone with the link can read — TickBase's price stays out of it."""
    return os.environ.get("FTI_PUBLIC_EXPORT") == "1"


def _get(path: str, params: dict | None = None, key: str | None = None) -> tuple[dict, float, dict]:
    """(body, milliseconds, the rate-limit / quota headers TickBase sent). Never puts the key into an error text."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=15.0, transport=_transport, headers=headers) as c:
            r = c.get(BASE + path, params=params or {})
    except httpx.HTTPError as exc:
        raise TickBaseError(f"TickBase neodpověděl ({type(exc).__name__}).") from exc
    ms = (time.monotonic() - t0) * 1000
    try:
        body = r.json()
    except ValueError:
        body = {}
    limits = {k.lower(): v for k, v in r.headers.items() if any(w in k.lower() for w in ("ratelimit", "rate-limit", "quota", "retry-after"))}
    if r.status_code == 200 and isinstance(body, dict) and "error" not in body:
        return body, ms, limits
    err = body.get("error") if isinstance(body, dict) and isinstance(body.get("error"), dict) else {}
    text = f"TickBase: HTTP {r.status_code} {err.get('code') or ''}".rstrip()
    if r.status_code == 401:
        raise TickBaseKeyRejected(f"{text} — klíč {KEY} TickBase nepřijal.")
    if r.status_code == 429:
        raise TickBaseLimit(f"{text} — vyčerpaný limit dotazů.")
    raise TickBaseError(f"{text}.")


def source_status() -> dict:
    """TickBase's public status (no key, no quota): {status, now, sources: [{asset, symbol, as_of, age_seconds, market_state}]}."""
    body, ms, _ = _get("/status")
    return {"status": body.get("status"), "now": body.get("now"), "sources": body.get("sources") or [], "ms": round(ms)}


def _metal_feed(st: dict, metal: str) -> dict | None:
    return next((s for s in st.get("sources") or [] if s.get("asset") == "metal" and (s.get("symbol") or metal) == metal), None)


def usage(month: str, session=None) -> int:
    from app.data import store

    payload, _ = store.cache_get(USAGE_KEY, session=session)
    return int(payload.get("count", 0)) if isinstance(payload, dict) and payload.get("month") == month else 0


def _count(month: str, session=None) -> int:
    from app.data import store

    n = usage(month, session) + 1
    store.cache_put(USAGE_KEY, {"month": month, "count": n, "cap": MONTHLY_CAP, "free": FREE_MONTHLY}, "tickbase", session=session)
    return n


def latest(metal: str = "XAU", now: dt.datetime | None = None, session=None) -> dict:
    """The current price with TickBase's own quote time. At most one request per MIN_INTERVAL_S; raises TickBaseError."""
    key = secrets.get(KEY)
    if not key:
        raise TickBaseNoKey(f"Chybí klíč {KEY} (účet zdarma na thetickbase.com) — TickBase se nedotazuje.")
    with _lock:
        hit = _mem.get(metal)
        if hit and time.monotonic() - hit[0] < MIN_INTERVAL_S:
            return {**hit[1], "cached": True}
    now = now or dt.datetime.now(dt.timezone.utc)
    month = now.strftime("%Y-%m")
    if usage(month, session) >= MONTHLY_CAP:
        raise TickBaseBudget(f"Měsíční strop FTI {MONTHLY_CAP} dotazů na TickBase je vyčerpaný (zdarma {FREE_MONTHLY}).")
    used = _count(month, session)  # counted before the answer: a failed request uses the quota too
    body, ms, limits = _get("/metals/latest", {"metal": metal}, key)
    received = dt.datetime.now(dt.timezone.utc)  # when the answer really arrived
    try:
        price = float(body["price"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TickBaseError("TickBase vrátil odpověď bez ceny.") from exc
    as_of = quality.parse_time(body.get("as_of"))
    if body.get("metal") not in (None, metal) or price <= 0 or as_of is None:
        raise TickBaseError("TickBase vrátil neplatnou cenu nebo čas kotace.")
    if body.get("unit") not in (None, "troy_ounce") or (body.get("currency") or "USD") != "USD":
        raise TickBaseError(f"TickBase vrátil jinou jednotku nebo měnu ({body.get('unit')}, {body.get('currency')}) než USD za trojskou unci.")

    def num(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    data = {"metal": metal, "currency": body.get("currency") or "USD", "price": price, "bid": num(body.get("bid")),
            "ask": num(body.get("ask")), "as_of": as_of.isoformat(), "derived": body.get("derived"),
            "received_at": received.isoformat(), "ms": round(ms), "used_this_month": used, "limits": limits, "cached": False}
    with _lock:
        _mem[metal] = (time.monotonic(), data)
    return data


def clear() -> None:
    with _lock:
        _mem.clear()
        _feed.clear()


def _reference(as_of: dt.datetime, session=None, provider: str = "dukascopy") -> dict | None:
    """The provider's price at TickBase's quote time: the candle that contains it (open market) or the last trade before
    it (closed market, e.g. Friday's close for a weekend time). M1 first, coarser candles only when M1 is not stored."""
    from app.data import store

    ts = int(as_of.timestamp())
    closed = market_hours.state(universe.get("XAUUSD"), as_of).get("state") != market_hours.OPEN
    for tf, sec in TF_SECONDS.items():
        rows = store.load_bars("XAUUSD", tf, provider, since=ts - (4 * 86400 if closed else 2 * sec + NEAR_S), session=session)
        if closed:
            bar = ([r for r in rows if r[0] + sec <= ts + NEAR_S] or [None])[-1]
            how = f"poslední obchod před časem kotace, trh byl zavřený ({tf})"
        else:
            hits = [r for r in rows if r[0] - NEAR_S <= ts < r[0] + sec + NEAR_S]
            bar = min(hits, key=lambda r: abs(r[0] + sec - ts)) if hits else None
            how = "stejná minuta" if tf == "M1" else f"svíčka {tf}, která čas kotace obsahuje"
        if bar is not None:
            return {"provider": provider, "tf": tf, "t": dt.datetime.fromtimestamp(bar[0], dt.timezone.utc).isoformat(),
                    "end": dt.datetime.fromtimestamp(bar[0] + sec, dt.timezone.utc).isoformat(), "close": bar[4],
                    "low": bar[3], "high": bar[2], "price_type": "bid", "match": how}
    return None


def last_trading_moment(now: dt.datetime) -> dt.datetime | None:
    """When the gold market last traded, from FTI's market calendar (now when it is open) — needs no data feed, so it
    also works when Dukascopy is down."""
    inst = universe.get("XAUUSD")
    if market_hours.state(inst, now).get("state") == market_hours.OPEN:
        return now
    t = now.replace(second=0, microsecond=0) - dt.timedelta(minutes=now.minute % 15)
    for _ in range(4 * 24 * 4):  # 15-minute steps, at most 4 days back
        t -= dt.timedelta(minutes=15)
        if market_hours.state(inst, t).get("state") == market_hours.OPEN:
            return t + dt.timedelta(minutes=15)
    return None


def _last_trade(now: dt.datetime, session=None) -> dt.datetime | None:
    known = [t for t in (_last_dukascopy(session), last_trading_moment(now)) if t is not None]
    return max(known) if known else None


def spread_pct(q: dict) -> float | None:
    if q.get("bid") and q.get("ask") and q.get("price"):
        return round((q["ask"] - q["bid"]) / q["price"] * 100, 3)
    return None


def _last_dukascopy(session=None) -> dt.datetime | None:
    from app.data import store

    rows = store.load_bars("XAUUSD", "M1", "dukascopy", since=int(time.time()) - 14 * 86400, session=session)
    return dt.datetime.fromtimestamp(rows[-1][0] + 60, dt.timezone.utc) if rows else None


def freshness(as_of: dt.datetime, now: dt.datetime, market_open: bool, last_trade: dt.datetime | None) -> dict:
    """Is TickBase's quote as fresh as the market allows? Open: its own limits (5 / 15 min). Closed: it must be from
    the last trading minutes, not from an earlier day (a feed that stopped before the close is stale)."""
    age = (now - as_of).total_seconds()
    when = market_hours.prague(as_of)
    if market_open:
        if age <= FRESH_S:
            return {"status": quality.NRT, "text": f"Kotace TickBase z {when} (před {round(age / 60)} min)."}
        if age <= DELAYED_S:
            return {"status": quality.DELAYED, "text": f"Kotace TickBase se zpožděním {round(age / 60)} min ({when})."}
        return {"status": quality.STALE, "text": f"Trh je otevřený, ale poslední kotace TickBase je z {when} — zdroj stojí."}
    if last_trade is not None and as_of < last_trade - dt.timedelta(hours=1):
        return {"status": quality.STALE, "text": (f"Trh je zavřený. Poslední kotace TickBase je z {when}, ale trh obchodoval "
                                                  f"až do {market_hours.prague(last_trade)} — TickBase se zastavil dřív.")}
    if last_trade is None or now - as_of > MAX_AGE_CLOSED:  # fail closed: without proof of freshness it is stale
        return {"status": quality.STALE, "text": f"Kotace TickBase z {when} — čerstvost nejde ověřit, bere se jako zastaralá."}
    return {"status": quality.DELAYED, "text": f"Trh je zavřený — poslední kotace TickBase z {when}."}


def compare(price: float, ref: dict | None) -> dict:
    if ref is None:
        return {"state": "no_reference", "text": "Dukascopy nemá svíčku z času kotace TickBase — ceny teď nejde porovnat."}
    diff = price - ref["close"]
    pct = diff / ref["close"] * 100
    state = "match" if abs(pct) <= MATCH_PCT else "small" if abs(pct) <= WARN_PCT else "mismatch"
    word = {"match": "shoda", "small": "mírný rozdíl", "mismatch": "ROZPOR"}[state]
    name = {"dukascopy": "Dukascopy", "mt5": "broker MT5"}.get(ref.get("provider"), ref.get("provider", "Dukascopy"))
    text = f"TickBase vs. {name} ({ref.get('match', 'stejná minuta')}): {word} — rozdíl {diff:+.2f} USD ({pct:+.3f} %)."
    return {"state": state, "diff": round(diff, 2), "diff_pct": round(pct, 3), "reference": ref, "text": _cs(text)}


def _cs(text: str) -> str:
    """Czech decimal comma in the numbers of a sentence (the sentence's own full stops stay)."""
    import re

    return re.sub(r"(\d)\.(\d)", r"\1,\2", text)


def feed_gate(now: dt.datetime, session=None, st: dict | None = None) -> dict:
    """May FTI ask TickBase for a price? Decided from its PUBLIC status (no key, no quota): only when its gold feed is
    as fresh as the market allows. User's decision 8. 11. 2026: no price polling while the source has no current quotes.
    Remembered FEED_TTL_S; a failed status answer closes the gate (fail closed)."""
    with _lock:
        hit = _feed.get("XAU")
        if st is None and hit and time.monotonic() - hit[0] < FEED_TTL_S:
            return hit[1]
    try:
        st = st or source_status()
        feed = _metal_feed(st, "XAU")
        as_of = quality.parse_time(feed.get("as_of")) if feed else None
        if as_of is None:
            verdict = {"open": False, "as_of": None, "text": "Veřejný stav TickBase neuvádí čas dat zlata — dotazy na ceny jsou vypnuté."}
        else:
            is_open = market_hours.state(universe.get("XAUUSD"), now).get("state") == market_hours.OPEN
            fresh = freshness(as_of, now, is_open, _last_trade(now, session))
            verdict = {"open": fresh["status"] != quality.STALE, "as_of": as_of.isoformat(), "status": fresh["status"],
                       "text": fresh["text"] if fresh["status"] != quality.STALE else
                       f"Dotazy na ceny TickBase jsou vypnuté, dokud zdroj nemá aktuální data. {fresh['text']}"}
    except TickBaseError as exc:
        verdict = {"open": False, "as_of": None, "text": f"Stav TickBase nejde zjistit ({exc}) — dotazy na ceny jsou vypnuté."}
    with _lock:
        _feed["XAU"] = (time.monotonic(), verdict)
    return verdict


def check(now: dt.datetime | None = None, session=None) -> dict:
    """One check per data cycle: TickBase's public feed status, its XAU price and the comparison with Dukascopy.
    The result goes to the source health list ("Zdroje") and to the cache for the API; never raises."""
    from app.data import store

    now = now or dt.datetime.now(dt.timezone.utc)
    inst = universe.get("XAUUSD")
    is_open = market_hours.state(inst, now).get("state") == market_hours.OPEN
    out: dict = {"source": "TickBase", "role": ROLE_CS, "checked_at": now.isoformat(), "market_open": is_open,
                 "key_set": bool(secrets.get(KEY))}
    st = None
    try:
        st = source_status()
        feed = _metal_feed(st, "XAU")
        out["feed"] = {"service": st["status"], "as_of": feed.get("as_of") if feed else None,
                       "age_seconds": feed.get("age_seconds") if feed else None,
                       "market_state": feed.get("market_state") if feed else None}
    except TickBaseError as exc:
        out["feed_error"] = str(exc)
    last_trade = _last_trade(now, session)
    gate = feed_gate(now, session, st) if st is not None else feed_gate(now, session, {"sources": []})
    out["price_polling"] = "on" if gate["open"] else "paused"
    if not gate["open"]:  # availability is still watched, without spending the quota
        out.update(state="paused", text=gate["text"])
        health.record(HEALTH_KEY, HEALTH_NAME, ok=False, error=gate["text"], kind="rejected")
        store.cache_put(CHECK_KEY, out, "tickbase", session=session)
        return out
    try:
        q = latest("XAU", now, session)
    except TickBaseNoKey as exc:
        out.update(state="no_key", text=str(exc))
        store.cache_put(CHECK_KEY, out, "tickbase", session=session)
        return out
    except TickBaseError as exc:
        out.update(state=exc.code, text=str(exc))
        health.record(HEALTH_KEY, HEALTH_NAME, ok=False, error=str(exc))
        store.cache_put(CHECK_KEY, out, "tickbase", session=session)
        return out
    as_of = quality.parse_time(q["as_of"])
    fresh = freshness(as_of, now, is_open, last_trade)
    # TickBase's headline price against Dukascopy's bid (the bid/ask difference of real gold, ~0.3 USD, is far below
    # the limits); the broker's candle is a second opinion
    cmp = compare(q["price"], _reference(as_of, session))
    broker = compare(q["price"], _reference(as_of, session, "mt5"))
    spread = spread_pct(q)
    spread_ok = spread is None or spread <= MAX_SPREAD_PCT
    texts = [fresh["text"], cmp["text"]]
    if not spread_ok:
        texts.append(_cs(f"Rozpětí bid/ask TickBase je {spread:.2f} % ceny — skutečné zlato má kolem 0.01 %, není to tržní kotace."))
    out.update(state="ok", quote_as_of=q["as_of"], received_at=q["received_at"], used_this_month=q["used_this_month"],
               limits=q.get("limits"), cached=q["cached"], freshness=fresh, comparison=cmp, comparison_broker=broker,
               spread_pct=spread, spread_ok=spread_ok, text=" ".join(texts))
    if not public_export():
        out["quote"] = {k: q[k] for k in ("price", "bid", "ask", "currency")}
    bad = fresh["status"] == quality.STALE or cmp["state"] == "mismatch" or not spread_ok
    health.record(HEALTH_KEY, HEALTH_NAME, ok=not bad, ms=q["ms"], records=1, data_as_of=q["as_of"], quality=fresh["status"],
                  expected=quality.NRT, error=out["text"] if bad else None, kind="rejected")
    store.cache_put(CHECK_KEY, out, "tickbase", session=session)
    return out


def last_check(session=None) -> dict | None:
    from app.data import store

    payload, _ = store.cache_get(CHECK_KEY, session=session)
    return payload if isinstance(payload, dict) else None


def quote(code: str, now: dt.datetime | None = None) -> dict | None:
    """Backup current price in the shape of prices.quote() — only on this PC, only with a key, only when fresh enough
    to say something (never older than the market allows). None otherwise, and the next fallback is used."""
    metal = METALS.get(code)
    inst = universe.get(code)
    if metal is None or inst is None or public_export() or not secrets.get(KEY):
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    if not feed_gate(now)["open"]:  # the public status says the source has no current data: no price request at all
        return None
    try:
        q = latest(metal, now)
    except TickBaseError:
        return None
    market = market_hours.state(inst, now)
    is_open = market.get("state") == market_hours.OPEN
    as_of = quality.parse_time(q["as_of"])
    fresh = freshness(as_of, now, is_open, _last_trade(now))  # regression 8. 11. 2026: None here let a week-old price through
    sp = spread_pct(q)
    if fresh["status"] == quality.STALE or (sp is not None and sp > MAX_SPREAD_PCT):
        return None
    when = market_hours.prague(as_of)
    qual = {"status": fresh["status"], "freshness": fresh["status"], "label": quality.LABELS_CS[fresh["status"]],
            "as_of": q["as_of"], "age_hours": round((now - as_of).total_seconds() / 3600, 2), "text": fresh["text"]}
    last = {"price": q["price"], "time": q["as_of"], "time_cs": when, "received_at": q["received_at"],
            "fetched_at": q["received_at"], "age_minutes": round((now - as_of).total_seconds() / 60, 1),
            "tradable_now": False, "time_verified": True, "reference": False, "indicative": False,
            "kind_cs": "spotová cena (záložní zdroj TickBase)", "timezone": "UTC (zobrazeno v čase Prahy SEČ/SELČ)",
            "note": "Záložní cena TickBase s jeho časem kotace — ne obchodovatelná kotace brokera."}
    return {"code": inst.code, "symbol": inst.symbol, "name": inst.name, "digits": inst.digits if inst.digits < 4 else 4,
            "available": True, "price": q["price"], "change_pct": None, "itype": inst.itype,
            "itype_cs": universe.ITYPE_CS.get(inst.itype, inst.itype), "reference": False, "indicative": False,
            "source": "TickBase (záloha — Dukascopy ani broker teď cenu nedodávají)", "provider": "tickbase", "quality": qual,
            "market": market, "last_quote": last, "proxy": False, "kind_cs": "spotová cena (záloha)", "tf": None,
            "notes": ["Hlavní zdroj svíček (Dukascopy / MT5) teď cenu nedodává — zobrazuje se záložní cena TickBase."]}
