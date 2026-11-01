"""Fundamentální skóre XAU/USD a dolaru — 11 kategorií sečtených do ±25.

The lesson defines the categories and their ranges; the total is their plain SUM
(EUR-JPY example in the PDF: 1+1+2+2+2+1+0+0+2−2+0 = 9). For a pair the
algorithm compares both sides; XAU/USD is gold against the US dollar, so:

    category            range   XAU/USD side
    COT                 ±3      gold managed money vs. USD leveraged funds
    Retail sentiment    ±1      gold small traders, contrarian
    Seasonality         ±2      gold, 10-year monthly statistics
    GDP                 ±2      USD economy, sign flipped (strong USD = weaker XAU/USD)
    Inflation           ±3      USD, flipped (high inflation → higher rates → stronger USD)
    Labor               ±4      USD, flipped
    Interest rates      ±2      USD rate EXPECTATIONS (2-year yield vs Fed funds), flipped
    Services PMI        ±2      USD, flipped
    Manufacturing PMI   ±2      USD, flipped
    Retail sales        ±2      USD, flipped
    Trend               ±2      gold price trend (daily + weekly) with a reversal check
    TOTAL               ±25

Every rule below is a fixed, readable threshold — the PDFs give the ranges and
the direction of each effect, not the exact formulas; those choices are ours and
are written next to each score so the trader can see why it moved.

Data that would need paid feeds are replaced by free official data and
labelled as such: ISM/S&P PMI → regional Fed surveys (diffusion indexes, 0 =
no change), broker retail sentiment → CFTC small traders, rate-probability tools
→ the 2-year Treasury yield against the effective Fed funds rate.

`compute(inputs, asof)` uses only data that was PUBLISHED by `asof` (each series
carries its usual publication lag), so the same code rebuilds the score history.
`compute(..., live=True)` is the score right now: whatever the sources return has
already been published, so nothing is held back by the modelled lag.
"""

from __future__ import annotations

import bisect
import datetime as dt
import statistics
from dataclasses import dataclass, field, replace

from app.connectors.kraken import Candle
from app.market import mtf
from app.market.technical import pivots, rsi_series

# --- FRED series and when their values become public -------------------------------
# (frequency, anchor, lag days): available from period_start/period_end + lag.

@dataclass(frozen=True)
class SeriesSpec:
    freq: str  # "D" | "W" | "M" | "Q"
    anchor: str  # "start" | "end" of the observation period
    lag: int


FRED_SPECS: dict[str, SeriesSpec] = {
    "GDPC1": SeriesSpec("Q", "end", 30),  # advance estimate ~1 month after the quarter
    "CFNAI": SeriesSpec("M", "end", 25),
    "CPILFESL": SeriesSpec("M", "end", 14),
    "CPIAUCSL": SeriesSpec("M", "end", 14),
    "PCEPILFE": SeriesSpec("M", "end", 30),
    "PAYEMS": SeriesSpec("M", "end", 7),  # first Friday
    "UNRATE": SeriesSpec("M", "end", 7),
    "CES0500000003": SeriesSpec("M", "end", 7),
    "SAHMREALTIME": SeriesSpec("M", "end", 7),
    "RSAFS": SeriesSpec("M", "end", 16),
    "GACDISA066MSFRBNY": SeriesSpec("M", "start", 16),  # Empire State, mid-month
    "GACDFSA066MSFRBPHI": SeriesSpec("M", "start", 21),  # Philadelphia, third Thursday
    "BACTSAMFRBDAL": SeriesSpec("M", "start", 30),  # Dallas manufacturing, last Monday
    "GABNDIF066MSFRBPHI": SeriesSpec("M", "start", 23),  # Philadelphia non-manufacturing
    "TSSOSBACTSAMFRBDAL": SeriesSpec("M", "start", 31),  # Dallas services, last Tuesday
    "DGS2": SeriesSpec("D", "start", 1),
    "DFF": SeriesSpec("D", "start", 1),
}
TRA_FRED_IDS = list(FRED_SPECS)
MFG_SURVEYS = {"GACDISA066MSFRBNY": "New York (Empire State)", "GACDFSA066MSFRBPHI": "Philadelphia", "BACTSAMFRBDAL": "Dallas"}
SVC_SURVEYS = {"GABNDIF066MSFRBPHI": "Philadelphia (služby)", "TSSOSBACTSAMFRBDAL": "Dallas (služby)"}

COT_PUBLICATION_LAG_DAYS = 3  # Tuesday positions, published Friday
MONTHLY_PRICE_LAG_DAYS = 3  # World Bank Pink Sheet: early in the next month

