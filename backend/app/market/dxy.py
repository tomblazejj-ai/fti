"""DXY (US Dollar Index) — rebuilt from its official ICE formula, and its
correlation with gold. DXY matters here only as gold's main counter-weight.

    DXY = 50.14348112 × EURUSD^−0.576 × USDJPY^0.136 × GBPUSD^−0.119
                      × USDCAD^0.091 × USDSEK^0.042 × USDCHF^0.036

ICE's own DXY feed is not free. Inputs instead:
  - EUR/USD, GBP/USD, USD/CAD, USD/CHF: Kraken public OHLC (live, M15…W1)
  - USD/JPY, USD/SEK: official ECB daily reference rates (Kraken's yen book
    is too thin — 25 trades a day; SEK is not on Kraken). Together 17,8 % of
    the index, so intraday DXY ignores the yen's intraday move — stated in UI.
Checked live 2026-10-02 21:29 CEST: replica 101,90 vs. ICE DXY 101,92 (−0,02 %).

Candle high/low are bounds: every component at its dollar-strongest (high)
or dollar-weakest (low) point of the bar — they rarely coincide exactly.
Kraken's FX books print stray trades far outside the market (GBP/USD "high"
1,70 on 2026-09-23, EUR/USD wicks of 2 % in four hours), so each pair's wick
is first clamped to 3× its typical bar body (see `clean_wicks`). Opens and
closes are not touched — those matched the official DXY within 0,02 %.
"""

from __future__ import annotations

import datetime as dt
import statistics
import time
from collections.abc import Callable

import httpx

from app.connectors import kraken
from app.connectors.kraken import Candle
from app.market import mtf

CONST = 50.14348112
# Kraken pair -> (exponent, quoted as USD per foreign unit?)
LIVE_PARTS = {"EURUSD": -0.576, "GBPUSD": -0.119, "USDCAD": 0.091, "USDCHF": 0.036}
EXP_JPY, EXP_SEK = 0.136, 0.042
VERIFIED = "Ověřeno 2. 10. 2026 21:29: přepočet 101,90 vs. oficiální ICE DXY 101,92 (rozdíl 0,02 %)."


def dxy_value(eurusd: float, usdjpy: float, gbpusd: float, usdcad: float, usdsek: float, usdchf: float) -> float:
    return CONST * eurusd ** -0.576 * usdjpy ** 0.136 * gbpusd ** -0.119 * usdcad ** 0.091 * usdsek ** 0.042 * usdchf ** 0.036


def ecb_usd_crosses(day_rates: dict[str, float]) -> dict[str, float]:
    """ECB gives units per 1 EUR; turn them into the six DXY quotes."""
    usd = day_rates["USD"]
    return {"EURUSD": usd, "USDJPY": day_rates["JPY"] / usd, "GBPUSD": usd / day_rates["GBP"],
            "USDCAD": day_rates["CAD"] / usd, "USDSEK": day_rates["SEK"] / usd, "USDCHF": day_rates["CHF"] / usd}


def daily_from_ecb(ecb: dict[str, dict[str, float]]) -> list[tuple[str, float]]:
    out = []
    for d in sorted(ecb):
        q = ecb_usd_crosses(ecb[d])
        out.append((d, dxy_value(q["EURUSD"], q["USDJPY"], q["GBPUSD"], q["USDCAD"], q["USDSEK"], q["USDCHF"])))
    return out


class _JpySek:
    """USD/JPY and USD/SEK for any moment: the latest ECB fixing on or before that date."""

    def __init__(self, ecb: dict[str, dict[str, float]]):
        self.days = sorted(ecb)
        self.q = {d: ecb_usd_crosses(ecb[d]) for d in self.days[-900:]}
        self.keys = sorted(self.q)

    def at(self, day: str) -> tuple[float, float]:
        lo, hi = 0, len(self.keys) - 1
        best = self.keys[0]
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.keys[mid] <= day:
                best, lo = self.keys[mid], mid + 1
            else:
                hi = mid - 1
        q = self.q[best]
        return q["USDJPY"], q["USDSEK"]


WICK_FACTOR = 3.0
MIN_WICK = 0.0002  # 0,02 % — flat bars still get a hairline wick


