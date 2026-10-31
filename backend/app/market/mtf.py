"""Trend on several timeframes + one overall trend (intraday / swing / celkem).

Same recipe on every timeframe so they are comparable:
  - cena vs. EMA50                      (30 %)
  - EMA20 vs. EMA50 (uspořádání)        (30 %)
  - sklon EMA20 za 5 svíček, v ATR      (20 %)
  - struktura: vyšší/nižší maxima+minima (20 %)
Score −1…+1; ≥ 0,4 nahoru, ≤ −0,4 dolů, jinak do strany.
Strength from ADX(14): < 20 slabý, 20–25 střední, > 25 silný.
"""

from __future__ import annotations

from app.connectors.kraken import Candle
from app.market.technical import ema

TF_LABELS = {"M15": "15 minut", "H1": "1 hodina", "H4": "4 hodiny", "D1": "Den", "W1": "Týden"}
MIN_CANDLES = 60
CHART_BARS = 120

# Which timeframes make up each overall view, and how much each counts.
BLENDS = {
    "intraday": {"M15": 0.2, "H1": 0.35, "H4": 0.45},
    "swing": {"H4": 0.2, "D1": 0.5, "W1": 0.3},
    "overall": {"M15": 0.1, "H1": 0.15, "H4": 0.25, "D1": 0.3, "W1": 0.2},
}
BLEND_LABELS = {"intraday": "Intradenní trend", "swing": "Swingový trend", "overall": "Celkový trend"}
UP, DOWN = 0.4, -0.4
LEAN = 0.2  # a blend between ±0,2 and ±0,4 is reported as "spíše" (leaning), not a trend


def _direction(score: float) -> str:
    return "up" if score >= UP else "down" if score <= DOWN else "sideways"


def atr(c: list[Candle], n: int = 14) -> float | None:
    if len(c) <= n:
        return None
    trs = [max(c[i].high - c[i].low, abs(c[i].high - c[i - 1].close), abs(c[i].low - c[i - 1].close)) for i in range(1, len(c))]
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def adx(c: list[Candle], n: int = 14) -> float | None:
    if len(c) < 2 * n + 1:
        return None
    pdm, ndm, trs = [], [], []
    for i in range(1, len(c)):
        up, down = c[i].high - c[i - 1].high, c[i - 1].low - c[i].low
        pdm.append(up if up > down and up > 0 else 0.0)
        ndm.append(down if down > up and down > 0 else 0.0)
        trs.append(max(c[i].high - c[i].low, abs(c[i].high - c[i - 1].close), abs(c[i].low - c[i - 1].close)))

    def wilder(xs: list[float]) -> list[float]:
        s = sum(xs[:n])
        out = [s]
        for x in xs[n:]:
            s = s - s / n + x
            out.append(s)
        return out

    tr_s, p_s, n_s = wilder(trs), wilder(pdm), wilder(ndm)
    dxs = []
    for t, p, m in zip(tr_s, p_s, n_s):
        if t == 0:
            dxs.append(0.0)
            continue
        pdi, ndi = 100 * p / t, 100 * m / t
        dxs.append(0.0 if pdi + ndi == 0 else 100 * abs(pdi - ndi) / (pdi + ndi))
    if len(dxs) < n:
        return None
    a = sum(dxs[:n]) / n
    for d in dxs[n:]:
        a = (a * (n - 1) + d) / n
    return a


def swings(c: list[Candle], window: int = 3) -> tuple[list[float], list[float]]:
    """Confirmed swing highs/lows (a bar higher/lower than `window` bars each side)."""
    highs, lows = [], []
    for i in range(window, len(c) - window):
        seg = c[i - window:i + window + 1]
        if c[i].high == max(x.high for x in seg):
            highs.append(c[i].high)
        if c[i].low == min(x.low for x in seg):
            lows.append(c[i].low)
    return highs, lows


def _fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