RANGES = {"cot": 3, "retail": 1, "seasonality": 2, "gdp": 2, "inflation": 3, "labor": 4, "rates": 2,
          "spmi": 2, "mpmi": 2, "retail_sales": 2, "trend": 2}
LABELS = {"cot": "COT bias", "retail": "Retail sentiment", "seasonality": "Sezónnost", "gdp": "HDP", "inflation": "Inflace",
          "labor": "Trh práce", "rates": "Úrokové sazby", "spmi": "PMI služby", "mpmi": "PMI průmysl",
          "retail_sales": "Maloobchodní tržby", "trend": "Trend"}
ORDER = ["cot", "retail", "seasonality", "gdp", "inflation", "labor", "rates", "spmi", "mpmi", "retail_sales", "trend"]
MAX_TOTAL = sum(RANGES.values())  # 25
# Bumped whenever a rule changes; the stored score history is then rebuilt with the new rules
# so the chart never mixes two models (2 = commercials + open interest in the gold COT).
MODEL_VERSION = 2


@dataclass
class TraInputs:
    fred: dict[str, dict[str, float]] = field(default_factory=dict)  # series → {date: value}
    gold_cot: list[dict] = field(default_factory=list)  # CFTC disaggregated rows (spec_* = managed money)
    usd_cot: list[dict] = field(default_factory=list)  # CFTC TFF rows for the USD Index
    gold_monthly: dict[str, float] = field(default_factory=dict)  # "YYYY-MM" → monthly average (World Bank)
    usd_daily: dict[str, float] = field(default_factory=dict)  # DXY rebuilt from ECB fixings, date → value
    gold_d1: list[Candle] = field(default_factory=list)
    gold_w1: list[Candle] = field(default_factory=list)
    dxy_d1: list[Candle] = field(default_factory=list)
    dxy_w1: list[Candle] = field(default_factory=list)


# --- helpers --------------------------------------------------------------------------

def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _clip(x: float, lim: int) -> int:
    return int(max(-lim, min(lim, round(x))))


def _num(v: float, digits: int = 1, signed: bool = False) -> str:
    s = f"{v:+.{digits}f}" if signed else f"{v:.{digits}f}"
    return s.replace(".", ",").replace("-", "−")


def _period_end(d: dt.date, freq: str) -> dt.date:
    if freq == "M":
        nxt = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        return nxt - dt.timedelta(days=1)
    if freq == "Q":
        m = d.month + 3
        nxt = dt.date(d.year + (m > 12), (m - 1) % 12 + 1, 1)
        return nxt - dt.timedelta(days=1)
    return d


class AsOf:
    """Values of one series as they were known on a given day (lag-aware)."""

    def __init__(self, series: dict[str, float], spec: SeriesSpec):
        rows = []
        for d, v in series.items():
            obs = dt.date.fromisoformat(d)
            base = _period_end(obs, spec.freq) if spec.anchor == "end" else obs
            rows.append((base + dt.timedelta(days=spec.lag), d, v))
        rows.sort()
        self.avail = [r[0] for r in rows]
        self.rows = rows

    def known(self, asof: dt.date) -> list[tuple[str, float]]:
        """(observation date, value) pairs published by `asof`, in observation order."""
        k = bisect.bisect_right(self.avail, asof)
        return sorted((r[1], r[2]) for r in self.rows[:k])


def _shift(day: str, months: int) -> str:
    y, m = int(day[:4]), int(day[5:7]) - months
    while m <= 0:
        m, y = m + 12, y - 1
    return f"{y:04d}-{m:02d}-01"


def _month_value(values: list[tuple[str, float]], day: str) -> float | None:
    """Monthly value by DATE, not by position: FRED leaves gaps (October 2025 — no CPI or
    unemployment survey during the US government shutdown). One missing month is bridged
    by the geometric mean of its neighbours."""
    look = dict(values)
    if day in look:
        return look[day]
    before, after = look.get(_shift(day, 1)), look.get(_shift(day, -1))
    return (before * after) ** 0.5 if before and after else None


def _yoy(values: list[tuple[str, float]], back: int = 0) -> float | None:
    """Year-over-year % of a monthly level series, `back` months before the latest."""
    if not values:
        return None
    day = _shift(values[-1][0], back)
    cur, prev = _month_value(values, day), _month_value(values, _shift(day, 12))
    return (cur / prev - 1) * 100 if cur is not None and prev else None