def clean_wicks(candles: list[Candle]) -> list[Candle]:
    """Clamp each bar's high/low to WICK_FACTOR × the pair's median body size."""
    if not candles:
        return candles
    bodies = sorted(abs(c.close - c.open) / c.open for c in candles if c.open)
    allowed = max(MIN_WICK, WICK_FACTOR * bodies[len(bodies) // 2]) if bodies else MIN_WICK
    out = []
    for c in candles:
        top, bot = max(c.open, c.close), min(c.open, c.close)
        out.append(Candle(c.time, c.open, min(c.high, top * (1 + allowed)), max(c.low, bot * (1 - allowed)), c.close))
    return out


def combine(parts: dict[str, list[Candle]], fixings: _JpySek) -> list[Candle]:
    """One DXY candle per timestamp present in all four Kraken pairs."""
    maps = {p: {c.time: c for c in clean_wicks(cs)} for p, cs in parts.items()}
    common = sorted(set.intersection(*(set(m) for m in maps.values())))
    out = []
    for t in common:
        jpy, sek = fixings.at(t.date().isoformat())
        fixed = CONST * jpy ** EXP_JPY * sek ** EXP_SEK

        def val(pick: Callable[[str, Candle], float]) -> float:
            v = fixed
            for p, e in LIVE_PARTS.items():
                v *= pick(p, maps[p][t]) ** e
            return v

        # dollar-strongest = USD-quoted pairs high, foreign-quoted pairs low
        o = val(lambda p, c: c.open)
        cl = val(lambda p, c: c.close)
        hi = val(lambda p, c: c.high if p.startswith("USD") else c.low)
        lo = val(lambda p, c: c.low if p.startswith("USD") else c.high)
        out.append(Candle(t, o, max(hi, o, cl), min(lo, o, cl), cl))
    return out


def fetch_candles(fixings: _JpySek, timeframes: dict[str, int], client: httpx.Client | None = None,
                  sleep_fn=time.sleep) -> tuple[dict[str, list[Candle]], list[str]]:
    owns = client is None
    client = client or httpx.Client(timeout=20.0, headers={"User-Agent": kraken.USER_AGENT})
    out: dict[str, list[Candle]] = {}
    errors: list[str] = []
    first = True
    try:
        for label, minutes in timeframes.items():
            parts: dict[str, list[Candle]] = {}
            for pair in LIVE_PARTS:
                if not first:
                    sleep_fn(kraken.SECONDS_BETWEEN_REQUESTS)
                first = False
                try:
                    parts[pair] = kraken.fetch_ohlc(minutes, client, pair=pair)
                except kraken.KrakenUnavailableError as exc:
                    errors.append(f"DXY {label}: {exc}")
                    break
            if len(parts) == len(LIVE_PARTS):
                out[label] = combine(parts, fixings)
        return out, errors
    finally:
        if owns:
            client.close()


def _returns(closes: list[float]) -> list[float]:
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]


def _corr(a: list[float], b: list[float]) -> float | None:
    if len(a) < 10 or len(a) != len(b):
        return None
    try:
        return round(statistics.correlation(a, b), 2)
    except statistics.StatisticsError:
        return None


def correlation(gold: list[Candle], dollar: list[Candle], window: int) -> tuple[float | None, float | None, int]:
    """Correlation and beta of bar-to-bar returns over the last `window` common bars."""
    g = {c.time: c.close for c in gold}
    d = {c.time: c.close for c in dollar}
    common = sorted(set(g) & set(d))[-(window + 1):]
    if len(common) < 12:
        return None, None, 0
    rg, rd = _returns([g[t] for t in common]), _returns([d[t] for t in common])
    corr = _corr(rg, rd)
    var = statistics.pvariance(rd)
    beta = round(statistics.covariance(rg, rd) / var, 2) if var else None
    return corr, beta, len(rg)


def _num(v: float, digits: int, signed: bool = False) -> str:
    return (f"{v:+.{digits}f}" if signed else f"{v:.{digits}f}").replace(".", ",").replace("-", "−")


def _together(c: float) -> str:
    a = abs(c)
    if a < 0.15:
        return "téměř nezávisle"
    how = "silně" if a >= 0.6 else "středně" if a >= 0.35 else "slabě"
    return f"{how} proti sobě" if c < 0 else f"{how} spolu"


def _strength(c: float | None) -> str:
    if c is None:
        return "nelze spočítat"
    a = abs(c)
    word = "silná" if a >= 0.6 else "střední" if a >= 0.35 else "slabá" if a >= 0.15 else "téměř žádná"
    return f"{word} {'opačná' if c < 0 else 'souběžná'}" if a >= 0.15 else word


def analyze(gold_candles: dict[str, list[Candle]], dxy_candles: dict[str, list[Candle]], live_price: float | None = None,
            ecb_date: str | None = None) -> dict | None:
    if not dxy_candles:
        return None
    trends = mtf.analyze_all(dxy_candles, unit="")
    corr = {}
    for key, tf, window in (("d20", "D1", 20), ("d60", "D1", 60), ("d250", "D1", 250), ("h1", "H1", 120)):
        if tf in gold_candles and tf in dxy_candles:
            c, beta, n = correlation(gold_candles[tf], dxy_candles[tf], window)
            corr[key] = {"value": c, "beta": beta, "bars": n, "label": _strength(c)}
    d60 = (corr.get("d60") or {}).get("value")
    beta60 = (corr.get("d60") or {}).get("beta")

    # overlay chart: last 120 common daily closes of both, as % from the first one
    g = {c.time.date().isoformat(): c.close for c in gold_candles.get("D1", [])}
    d = {c.time.date().isoformat(): c.close for c in dxy_candles.get("D1", [])}
    days = sorted(set(g) & set(d))[-120:]
    overlay = [{"date": day, "gold": round((g[day] / g[days[0]] - 1) * 100, 2), "dxy": round((d[day] / d[days[0]] - 1) * 100, 2)}
               for day in days] if days else []

    swing, intraday = trends.get("swing"), trends.get("intraday")
    price = live_price or trends.get("price")
    lines = []
    if swing:
        lines.append(f"Dolar (DXY) je swingově {swing['word'].lower()}" + (f", intradenně {intraday['word'].lower()}." if intraday else "."))
    if d60 is not None:
        lines.append(f"Za posledních 60 dní chodí zlato a dolar {_together(d60)} (korelace {_num(d60, 2, True)}).")
        if beta60 is not None and d60 <= -0.15:
            lines.append(f"Když dolar posílí o 1 %, zlato v průměru {'klesne' if beta60 < 0 else 'stoupne'} o {_num(abs(beta60), 1)} %.")
    effect = 0.0
    if swing and d60 is not None and d60 <= -0.15:
        effect = -swing["score"] * min(1.0, abs(d60) / 0.6)  # strong dollar + inverse link = pressure on gold
        if swing["lean"] == "up":
            lines.append("Posilující dolar teď na zlato tlačí dolů.")
        elif swing["lean"] == "down":
            lines.append("Slábnoucí dolar teď zlatu pomáhá.")
        else:
            lines.append("Dolar teď nemá jasný směr — na zlato netlačí.")
    elif d60 is not None:
        lines.append("Zlato se teď od dolaru odpojilo — pohyb dolaru ho moc neřídí.")

    h4 = next((t for t in trends["timeframes"] if t["tf"] == "H4"), None)
    return {
        "price": round(price, 3) if price else None,
        "trends": trends,
        "correlation": corr,
        "effect_on_gold": round(effect, 2),
        "text": " ".join(lines),
        "overlay": overlay,
        "levels": {"swing_high": h4["swing_high"] if h4 else None, "swing_low": h4["swing_low"] if h4 else None},
        "source": ("Přepočet podle oficiálního vzorce ICE: EUR, GBP, CAD, CHF živě z Krakenu, JPY a SEK z denního fixingu ECB "
                   "(intradenní pohyb jenu se proto nepromítá)."),
        "verified": VERIFIED,
        "ecb_date": ecb_date,
    }


def live_quote(tickers: dict[str, float], fixings: _JpySek, today: str) -> float | None:
    """DXY now from Kraken last prices + ECB JPY/SEK."""
    if not all(p in tickers for p in LIVE_PARTS):
        return None
    jpy, sek = fixings.at(today)
    return dxy_value(tickers["EURUSD"], jpy, tickers["GBPUSD"], tickers["USDCAD"], sek, tickers["USDCHF"])


# --- Funded Mind, "DXY a jeho vliv": key levels as the bias, trend as the filter, mirror zones with gold
WEIGHTS = [  # ICE US Dollar Index basket (fixed since 1999)
    {"code": "EUR", "name": "Euro", "weight": 57.6},
    {"code": "JPY", "name": "Japonský jen", "weight": 13.6},
    {"code": "GBP", "name": "Britská libra", "weight": 11.9},
    {"code": "CAD", "name": "Kanadský dolar", "weight": 9.1},
    {"code": "SEK", "name": "Švédská koruna", "weight": 4.2},
    {"code": "CHF", "name": "Švýcarský frank", "weight": 3.6},
]
GOLD_NEAR_PCT = 0.8  # gold "at a level" — about half of its usual daily range
DXY_NEAR_PCT = 0.35  # the dollar index moves roughly 2–3× less than gold


def _at_level(tech: dict, lim: float) -> tuple[str, dict] | None:
    """("support" | "resistance", level) when the price sits within `lim` % of its nearest level."""
    near = [(kind, tech[key][0]) for kind, key in (("support", "supports"), ("resistance", "resistances")) if tech[key]]
    if not near:
        return None
    kind, lv = min(near, key=lambda x: abs(x[1]["pct"]))
    return (kind, lv) if abs(lv["pct"]) <= lim else None


def levels_view(dxy_tech: dict | None, trends: dict | None) -> dict | None:
    """Key daily levels of the DXY and what they mean for gold."""
    if not dxy_tech:
        return None
    sup = dxy_tech["supports"][0] if dxy_tech["supports"] else None
    res = dxy_tech["resistances"][0] if dxy_tech["resistances"] else None
    swing = (trends or {}).get("swing") or {}
    lean = swing.get("lean")
    parts = []
    if sup:
        parts.append(f"nejbližší support {_num(sup['price'], 2)} ({_num(sup['pct'], 1, True)} %)")
    if res:
        parts.append(f"rezistence {_num(res['price'], 2)} ({_num(res['pct'], 1, True)} %)")
    text = ("DXY: " + ", ".join(parts) + ".") if parts else ""
    if lean == "up":
        filt = "Swingový trend dolaru roste — pro zlato hledej spíš shorty, longy jen s potvrzením."
    elif lean == "down":
        filt = "Swingový trend dolaru klesá — pro zlato hledej spíš longy, shorty jen s potvrzením."
    else:
        filt = "Dolar je swingově bez jasného trendu — jako filtr pro zlato teď nerozhoduje."
    return {"supports": dxy_tech["supports"], "resistances": dxy_tech["resistances"], "text": text, "filter": filt,
            "trend": swing.get("word")}


def mirror(gold_tech: dict | None, dxy_tech: dict | None, corr60: float | None) -> dict | None:
    """"Zrcadlové zóny": gold at resistance while the dollar sits on support (and vice versa)
    makes a reaction at the gold level more likely — if the two still move against each other."""
    if not gold_tech or not dxy_tech:
        return None
    g, d = _at_level(gold_tech, GOLD_NEAR_PCT), _at_level(dxy_tech, DXY_NEAR_PCT)
    g_kind, d_kind = (g[0] if g else None), (d[0] if d else None)
    if g_kind == "resistance" and d_kind == "support":
        state, text = "short", ("Zrcadlo: zlato je u rezistence a dolar u supportu. Když se dolar od supportu odrazí nahoru, "
                                "má zlato důvod od rezistence klesnout — silnější argument pro short zlata.")
    elif g_kind == "support" and d_kind == "resistance":
        state, text = "long", ("Zrcadlo: zlato je u supportu a dolar u rezistence. Když dolar od rezistence obrátí dolů, "
                               "má zlato důvod se od supportu odrazit — silnější argument pro long zlata.")
    elif g_kind and g_kind == d_kind:
        state, text = "conflict", ("Zlato i dolar stojí u stejného typu úrovně — zrcadlo nesedí, "
                                   "jeden z nich pravděpodobně úroveň prorazí. Počkej na reakci.")
    else:
        state, text = "none", "Zlato a dolar teď nestojí současně u klíčových úrovní — zrcadlový signál není."
    linked = corr60 is not None and corr60 <= -0.15
    if state in ("short", "long") and not linked:
        text += " Pozor: zlato se teď od dolaru odpojilo (slabá korelace), ber to jen orientačně."
    def pick(t: dict) -> dict:
        return {"support": t["supports"][0] if t["supports"] else None,
                "resistance": t["resistances"][0] if t["resistances"] else None}
    return {"state": state, "text": text, "linked": linked, "gold": pick(gold_tech), "dxy": pick(dxy_tech),
            "gold_at": g_kind, "dxy_at": d_kind, "near_pct": {"gold": GOLD_NEAR_PCT, "dxy": DXY_NEAR_PCT}}
