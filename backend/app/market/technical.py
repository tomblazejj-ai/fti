"""Daily + weekly technical read of a price series — pure functions, no I/O.

Input is daily CLOSES only (the free gold source is a daily index, no
intraday high/low), so everything is close-based. Levels are reported as %
distance from the latest close: the source is an index that tracks gold,
not the $/oz quote on the user's chart — a % distance transfers to any
chart, an index level would not.

Output groups (shown in the UI in this order):
  trend      daily MA alignment, weekly trend, market structure, regression
  momentum   MACD, RSI (+ divergence), 20-day rate of change
  volatility Bollinger %B and squeeze, stretch from the 200-day average
  levels     pivot-based support/resistance, Fibonacci retracement
Every indicator returns a signal (+1 býčí / 0 / −1 medvědí) and one Czech
sentence; tech_score is their weighted average on −100…+100.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import dataclass

MIN_HISTORY = 210  # SMA200 plus a 20-day slope window
PIVOT_WINDOW = 5


class InsufficientPriceHistory(ValueError):
    pass


@dataclass
class TrendComponent:
    points: float
    text: str


# ---------------------------------------------------------------- helpers

def sma(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= n:
            running -= values[i - n]
        if i >= n - 1:
            out[i] = running / n
    return out


def ema(values: list[float], n: int) -> list[float]:
    k = 2.0 / (n + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi_series(values: list[float], n: int = 14) -> list[float | None]:
    """Wilder's RSI for every bar (None until enough data)."""
    out: list[float | None] = [None] * len(values)
    if len(values) <= n:
        return out
    gains = [max(0.0, values[i] - values[i - 1]) for i in range(1, len(values))]
    losses = [max(0.0, values[i - 1] - values[i]) for i in range(1, len(values))]
    avg_g = sum(gains[:n]) / n
    avg_l = sum(losses[:n]) / n
    out[n] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(n, len(gains)):
        avg_g = (avg_g * (n - 1) + gains[i]) / n
        avg_l = (avg_l * (n - 1) + losses[i]) / n
        out[i + 1] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


def rsi(values: list[float], n: int = 14) -> float | None:
    return rsi_series(values, n)[-1]


def pct_change(values: list[float], n: int) -> float | None:
    if len(values) <= n or values[-1 - n] == 0:
        return None
    return (values[-1] / values[-1 - n] - 1.0) * 100.0


def realised_vol(values: list[float], n: int = 20) -> float | None:
    """Annualised % standard deviation of daily log returns."""
    if len(values) <= n:
        return None
    rets = [math.log(values[i] / values[i - 1]) for i in range(len(values) - n, len(values))]
    return statistics.stdev(rets) * math.sqrt(252) * 100.0


def linreg(values: list[float]) -> tuple[float, float]:
    """Slope (% per day, on log prices) and R² of a straight-line fit."""
    ys = [math.log(v) for v in values]
    n = len(ys)
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (my + slope * (x - mx))) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    return (math.exp(slope) - 1) * 100.0, r2


def pivots(values: list[float], window: int = PIVOT_WINDOW) -> tuple[list[int], list[int]]:
    """Indexes of swing highs and swing lows (strict local extremes of ±window bars)."""
    highs, lows = [], []
    for i in range(window, len(values) - window):
        seg = values[i - window:i + window + 1]
        if values[i] == max(seg) and seg.count(values[i]) == 1:
            highs.append(i)
        if values[i] == min(seg) and seg.count(values[i]) == 1:
            lows.append(i)
    return highs, lows


def weekly_closes(dates: list[str], closes: list[float]) -> list[float]:
    """Last close of each ISO week."""
    out: list[float] = []
    last_key = None
    for d, c in zip(dates, closes):
        y, w, _ = dt.date.fromisoformat(d).isocalendar()
        if (y, w) == last_key:
            out[-1] = c
        else:
            out.append(c)
            last_key = (y, w)
    return out


def _pct_from(last: float, level: float) -> float:
    return (level / last - 1.0) * 100.0


def _pct(value: float) -> str:
    return f"{value:+.1f}".replace(".", ",").replace("-", "−") + " %"


def _num(value: float, digits: int = 0) -> str:
    return f"{value:.{digits}f}".replace(".", ",").replace("-", "−")


def _item(name: str, value: str, signal: int, text: str, weight: float) -> dict:
    return {"name": name, "value": value, "signal": signal, "text": text, "weight": weight}