def _component(key: str, score: int, reason: str, inputs: list[dict], usd_score: int | None = None,
               proxy: str | None = None) -> dict:
    return {"key": key, "label": LABELS[key], "score": score, "max": RANGES[key], "reason": reason,
            "inputs": inputs, "usd_score": usd_score, "proxy": proxy}


def _missing(key: str, why: str) -> dict:
    return {"key": key, "label": LABELS[key], "score": None, "max": RANGES[key], "reason": why, "inputs": [],
            "usd_score": None, "proxy": None}


# --- USD macro categories (scored for the US DOLLAR; XAU/USD gets the opposite sign) ---

def usd_gdp(k: dict[str, AsOf], asof: dt.date) -> tuple[int, str, list[dict]] | None:
    gdp = k["GDPC1"].known(asof) if "GDPC1" in k else []
    if len(gdp) < 2:
        return None
    growth = ((gdp[-1][1] / gdp[-2][1]) ** 4 - 1) * 100
    pts = 2 if growth >= 3 else 1 if growth >= 2 else 0 if growth >= 1 else -1 if growth >= 0 else -2
    inputs = [{"name": "Reálné HDP (q/q anualizovaně)", "value": f"{_num(growth, 1, True)} %", "as_of": gdp[-1][0]}]
    text = f"HDP USA roste {_num(growth)} % ročním tempem"
    cf = k["CFNAI"].known(asof) if "CFNAI" in k else []
    if len(cf) >= 3:
        ma3 = statistics.mean(v for _, v in cf[-3:])
        inputs.append({"name": "Index aktivity Chicago Fed (3m průměr)", "value": _num(ma3, 2, True), "as_of": cf[-1][0]})
        if ma3 >= 0.2:
            pts += 1
            text += ", aktivita nad trendem"
        elif ma3 <= -0.35:
            pts -= 1
            text += ", aktivita pod trendem"
    return _clip(pts, 2), text + ".", inputs


def usd_inflation(k: dict[str, AsOf], asof: dt.date) -> tuple[int, str, list[dict]] | None:
    core = k["CPILFESL"].known(asof) if "CPILFESL" in k else []
    level = _yoy(core)
    if level is None:
        return None
    prev3 = _yoy(core, 3)
    pts = 2 if level >= 3.5 else 1 if level >= 2.75 else -2 if level <= 1.25 else -1 if level <= 1.75 else 0
    dev = 0.0 if prev3 is None else level - prev3
    pts += 1 if dev >= 0.2 else -1 if dev <= -0.2 else 0
    inputs = [{"name": "Jádrová inflace CPI r/r", "value": f"{_num(level)} %", "as_of": core[-1][0]}]
    if prev3 is not None:
        inputs.append({"name": "Změna za 3 měsíce", "value": f"{_num(dev, 1, True)} p.b.", "as_of": core[-1][0]})
    head = _yoy(k["CPIAUCSL"].known(asof)) if "CPIAUCSL" in k else None
    if head is not None:
        inputs.append({"name": "Celková inflace CPI r/r", "value": f"{_num(head)} %", "as_of": k["CPIAUCSL"].known(asof)[-1][0]})
    trend = "zrychluje" if dev >= 0.2 else "zpomaluje" if dev <= -0.2 else "je stabilní"
    return _clip(pts, 3), f"Jádrová inflace {_num(level)} % a {trend} (cíl Fedu 2 %).", inputs


def usd_labor(k: dict[str, AsOf], asof: dt.date) -> tuple[int, str, list[dict]] | None:
    nfp = k["PAYEMS"].known(asof) if "PAYEMS" in k else []
    if len(nfp) < 4:
        return None
    jobs3 = statistics.mean(nfp[-i][1] - nfp[-i - 1][1] for i in range(1, 4))
    pts = 2 if jobs3 >= 200 else 1 if jobs3 >= 100 else -2 if jobs3 < 0 else -1 if jobs3 < 50 else 0
    inputs = [{"name": "Nová pracovní místa NFP (3m průměr)", "value": f"{_num(jobs3, 0, True)} tis.", "as_of": nfp[-1][0]}]
    parts = [f"{_num(jobs3, 0)} tis. nových míst měsíčně"]
    un = k["UNRATE"].known(asof) if "UNRATE" in k else []
    un3 = _month_value(un, _shift(un[-1][0], 3)) if un else None
    if un3 is not None:
        d3 = un[-1][1] - un3
        pts += 1 if d3 <= -0.2 else -1 if d3 >= 0.2 else 0
        inputs.append({"name": "Nezaměstnanost", "value": f"{_num(un[-1][1])} % ({_num(d3, 1, True)} za 3 m)", "as_of": un[-1][0]})
        parts.append(f"nezaměstnanost {_num(un[-1][1])} %")
    sahm = k["SAHMREALTIME"].known(asof) if "SAHMREALTIME" in k else []
    if sahm and sahm[-1][1] >= 0.5:
        pts -= 1
        parts.append("Sahmovo pravidlo hlásí recesi")
        inputs.append({"name": "Sahmovo pravidlo recese", "value": _num(sahm[-1][1], 2), "as_of": sahm[-1][0]})
    wages = _yoy(k["CES0500000003"].known(asof)) if "CES0500000003" in k else None
    if wages is not None:
        pts += 1 if wages >= 4.0 else -1 if wages <= 3.0 else 0
        inputs.append({"name": "Hodinové mzdy r/r", "value": f"{_num(wages)} %", "as_of": k["CES0500000003"].known(asof)[-1][0]})
        parts.append(f"mzdy +{_num(wages)} %")
    return _clip(pts, 4), _cap(", ".join(parts)) + ".", inputs