def analyze_tf(label: str, candles: list[Candle]) -> dict | None:
    if len(candles) < MIN_CANDLES:
        return None
    closes = [x.close for x in candles]
    last = closes[-1]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    a = atr(candles) or 0.0
    strength_adx = adx(candles)

    above50 = last > e50[-1]
    stacked_up = e20[-1] > e50[-1]
    slope_atr = (e20[-1] - e20[-6]) / a if a else 0.0
    slope_sig = 1 if slope_atr > 0.3 else -1 if slope_atr < -0.3 else 0

    hs, ls = swings(candles)
    if len(hs) >= 2 and len(ls) >= 2:
        hh, hl = hs[-1] > hs[-2], ls[-1] > ls[-2]
        struct_sig = 1 if hh and hl else -1 if not hh and not hl else 0
        struct_text = {1: "vyšší maxima i minima", -1: "nižší maxima i minima", 0: "smíšená maxima a minima"}[struct_sig]
    else:
        struct_sig, struct_text = 0, "struktura zatím nečitelná"

    score = round(0.3 * (1 if above50 else -1) + 0.3 * (1 if stacked_up else -1) + 0.2 * slope_sig + 0.2 * struct_sig, 2)
    direction = _direction(score)
    if strength_adx is None:
        strength = "neznámá"
    else:
        strength = "silný" if strength_adx > 25 else "střední" if strength_adx >= 20 else "slabý"

    word = {"up": "Nahoru", "down": "Dolů", "sideways": "Do strany"}[direction]
    reasons = [
        f"cena {'nad' if above50 else 'pod'} EMA50",
        f"EMA20 {'nad' if stacked_up else 'pod'} EMA50",
        "EMA20 roste" if slope_sig > 0 else "EMA20 klesá" if slope_sig < 0 else "EMA20 plochá",
        struct_text,
    ]
    lookback = min(len(closes) - 1, 20)
    return {
        "tf": label,
        "tf_label": TF_LABELS[label],
        "direction": direction,
        "word": word,
        "score": score,
        "strength": strength,
        "adx": round(strength_adx, 1) if strength_adx is not None else None,
        "close": round(last, 2),
        "ema20": round(e20[-1], 2),
        "ema50": round(e50[-1], 2),
        "atr": round(a, 2),
        "change_pct": round((last / closes[-1 - lookback] - 1) * 100, 2),
        "change_bars": lookback,
        "swing_high": round(hs[-1], 2) if hs else None,
        "swing_low": round(ls[-1], 2) if ls else None,
        "text": (lambda t: t[0].upper() + t[1:])(", ".join(reasons)) + ".",
        "as_of": candles[-1].time.isoformat(),
        # for the chart: the last CHART_BARS candles with both averages
        "candles": [
            [int(c.time.timestamp()), round(c.open, 2), round(c.high, 2), round(c.low, 2), round(c.close, 2), round(f, 2), round(sl, 2)]
            for c, f, sl in zip(candles[-CHART_BARS:], e20[-CHART_BARS:], e50[-CHART_BARS:])
        ],
    }


def _blend(key: str, tfs: dict[str, dict]) -> dict | None:
    weights = {k: w for k, w in BLENDS[key].items() if k in tfs}
    if sum(weights.values()) < 0.5:  # most of the inputs missing → don't pretend
        return None
    total = sum(weights.values())
    score = round(sum(tfs[k]["score"] * w for k, w in weights.items()) / total, 2)
    direction = _direction(score)
    agree = [k for k in weights if tfs[k]["direction"] == direction]
    if direction == "sideways" and abs(score) >= LEAN:
        word = "Spíše nahoru" if score > 0 else "Spíše dolů"
    else:
        word = {"up": "Nahoru", "down": "Dolů", "sideways": "Do strany"}[direction]
    return {
        "key": key,
        "label": BLEND_LABELS[key],
        "direction": direction,
        "lean": "up" if score >= LEAN else "down" if score <= -LEAN else "sideways",
        "word": word,
        "score": score,
        "timeframes": list(weights),
        "agree": agree,
    }


def _advice(intraday: dict | None, swing: dict | None) -> str:
    if not intraday or not swing:
        return "Pro souhrn chybí část timeframů."
    i, s = intraday["direction"], swing["direction"]
    if i == s == "up":
        return "Krátkodobě i dlouhodobě nahoru — trendy jsou sladěné. Intradenně i swingově hledat nákupy na poklesech (k EMA20/EMA50)."
    if i == s == "down":
        return "Krátkodobě i dlouhodobě dolů — trendy jsou sladěné. Intradenně i swingově hledat prodeje na odrazech nahoru."
    if s == "down" and i == "up":
        return "Hlavní trend je dolů, intradenně jde o korekci nahoru. Swing: počkat, až korekce dojede, a prodávat. Intradenní long jen krátce a opatrně."
    if s == "up" and i == "down":
        return "Hlavní trend je nahoru, intradenně jde o korekci dolů. Swing: počkat na konec korekce a nakupovat. Intradenní short jen krátce a opatrně."
    if s == "sideways" and i != "sideways":
        return f"Dlouhodobě bez jasného směru, krátkodobě {'nahoru' if i == 'up' else 'dolů'}. Vhodnější je intradenní obchod; swing zatím bez výhody."
    if i == "sideways" and s != "sideways":
        return f"Swingový trend {'nahoru' if s == 'up' else 'dolů'}, intradenně trh odpočívá. Swing držet směr, intradenně počkat na výběh z pásma."
    return "Trh je na všech timeframech bez jasného směru — lepší počkat."


def analyze_all(candles_by_tf: dict[str, list[Candle]], unit: str = "$") -> dict:
    tfs: dict[str, dict] = {}
    for label, candles in candles_by_tf.items():
        res = analyze_tf(label, candles)
        if res:
            tfs[label] = res
    order = [k for k in ("M15", "H1", "H4", "D1", "W1") if k in tfs]
    blends = {k: _blend(k, tfs) for k in BLENDS}
    price = tfs[order[0]]["close"] if order else None
    price_time = tfs[order[0]]["as_of"] if order else None
    return {
        "timeframes": [tfs[k] for k in order],
        "intraday": blends["intraday"],
        "swing": blends["swing"],
        "overall": blends["overall"],
        "advice": _advice(blends["intraday"], blends["swing"]),
        "price": price,
        "price_time": price_time,
        "price_text": (f"{_fmt(price)} {unit}".strip()) if price is not None else None,
    }