LEVEL_NAME_PRIORITY = ["200denní průměr", "50denní průměr", "Roční minimum", "Roční maximum", "Cenová zóna"]


def _price(level: float, unit: str) -> float | None:
    return round(level, 2) if unit in ("USD", "DXY") else None


def _merge_close_levels(levels: list[dict], within_pct: float = 0.25) -> list[dict]:
    """Levels at practically the same price are ONE zone with more touches,
    not several separate lines. The zone keeps the most meaningful name."""
    merged: list[dict] = []
    for lv in levels:
        if merged and abs(merged[-1]["pct"] - lv["pct"]) < within_pct:
            prev = merged[-1]
            names = {prev["label"], lv["label"]}
            label = next(n for n in LEVEL_NAME_PRIORITY if n in names)
            merged[-1] = {**prev, "label": label, "touches": prev.get("touches", 1) + lv.get("touches", 1)}
        else:
            merged.append(dict(lv))
    return merged


def _days_since(values: list[bool]) -> int:
    """How many bars the last value of a boolean series has held."""
    n = 0
    for v in reversed(values):
        if v != values[-1]:
            break
        n += 1
    return n


# ---------------------------------------------------------------- analysis

def analyze(dates: list[str], closes: list[float], unit: str = "index") -> dict:
    """`unit` is "USD" for a real gold price (levels then also carry `price`), "DXY" for the rebuilt
    dollar index (also with prices), "index" for the FRED fallback."""
    if len(closes) < MIN_HISTORY:
        raise InsufficientPriceHistory(f"Pro trend je potřeba aspoň {MIN_HISTORY} denních cen, k dispozici {len(closes)}.")

    last = closes[-1]
    s20, s50, s200 = sma(closes, 20), sma(closes, 50), sma(closes, 200)
    sma20, sma50, sma200, sma50_prev = s20[-1], s50[-1], s200[-1], s50[-21]
    slope50 = (sma50 / sma50_prev - 1.0) * 100.0
    mom20 = pct_change(closes, 20) or 0.0

    # --- classic daily trend score (kept stable: the verdict and UI depend on it)
    comps = [
        TrendComponent(30 if last > sma200 else -30,
                       f"Cena je {'nad' if last > sma200 else 'pod'} 200denním průměrem ({_pct(_pct_from(sma200, last))})."),
        TrendComponent(25 if sma50 > sma200 else -25,
                       f"50denní průměr je {'nad' if sma50 > sma200 else 'pod'} 200denním ({'býčí' if sma50 > sma200 else 'medvědí'} uspořádání)."),
        TrendComponent(20 if last > sma50 else -20,
                       f"Cena je {'nad' if last > sma50 else 'pod'} 50denním průměrem ({_pct(_pct_from(sma50, last))})."),
        TrendComponent(
            (15 if slope50 > 0 else -15) if abs(slope50) > 0.3 else 0,
            f"50denní průměr za měsíc {'roste' if slope50 > 0.3 else 'klesá' if slope50 < -0.3 else 'je téměř plochý'} ({_pct(slope50)}).",
        ),
        TrendComponent(max(-10.0, min(10.0, mom20 * 2.0)), f"Změna ceny za 20 obchodních dní: {_pct(mom20)}."),
    ]
    trend_score = round(sum(c.points for c in comps), 1)

    # --- weekly trend (≈ 10- and 40-week averages = 50/200 days)
    wk = weekly_closes(dates, closes)
    w10, w40 = sma(wk, 10)[-1], sma(wk, 40)[-1] if len(wk) >= 40 else None
    if w10 is not None and w40 is not None:
        weekly_sig = 1 if wk[-1] > w40 and w10 > w40 else -1 if wk[-1] < w40 and w10 < w40 else 0
        weekly_text = {
            1: "Na týdenním grafu je cena nad 40týdenním průměrem a krátký průměr je nad dlouhým — dlouhodobý trend nahoru.",
            -1: "Na týdenním grafu je cena pod 40týdenním průměrem a krátký průměr pod dlouhým — dlouhodobý trend dolů.",
            0: "Týdenní graf je smíšený — dlouhodobý trend se láme nebo jde do strany.",
        }[weekly_sig]
    else:
        weekly_sig, weekly_text = 0, "Na týdenní trend je málo historie."

    # --- market structure from swing points
    highs, lows = pivots(closes[-180:])
    base = len(closes) - min(180, len(closes))
    highs = [i + base for i in highs]
    lows = [i + base for i in lows]
    if len(highs) >= 2 and len(lows) >= 2:
        hh = closes[highs[-1]] > closes[highs[-2]]
        hl = closes[lows[-1]] > closes[lows[-2]]
        if hh and hl:
            struct_sig, struct_text = 1, "Vyšší maxima i vyšší minima — rostoucí struktura trhu."
        elif not hh and not hl:
            struct_sig, struct_text = -1, "Nižší maxima i nižší minima — klesající struktura trhu."
        else:
            struct_sig, struct_text = 0, "Maxima a minima se nepotvrzují — struktura je smíšená (konsolidace nebo obrat)."
    else:
        struct_sig, struct_text = 0, "Málo výrazných swingů na určení struktury."

    # --- regression: direction and cleanliness of the last 50 days
    reg_slope, reg_r2 = linreg(closes[-50:])
    monthly = reg_slope * 21
    reg_sig = (1 if monthly > 0 else -1) if abs(monthly) > 1.0 and reg_r2 > 0.3 else 0
    quality = "čistý" if reg_r2 > 0.6 else "rozkolísaný" if reg_r2 > 0.3 else "bez směru"
    reg_text = f"Lineární trend za 50 dní: {_pct(monthly)} měsíčně, průběh {quality} (R² {_num(reg_r2, 2)})."

    # --- MACD 12/26/9
    e12, e26 = ema(closes, 12), ema(closes, 26)
    macd_line = [a - b for a, b in zip(e12, e26)]
    signal_line = ema(macd_line, 9)
    hist = [a - b for a, b in zip(macd_line, signal_line)]
    macd_above = [m > s for m, s in zip(macd_line, signal_line)]
    macd_days = _days_since(macd_above)
    hist_rising = hist[-1] > hist[-2]
    macd_sig = 1 if macd_above[-1] else -1
    side = "býčí" if macd_above[-1] else "medvědí"
    macd_text = (
        f"MACD je {'nad' if macd_above[-1] else 'pod'} signální linkou už {macd_days} "
        f"{'den' if macd_days == 1 else 'dní' if macd_days >= 5 else 'dny'} — {side} momentum "
        f"{'sílí' if (hist_rising == macd_above[-1]) else 'slábne'}."
    )

    # --- RSI + divergence
    rs = rsi_series(closes, 14)
    rsi14 = rs[-1]
    if rsi14 is None:
        rsi_state, rsi_sig = "neznámé", 0
    elif rsi14 >= 70:
        rsi_state, rsi_sig = "překoupeno", -1
    elif rsi14 <= 30:
        rsi_state, rsi_sig = "přeprodáno", 1
    else:
        rsi_state, rsi_sig = "neutrální", (1 if rsi14 > 55 else -1 if rsi14 < 45 else 0)
    rsi_text = {
        "překoupeno": "RSI nad 70 — trh je překoupený, růst je natažený a hrozí oddech.",
        "přeprodáno": "RSI pod 30 — trh je přeprodaný, pokles je natažený a hrozí odraz.",
    }.get(rsi_state, f"RSI {_num(rsi14 or 0)} — {'kupující mají mírnou převahu' if rsi_sig > 0 else 'prodávající mají mírnou převahu' if rsi_sig < 0 else 'rovnováha'}.")

    divergence, div_sig, div_text = None, 0, "Bez divergence mezi cenou a RSI."
    recent_lows = [i for i in lows if i >= len(closes) - 60]
    recent_highs = [i for i in highs if i >= len(closes) - 60]
    if len(recent_lows) >= 2:
        a, b = recent_lows[-2], recent_lows[-1]
        if closes[b] < closes[a] and rs[a] is not None and rs[b] is not None and rs[b] > rs[a]:
            divergence, div_sig = "bullish", 1
            div_text = "Býčí divergence: cena udělala nižší minimum, RSI už ne — prodejní tlak slábne."
    if divergence is None and len(recent_highs) >= 2:
        a, b = recent_highs[-2], recent_highs[-1]
        if closes[b] > closes[a] and rs[a] is not None and rs[b] is not None and rs[b] < rs[a]:
            divergence, div_sig = "bearish", -1
            div_text = "Medvědí divergence: cena udělala vyšší maximum, RSI už ne — nákupní tlak slábne."

    roc_sig = 1 if mom20 > 1 else -1 if mom20 < -1 else 0
    roc_text = f"Za posledních 20 obchodních dní {'vzrostla' if mom20 > 0 else 'klesla'} cena o {_pct(mom20).lstrip('+−')}."

    # --- Bollinger 20/2
    std20 = statistics.pstdev(closes[-20:])
    upper, lower = sma20 + 2 * std20, sma20 - 2 * std20
    pct_b = (last - lower) / (upper - lower) if upper != lower else 0.5
    widths = []
    for i in range(len(closes) - 120, len(closes)):
        seg = closes[i - 19:i + 1]
        m = sum(seg) / 20
        widths.append(4 * statistics.pstdev(seg) / m)
    width_rank = sum(1 for w in widths if w <= widths[-1]) / len(widths) * 100
    squeeze = width_rank <= 20
    if pct_b > 1:
        bb_text = "Cena je nad horním Bollingerovým pásmem — silný, ale natažený růst."
    elif pct_b < 0:
        bb_text = "Cena je pod dolním Bollingerovým pásmem — silný, ale natažený pokles."
    else:
        bb_text = f"Cena je v Bollingerových pásmech na {_num(pct_b * 100)} % jejich šířky (0 = dolní, 100 = horní)."
    if squeeze:
        bb_text += " Pásma jsou nezvykle úzká — trh se stlačuje, často následuje prudký pohyb."

    stretch = (last / sma200 - 1) * 100
    hist_stretch = [(closes[i] / s200[i] - 1) * 100 for i in range(len(closes) - 250, len(closes)) if s200[i]]
    z = (stretch - statistics.mean(hist_stretch)) / (statistics.pstdev(hist_stretch) or 1)
    stretch_text = (f"Cena je {_pct(stretch)} od 200denního průměru"
                    + (" — to je na poměry posledního roku extrémní vzdálenost, návrat k průměru je pravděpodobný." if abs(z) > 2 else "."))

    # --- trend age and last MA cross
    above50 = [c > m for c, m in zip(closes, s50) if m is not None]
    days_side50 = _days_since(above50)
    cross = None
    for i in range(len(closes) - 1, 200, -1):
        if s50[i] is None or s200[i] is None or s50[i - 1] is None or s200[i - 1] is None:
            break
        if (s50[i] > s200[i]) != (s50[i - 1] > s200[i - 1]):
            cross = {"type": "golden" if s50[i] > s200[i] else "death", "date": dates[i], "days_ago": len(closes) - 1 - i}
            break

    # --- support/resistance from pivots + MAs + extremes
    candidates: list[dict] = []
    # A former swing high can be today's support and vice versa, so pivots are
    # simply "price zones"; what matters is where the price reacted before.
    for i in highs + lows:
        candidates.append({"label": "Cenová zóna", "level": closes[i], "touches": 1})
    candidates += [
        {"label": "50denní průměr", "level": sma50, "touches": 1},
        {"label": "200denní průměr", "level": sma200, "touches": 1},
        {"label": "Roční minimum", "level": min(closes[-252:]), "touches": 1},
        {"label": "Roční maximum", "level": max(closes[-252:]), "touches": 1},
    ]
    below = sorted(
        ({"label": c["label"], "pct": round(_pct_from(last, c["level"]), 2), "price": _price(c["level"], unit), "touches": c["touches"]}
         for c in candidates if c["level"] < last * 0.999),
        key=lambda x: -x["pct"],
    )
    above = sorted(
        ({"label": c["label"], "pct": round(_pct_from(last, c["level"]), 2), "price": _price(c["level"], unit), "touches": c["touches"]}
         for c in candidates if c["level"] > last * 1.001),
        key=lambda x: x["pct"],
    )
    supports = _merge_close_levels(below, within_pct=0.6)[:3]
    resistances = _merge_close_levels(above, within_pct=0.6)[:3]

    # --- Fibonacci of the last major swing (120 days)
    window = closes[-120:]
    hi_i, lo_i = window.index(max(window)), window.index(min(window))
    hi, lo = max(window), min(window)
    fib = []
    if hi > lo:
        down_swing = hi_i < lo_i  # high came first → we are retracing a fall
        for r in (0.236, 0.382, 0.5, 0.618):
            level = lo + r * (hi - lo) if down_swing else hi - r * (hi - lo)
            fib.append({"ratio": r, "pct": round(_pct_from(last, level), 2), "price": _price(level, unit)})
        fib_text = (f"Poslední velký pohyb byl {'pokles' if down_swing else 'růst'} o {_pct((lo / hi - 1) * 100 if down_swing else (hi / lo - 1) * 100).lstrip('+−')}; "
                    f"Fibonacciho úrovně návratu jsou níže v tabulce.")
    else:
        fib_text = "Bez výrazného swingu pro Fibonacci."

    # --- trend label & overall technical score
    strength = abs(trend_score)
    if trend_score >= 40:
        trend, trend_label = "up", "Silný rostoucí trend" if strength >= 70 and weekly_sig == 1 else "Rostoucí trend"
    elif trend_score <= -40:
        trend, trend_label = "down", "Silný klesající trend" if strength >= 70 and weekly_sig == -1 else "Klesající trend"
    else:
        trend, trend_label = "sideways", "Bez jasného trendu (konsolidace)"

    groups = [
        {"key": "trend", "title": "Trend", "items": [
            _item("Denní trend (průměry 50/200)", f"{_num(trend_score, 0)}", 1 if trend_score >= 40 else -1 if trend_score <= -40 else 0,
                  " ".join(c.text for c in comps[:3]), 20),
            _item("Týdenní trend", "nahoru" if weekly_sig > 0 else "dolů" if weekly_sig < 0 else "smíšený", weekly_sig, weekly_text, 15),
            _item("Struktura trhu", "rostoucí" if struct_sig > 0 else "klesající" if struct_sig < 0 else "smíšená", struct_sig, struct_text, 10),
            _item("Směr a čistota (regrese 50 dní)", _pct(monthly) + "/měs.", reg_sig, reg_text, 10),
        ]},
        {"key": "momentum", "title": "Momentum", "items": [
            _item("MACD (12, 26, 9)", "nad signálem" if macd_above[-1] else "pod signálem", macd_sig, macd_text, 12),
            _item("RSI (14)", _num(rsi14 or 0), rsi_sig, rsi_text, 8),
            _item("Divergence RSI", {"bullish": "býčí", "bearish": "medvědí"}.get(divergence or "", "žádná"), div_sig, div_text, 8),
            _item("Změna za 20 dní", _pct(mom20), roc_sig, roc_text, 7),
        ]},
        {"key": "volatility", "title": "Volatilita a natažení", "items": [
            _item("Bollingerova pásma (20, 2)", f"{_num(pct_b * 100)} %", 0, bb_text, 0),
            _item("Vzdálenost od 200denního průměru", _pct(stretch), 0, stretch_text, 0),
            _item("Kolísavost (20 dní, ročně)", f"{_num(realised_vol(closes, 20) or 0, 1)} %", 0,
                  "Čím vyšší kolísavost, tím širší stop-loss a menší pozice.", 0),
        ]},
    ]
    weighted = [(it["signal"], it["weight"]) for g in groups for it in g["items"] if it["weight"]]
    tech_score = round(sum(s * w for s, w in weighted) / sum(w for _, w in weighted) * 100, 1)

    history_len = 180
    history = [
        {"date": d, "close": round(c, 2), "sma50": round(a, 2) if a else None, "sma200": round(b, 2) if b else None}
        for d, c, a, b in zip(dates[-history_len:], closes[-history_len:], s50[-history_len:], s200[-history_len:])
    ]

    return {
        "as_of": dates[-1],
        "unit": unit,
        "last_price": _price(last, unit),
        "trend": trend,
        "trend_label": trend_label,
        "trend_score": trend_score,
        "tech_score": tech_score,
        "components": [{"points": c.points, "text": c.text} for c in comps],
        "groups": groups,
        "trend_age_days": days_side50,
        "trend_age_text": f"Cena je {'nad' if above50[-1] else 'pod'} 50denním průměrem už {days_side50} obchodních dní.",
        "last_cross": cross,
        "rsi14": round(rsi14, 1) if rsi14 is not None else None,
        "rsi_state": rsi_state,
        "divergence": divergence,
        "macd_bullish": macd_above[-1],
        "bollinger_pct_b": round(pct_b * 100, 1),
        "squeeze": squeeze,
        "changes": {k: (round(v, 2) if v is not None else None) for k, v in
                    {"1d": pct_change(closes, 1), "5d": pct_change(closes, 5), "20d": pct_change(closes, 20),
                     "60d": pct_change(closes, 60), "250d": pct_change(closes, 250)}.items()},
        "volatility20": round(realised_vol(closes, 20) or 0.0, 1),
        "supports": supports,
        "resistances": resistances,
        "fibonacci": fib,
        "fibonacci_text": fib_text,
        "sma50_pct": round(_pct_from(last, sma50), 2),
        "sma200_pct": round(_pct_from(last, sma200), 2),
        "history": history,
    }