def usd_rates(k: dict[str, AsOf], asof: dt.date) -> tuple[int, str, list[dict]] | None:
    two = k["DGS2"].known(asof) if "DGS2" in k else []
    ff = k["DFF"].known(asof) if "DFF" in k else []
    if not two or not ff:
        return None
    spread = two[-1][1] - ff[-1][1]
    pts = 2 if spread >= 0.6 else 1 if spread >= 0.25 else -2 if spread <= -0.6 else -1 if spread <= -0.25 else 0
    back = [v for d, v in two if dt.date.fromisoformat(d) <= asof - dt.timedelta(days=28)]
    chg = two[-1][1] - back[-1] if back else 0.0
    pts += 1 if chg >= 0.25 else -1 if chg <= -0.25 else 0
    expect = ("trh čeká ZVYŠOVÁNÍ sazeb" if spread >= 0.25 else "trh čeká SNIŽOVÁNÍ sazeb" if spread <= -0.25
              else "trh nečeká velkou změnu sazeb")
    inputs = [{"name": "2letý výnos USA", "value": f"{_num(two[-1][1], 2)} %", "as_of": two[-1][0]},
              {"name": "Efektivní sazba Fedu", "value": f"{_num(ff[-1][1], 2)} %", "as_of": ff[-1][0]},
              {"name": "Změna 2letého výnosu za 4 týdny", "value": f"{_num(chg, 2, True)} p.b.", "as_of": two[-1][0]}]
    return _clip(pts, 2), f"2letý výnos {_num(two[-1][1], 2)} % vs. sazba Fedu {_num(ff[-1][1], 2)} % → {expect}.", inputs


def _survey(k: dict[str, AsOf], asof: dt.date, ids: dict[str, str], label: str) -> tuple[int, str, list[dict]] | None:
    latest, older, inputs = [], [], []
    for sid, name in ids.items():
        vals = k[sid].known(asof) if sid in k else []
        if len(vals) < 4:
            continue
        latest.append(vals[-1][1])
        older.append(vals[-4][1])
        inputs.append({"name": name, "value": _num(vals[-1][1], 1, True), "as_of": vals[-1][0]})
    if not latest:
        return None
    now_avg, old_avg = statistics.mean(latest), statistics.mean(older)
    pts = (1 if now_avg >= 5 else -1 if now_avg <= -5 else 0) + (1 if now_avg - old_avg >= 5 else -1 if now_avg - old_avg <= -5 else 0)
    state = "roste" if now_avg >= 5 else "klesá" if now_avg <= -5 else "stagnuje"
    trend = "zlepšuje se" if now_avg - old_avg >= 5 else "zhoršuje se" if now_avg - old_avg <= -5 else "beze změny"
    return _clip(pts, 2), f"{label} {state} (průměr {_num(now_avg, 1, True)}, za 3 měsíce {trend}).", inputs


def usd_retail_sales(k: dict[str, AsOf], asof: dt.date) -> tuple[int, str, list[dict]] | None:
    rs = k["RSAFS"].known(asof) if "RSAFS" in k else []
    if len(rs) < 4:
        return None
    mom = [(rs[-i][1] / rs[-i - 1][1] - 1) * 100 for i in range(1, 4)]
    avg3 = statistics.mean(mom)
    pts = 2 if avg3 >= 0.7 else 1 if avg3 >= 0.4 else -2 if avg3 <= -0.5 else -1 if avg3 <= 0.0 else 0
    inputs = [{"name": "Maloobchodní tržby m/m (poslední)", "value": f"{_num(mom[0], 1, True)} %", "as_of": rs[-1][0]},
              {"name": "Průměr za 3 měsíce", "value": f"{_num(avg3, 2, True)} %", "as_of": rs[-1][0]}]
    word = "silná" if pts > 0 else "slabá" if pts < 0 else "průměrná"
    return pts, f"Spotřeba je {word}: tržby rostou v průměru {_num(avg3, 2, True)} % měsíčně.", inputs


# --- positioning ------------------------------------------------------------------------

def _published(rows: list[dict], asof: dt.date) -> list[dict]:
    return [r for r in rows if dt.date.fromisoformat(r["date"]) + dt.timedelta(days=COT_PUBLICATION_LAG_DAYS) <= asof]


def _index(values: list[float]) -> float | None:
    lo, hi = min(values), max(values)
    return None if hi == lo else (values[-1] - lo) / (hi - lo) * 100


def gold_cot_score(rows: list[dict]) -> tuple[int, dict] | None:
    """Funds (managed money): crowding level + 4-week flow. Since 2026-10-17
    also the commercials at a 3-year extreme (±1) and the open interest: when contracts are being
    closed (OI −3 % in 4 weeks) the funds' flow counts one step less."""
    if len(rows) < 30:
        return None
    net = [r["spec_net"] for r in rows]
    idx = _index(net[-156:])
    moves = [net[i] - net[i - 4] for i in range(4, len(net))]
    sd = statistics.pstdev(moves) or 1.0
    z = (net[-1] - net[-5]) / sd if len(net) >= 5 else 0.0
    level = 0 if idx is None else (-1 if idx >= 90 else 1 if idx <= 10 else 1 if idx >= 65 else -1 if idx <= 35 else 0)
    flow = 2 if z >= 1.5 else 1 if z >= 0.5 else -2 if z <= -1.5 else -1 if z <= -0.5 else 0
    oi = [r.get("open_interest") or 0 for r in rows]
    oi_chg = (oi[-1] / oi[-5] - 1) * 100 if len(oi) >= 5 and oi[-5] else 0.0
    damped = flow != 0 and oi_chg <= -3.0
    if damped:
        flow += -1 if flow > 0 else 1
    comm = [r["comm_net"] for r in rows if r.get("comm_net") is not None]
    comm_idx = _index(comm[-156:]) if len(comm) >= 30 else None
    comm_pts = 0 if comm_idx is None else 1 if comm_idx >= 90 else -1 if comm_idx <= 10 else 0
    last = rows[-1]
    long_pct = last["spec_long"] / (last["spec_long"] + last["spec_short"]) * 100 if last["spec_long"] + last["spec_short"] else None
    return _clip(level + flow + comm_pts, 3), {"index": idx, "z": z, "long_pct": long_pct, "as_of": last["date"],
                                               "comm_index": comm_idx, "comm_pts": comm_pts, "oi_change": oi_chg, "oi_damped": damped}


def usd_cot_score(rows: list[dict]) -> tuple[int, dict] | None:
    if len(rows) < 5:
        return None
    pct = [r["lev_long"] / (r["lev_long"] + r["lev_short"]) * 100 for r in rows if r["lev_long"] + r["lev_short"]]
    p = pct[-1]
    level = 0 if p >= 85 or p <= 15 else 2 if p >= 70 else 1 if p >= 60 else -2 if p <= 30 else -1 if p <= 40 else 0
    chg4 = p - pct[-5]
    flow = 1 if chg4 >= 10 else -1 if chg4 <= -10 else 0
    return _clip(level + flow, 3), {"long_pct": p, "change_4w": chg4, "as_of": rows[-1]["date"]}


def retail_score(rows: list[dict], long_key: str, short_key: str) -> tuple[int, dict] | None:
    pct = [r[long_key] / (r[long_key] + r[short_key]) * 100 for r in rows if r.get(long_key, 0) + r.get(short_key, 0)]
    if len(pct) < 30:
        return None
    idx = _index(pct[-156:])
    score = -1 if idx is not None and idx >= 80 else 1 if idx is not None and idx <= 20 else 0
    return score, {"long_pct": pct[-1], "index": idx, "as_of": rows[-1]["date"]}


# --- seasonality and trend --------------------------------------------------------------

def monthly_returns(monthly: dict[str, float]) -> dict[str, float]:
    keys = sorted(monthly)
    out = {}
    for a, b in zip(keys, keys[1:]):
        ya, ma = int(a[:4]), int(a[5:])
        if (int(b[:4]), int(b[5:])) == (ya + (ma == 12), ma % 12 + 1) and monthly[a]:
            out[b] = (monthly[b] / monthly[a] - 1) * 100
    return out


def month_stats(rets: dict[str, float], month: int, before: str, years: int) -> dict | None:
    """Average return of calendar `month` over the last `years` occurrences strictly before `before` ("YYYY-MM")."""
    vals = [(k, v) for k, v in sorted(rets.items()) if int(k[5:]) == month and k < before][-years:]
    if len(vals) < max(3, years // 2):
        return None
    xs = [v for _, v in vals]
    return {"avg": statistics.mean(xs), "win": sum(x > 0 for x in xs) / len(xs) * 100, "n": len(xs),
            "from": vals[0][0][:4], "to": vals[-1][0][:4]}


def seasonality_score(rets: dict[str, float], asof: dt.date) -> tuple[int, dict] | None:
    st = month_stats(rets, asof.month, f"{asof.year:04d}-{asof.month:02d}", 10)
    if st is None:
        return None
    a, w = st["avg"], st["win"]
    score = 2 if a >= 1.5 and w >= 70 else 1 if a >= 0.5 and w >= 60 else -2 if a <= -1.5 and w <= 30 else -1 if a <= -0.5 and w <= 40 else 0
    return score, st


def daily_monthly_avg(daily: dict[str, float]) -> dict[str, float]:
    buckets: dict[str, list[float]] = {}
    for d, v in daily.items():
        buckets.setdefault(d[:7], []).append(v)
    return {k: statistics.mean(v) for k, v in buckets.items() if len(v) >= 10}


def reversal_against(closes: list[float], direction: int) -> bool:
    """RSI divergence against the trend on the last two swing points (higher-low RSI in a downtrend etc.)."""
    if len(closes) < 60 or direction == 0:
        return False
    rsi = rsi_series(closes, 14)
    highs, lows = pivots(closes[-120:], 5)
    off = len(closes) - min(120, len(closes))
    pts = lows if direction < 0 else highs
    if len(pts) < 2:
        return False
    a, b = pts[-2] + off, pts[-1] + off
    if rsi[a] is None or rsi[b] is None:
        return False
    if direction < 0:
        return closes[b] < closes[a] and rsi[b] > rsi[a] + 2  # lower low in price, higher low in RSI
    return closes[b] > closes[a] and rsi[b] < rsi[a] - 2


def trend_score(d1: list[Candle], w1: list[Candle], asof_ts: dt.datetime) -> tuple[int, dict] | None:
    d = [c for c in d1 if c.time <= asof_ts]
    w = [c for c in w1 if c.time <= asof_ts]
    td = mtf.analyze_tf("D1", d) if len(d) >= mtf.MIN_CANDLES else None
    tw = mtf.analyze_tf("W1", w) if len(w) >= mtf.MIN_CANDLES else None
    if td is None and tw is None:
        return None
    parts = [(td, 0.6), (tw, 0.4)]
    used = [(t["score"], wt) for t, wt in parts if t]
    s = sum(v * wt for v, wt in used) / sum(wt for _, wt in used)
    score = 2 if s >= 0.6 else 1 if s >= 0.2 else -2 if s <= -0.6 else -1 if s <= -0.2 else 0
    reversal = reversal_against([c.close for c in d], 1 if score > 0 else -1 if score < 0 else 0)
    if reversal:
        score += -1 if score > 0 else 1
    return score, {"blend": s, "d1": td["word"] if td else None, "w1": tw["word"] if tw else None, "reversal": reversal}


# --- the whole score ----------------------------------------------------------------------

def _known(inputs: TraInputs, live: bool = False) -> dict[str, AsOf]:
    def spec(sid: str) -> SeriesSpec:
        return replace(FRED_SPECS[sid], lag=-36500) if live else FRED_SPECS[sid]
    return {sid: AsOf(series, spec(sid)) for sid, series in inputs.fred.items() if sid in FRED_SPECS and series}


def _verdict(total: int) -> dict:
    word = "Býčí" if total > 0 else "Medvědí" if total < 0 else "Neutrální"
    strong = abs(total) >= 8
    return {"word": word, "strength": "silně " if strong and total else "", "arrow": "up" if total > 0 else "down" if total < 0 else "flat"}


def compute(inputs: TraInputs, asof: dt.datetime, known: dict[str, AsOf] | None = None, live: bool = False) -> dict:
    """Both sides at `asof`: {"xau": {...}, "usd": {...}} with components, totals and words."""
    day = asof.date()
    k = known if known is not None else _known(inputs, live)

    def published(rows: list[dict]) -> list[dict]:
        return rows if live else _published(rows, day)
    usd_macro = {
        "gdp": usd_gdp(k, day),
        "inflation": usd_inflation(k, day),
        "labor": usd_labor(k, day),
        "rates": usd_rates(k, day),
        "mpmi": _survey(k, day, MFG_SURVEYS, "Průmysl"),
        "spmi": _survey(k, day, SVC_SURVEYS, "Sektor služeb"),
        "retail_sales": usd_retail_sales(k, day),
    }
    proxies = {"mpmi": "Regionální průzkumy Fedu (NY, Philadelphia, Dallas) místo ISM/S&P PMI, které nejsou zdarma.",
               "spmi": "Regionální průzkumy Fedu ve službách (Philadelphia, Dallas) místo ISM/S&P PMI služeb.",
               "rates": "Očekávání sazeb z 2letého výnosu vs. sazba Fedu (místo placených pravděpodobností typu FedWatch)."}

    xau: dict[str, dict] = {}
    usd: dict[str, dict] = {}
    for key, res in usd_macro.items():
        if res is None:
            xau[key] = _missing(key, "Data se nepodařilo stáhnout.")
            usd[key] = _missing(key, "Data se nepodařilo stáhnout.")
            continue
        s, text, inp = res
        usd[key] = _component(key, s, text, inp, usd_score=s, proxy=proxies.get(key))
        effect = "pro zlato negativní" if s > 0 else "pro zlato pozitivní" if s < 0 else "bez vlivu"
        xau[key] = _component(key, -s if s else 0, f"{text} Silnější dolar = {effect}." if s else text, inp, usd_score=s,
                              proxy=proxies.get(key))

    # COT
    g = gold_cot_score(published(inputs.gold_cot))
    u = usd_cot_score(published(inputs.usd_cot))
    if g or u:
        gs, gi = g if g else (0, {})
        us, ui = u if u else (0, {})
        pair = _clip(gs - us, 3)
        parts, inp = [], []
        if g:
            parts.append(f"fondy ve zlatě: COT index {_num(gi['index'] or 0, 0)}/100, tok {'přikupují' if gi['z'] > 0.5 else 'prodávají' if gi['z'] < -0.5 else 'beze změny'}")
            if gi.get("comm_pts"):
                parts.append(f"commercials v extrému (index {_num(gi['comm_index'] or 0, 0)}/100) → {'pro růst' if gi['comm_pts'] > 0 else 'pro pokles'}")
            if gi.get("oi_damped"):
                parts.append(f"open interest {_num(gi['oi_change'], 1, True)} % — zavírání pozic oslabuje signál fondů")
            inp.append({"name": "Zlato – hedgeové fondy long", "value": f"{_num(gi['long_pct'] or 0, 1)} %", "as_of": gi["as_of"]})
            if gi.get("comm_index") is not None:
                inp.append({"name": "Zlato – commercials, COT index 3 roky", "value": f"{_num(gi['comm_index'], 0)}/100", "as_of": gi["as_of"]})
        if u:
            parts.append(f"fondy v dolaru {_num(ui['long_pct'], 1)} % long ({_num(ui['change_4w'], 1, True)} p.b. za 4 týdny)")
            inp.append({"name": "USD – hedgeové fondy long", "value": f"{_num(ui['long_pct'], 1)} %", "as_of": ui["as_of"]})
        xau["cot"] = _component("cot", pair, _cap("; ".join(parts)) + ".", inp, usd_score=us if u else None)
        usd["cot"] = _component("cot", us, f"Hedgeové fondy v dolaru {_num(ui['long_pct'], 1)} % long." if u else "COT dolaru chybí.", inp[-1:] if u else [],
                                usd_score=us if u else None)
    else:
        xau["cot"] = usd["cot"] = _missing("cot", "COT data nejsou k dispozici.")

    # Retail sentiment (contrarian) — CFTC small traders instead of broker data
    proxy_retail = "Malí obchodníci z CFTC COT místo brokerských dat (ta nejsou zdarma bez registrace)."
    r = retail_score(published(inputs.gold_cot), "small_long", "small_short")
    if r:
        rs, ri = r
        why = ("retail je long nejvíc za 3 roky → kontrariánsky dolů" if rs < 0 else
               "retail je long nejméně za 3 roky → kontrariánsky nahoru" if rs > 0 else "retail není v extrému")
        xau["retail"] = _component("retail", rs, f"Malí obchodníci ve zlatě {_num(ri['long_pct'], 0)} % long, {why}.",
                                   [{"name": "Zlato – malí obchodníci long", "value": f"{_num(ri['long_pct'], 1)} %", "as_of": ri["as_of"]}],
                                   proxy=proxy_retail)
    else:
        xau["retail"] = _missing("retail", "Data o malých obchodnících chybí.")
    ru = retail_score(published(inputs.usd_cot), "small_long", "small_short")
    if ru:
        rs, ri = ru
        usd["retail"] = _component("retail", rs, f"Malí obchodníci v dolaru {_num(ri['long_pct'], 0)} % long.",
                                   [{"name": "USD – malí obchodníci long", "value": f"{_num(ri['long_pct'], 1)} %", "as_of": ri["as_of"]}],
                                   proxy=proxy_retail)
    else:
        usd["retail"] = _missing("retail", "Data o malých obchodnících chybí.")

    # Seasonality — the last 10 years
    gold_rets = monthly_returns({m: v for m, v in inputs.gold_monthly.items()
                                 if live or dt.date(int(m[:4]), int(m[5:]), 1) + dt.timedelta(days=35) <= day})
    sg = seasonality_score(gold_rets, day)
    if sg:
        s, st = sg
        xau["seasonality"] = _component(
            "seasonality", s, f"Zlato v měsíci {MONTHS_CZ[day.month - 1]}: průměr {_num(st['avg'], 1, True)} %, růst v {_num(st['win'], 0)} % let ({st['from']}–{st['to']}).",
            [{"name": "10letý průměr měsíce", "value": f"{_num(st['avg'], 2, True)} %", "as_of": st["to"]}])
    else:
        xau["seasonality"] = _missing("seasonality", "Chybí měsíční historie cen.")
    usd_rets = monthly_returns(daily_monthly_avg({d: v for d, v in inputs.usd_daily.items() if d <= day.isoformat()}))
    su = seasonality_score(usd_rets, day)
    if su:
        s, st = su
        usd["seasonality"] = _component(
            "seasonality", s, f"Dolar (DXY) v měsíci {MONTHS_CZ[day.month - 1]}: průměr {_num(st['avg'], 1, True)} %, růst v {_num(st['win'], 0)} % let.",
            [{"name": "10letý průměr měsíce", "value": f"{_num(st['avg'], 2, True)} %", "as_of": st["to"]}])
    else:
        usd["seasonality"] = _missing("seasonality", "Chybí historie dolaru.")

    # Trend
    for side, d1, w1, name in (("xau", inputs.gold_d1, inputs.gold_w1, "Zlato"), ("usd", inputs.dxy_d1, inputs.dxy_w1, "Dolar")):
        t = trend_score(d1, w1, asof)
        target = xau if side == "xau" else usd
        if t:
            s, ti = t
            rev = " Pozor: divergence RSI naznačuje možný obrat, skóre zmírněno." if ti["reversal"] else ""
            target["trend"] = _component("trend", s, f"{name}: denní trend {(ti['d1'] or '—').lower()}, týdenní {(ti['w1'] or '—').lower()}.{rev}",
                                         [{"name": "Směs D1 + W1", "value": _num(ti["blend"], 2, True), "as_of": asof.date().isoformat()}])
        else:
            target["trend"] = _missing("trend", "Málo svíček pro trend.")

    def pack(side: dict[str, dict]) -> dict:
        comps = [side[key] for key in ORDER]
        total = sum(c["score"] for c in comps if c["score"] is not None)
        missing = [c["label"] for c in comps if c["score"] is None]
        return {"components": comps, "total": total, "max": MAX_TOTAL, "missing": missing, **_verdict(total)}

    return {"as_of": asof.isoformat(), "xau": pack(xau), "usd": pack(usd)}


MONTHS_CZ = ["leden", "únor", "březen", "duben", "květen", "červen", "červenec", "srpen", "září", "říjen", "listopad", "prosinec"]


def backfill(inputs: TraInputs, days: int, now: dt.datetime) -> list[dict]:
    """One point per day (21:00 UTC, after the New York close) for the last `days` days, oldest first."""
    known = _known(inputs)
    out = []
    start = (now - dt.timedelta(days=days)).replace(hour=21, minute=0, second=0, microsecond=0)
    t = start
    while t < now - dt.timedelta(hours=12):
        if t.weekday() < 5:
            res = compute(inputs, t, known)
            out.append({"t": t, "xau": res["xau"], "usd": res["usd"]})
        t += dt.timedelta(days=1)
    return out
