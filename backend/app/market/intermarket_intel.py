"""Intermarket Intelligence — how gold moves together with the other markets, measured on FTI's own synchronised data.

Nothing here is a textbook rule written in advance: every relationship is a correlation of real RETURNS (never of
price levels — two trending prices correlate by accident), with its window, number of observations, effective number
of observations after autocorrelation, significance, stability over time, recent change, a possible breakdown, whether
the other market now confirms or contradicts gold's move, the time of the last common observation, the sources and the
data quality. All market pairs are also scanned for relationships nobody listed (Benjamini–Hochberg correction), and
lead/lag is tested. A correlation is co-movement, never proof that one market causes the other.

Synchronisation (the user's rule: no correlation of series that are not synchronised):
  M15 / M30 / H1 / H4  only closes at the SAME UTC instant; a return runs between consecutive common instants, so both
      markets are measured over exactly the same interval. M30 and H4 are built from M15 and H1 only when the bar's last
      constituent exists (otherwise its close would be from an earlier moment and the markets would not be aligned).
  D1  closes of the same US trading day: 17:00 New York (the hourly bar ending exactly then; MT5's broker day ends then),
      official closes of the same day (S&P 500 16:00, VIX 16:15, Treasury yields ~15:30, WTI 14:30 — the offset is shown).
      ECB fixings (14:15 Frankfurt = 8:15 New York) and Dukascopy's midnight-UTC daily bars are not used.
Statistics: Pearson r of log returns (yields: changes in basis points); p and the 95 % interval by Fisher's z with the
EFFECTIVE number of observations (Bartlett: n / (1 + 2 Σ ρx(k)·ρy(k)), autocorrelated series count for fewer independent
observations); q-values by Benjamini–Hochberg wherever many relationships are tested at once.
No look-ahead: with `as_of` every number uses only data up to that moment; the breakdown compares windows that both end
at the latest point; the yardstick of "confirms / contradicts" is measured BEFORE the move it judges.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc
TF_S = {"M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
# every window ≥ MIN_N, or it could never be computed
WINDOWS = {"M15": (96, 480, 1440), "M30": (48, 240, 720), "H1": (48, 120, 480), "H4": (30, 120, 360),
           "D1": (30, 60, 120, 250)}
MAIN = {"M15": 480, "M30": 240, "H1": 120, "H4": 120, "D1": 60}  # stability, change, breakdown, discovery
LONG = {"M15": 1440, "M30": 720, "H1": 480, "H4": 360, "D1": 250}
MOVE_BARS = {"M15": 32, "M30": 16, "H1": 24, "H4": 6, "D1": 5}  # gold's recent move (8 h / 8 h / 1 d / 1 d / 1 week)
MAX_GAP_S = 4 * 86400  # a return over a longer pause (holiday) is not used
MAX_GAP_D1 = 6
MIN_N = 30
ACF_LAGS = 10
CAUSALITY = ("Korelace měří souběh pohybů, ne příčinu: dva trhy se mohou hýbat společně kvůli třetímu vlivu "
             "a vztah se může kdykoli změnit.")
CACHE_KEY = "intermarket:intel:{tf}"
HISTORY_KEY = "intermarket:history:{tf}"
HISTORY_KEEP = 60
TTL_S = 35 * 60
# pairs related by construction or by being the same market — shown, but never sold as a discovery
RELATED = [({"US10Y", "US10YR"}, "nominální a reálný výnos 10 let se liší jen o očekávanou inflaci"),
           ({"US10Y", "US02Y"}, "dva body téže výnosové křivky"), ({"US02Y", "US10YR"}, "body téže výnosové křivky"),
           ({"USOIL", "UKOIL"}, "dva druhy téže suroviny"), ({"US500", "VIX"}, "VIX se počítá z opcí na S&P 500"),
           ({"DXY", "EURUSD"}, "euro tvoří 57,6 % dolarového indexu"), ({"DXY", "USDJPY"}, "jen je součástí dolarového indexu"),
           ({"USTBOND", "US10Y"}, "cena dluhopisu a výnos jsou dvě strany téhož")]


@dataclass
class Series:
    key: str
    code: str
    label: str
    source: str
    kind: str  # price | vol | yield
    proxy: bool  # a CFD on futures: moves with the market, its level is not the official one
    close_ny: float  # hour of the close in New York (daily sync); 0 = the intraday grid
    points: dict = field(default_factory=dict)  # intraday: unix start -> close; D1: "YYYY-MM-DD" -> close
    category: str = ""  # spot FX | spot kov | CFD | vypočtený index | oficiální výnos | oficiální index | spot komodita

    @property
    def last(self):
        return max(self.points) if self.points else None

    @property
    def base(self) -> str:
        return self.code.replace(".CFD", "").replace("*", "")


# ------------------------------------------------------------------------------------------------- statistics (pure)

def pearson(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx <= 0 or syy <= 0:
        return None
    return max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))


def acf(x: list[float], k: int) -> float:
    n = len(x)
    if n <= k + 2:
        return 0.0
    m = sum(x) / n
    den = sum((a - m) ** 2 for a in x)
    if den <= 0:
        return 0.0
    return sum((x[i] - m) * (x[i + k] - m) for i in range(n - k)) / den


def n_effective(x: list[float], y: list[float], lags: int = ACF_LAGS) -> float:
    """Bartlett's effective number of independent observations for a correlation of two autocorrelated series."""
    n = len(x)
    if n < 4:
        return float(n)
    s = sum(acf(x, k) * acf(y, k) for k in range(1, min(lags, n // 4) + 1))
    return max(3.0, min(float(n), n / max(1e-9, 1 + 2 * s)))


def p_value(r: float, n: float) -> float:
    """Two-sided p of r = 0 (Fisher z, normal approximation — fine from n ≈ 30)."""
    if n <= 3 or abs(r) >= 1:
        return 0.0 if abs(r) >= 1 else 1.0
    z = math.atanh(r) * math.sqrt(n - 3)
    return math.erfc(abs(z) / math.sqrt(2))


def ci95(r: float, n: float) -> list[float] | None:
    if n <= 3 or abs(r) >= 1:
        return None
    z, se = math.atanh(r), 1 / math.sqrt(n - 3)
    return [round(math.tanh(z - 1.96 * se), 3), round(math.tanh(z + 1.96 * se), 3)]


def fisher_diff_p(r1: float, n1: float, r2: float, n2: float) -> float:
    """p of 'the two correlations are equal'."""
    if min(n1, n2) <= 3:
        return 1.0
    r1, r2 = max(-0.999, min(0.999, r1)), max(-0.999, min(0.999, r2))
    z = (math.atanh(r1) - math.atanh(r2)) / math.sqrt(1 / (n1 - 3) + 1 / (n2 - 3))
    return math.erfc(abs(z) / math.sqrt(2))


def bh(pvals: list[float]) -> list[float]:
    """Benjamini–Hochberg q-values: many pairs tested at once must not produce lucky 'discoveries'."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [1.0] * m
    best = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        best = min(best, pvals[i] * m / rank)
        q[i] = best
    return q


def strength(r: float) -> str:
    a = abs(r)
    word = ("zanedbatelná" if a < 0.2 else "slabá" if a < 0.4 else "střední" if a < 0.6 else "silná" if a < 0.8 else "velmi silná")
    return f"{word} {'kladná' if r > 0 else 'záporná'}" if a >= 0.2 else word


def sufficiency(n: int) -> str:
    return ("nedostatek pozorování" if n < MIN_N else "omezený počet pozorování" if n < 60 else
            "dostatečný počet pozorování" if n < 120 else "dobrý počet pozorování")


def related(a: Series, b: Series) -> str | None:
    pair = {a.base, b.base}
    if a.base == b.base:
        return "tentýž trh z jiného zdroje"
    return next((why for keys, why in RELATED if keys == pair), None)


def corr_stats(x: list[float], y: list[float]) -> dict | None:
    r = pearson(x, y)
    if r is None:
        return None
    ne = n_effective(x, y)
    return {"r": r, "n": len(x), "n_eff": ne, "p": p_value(r, ne), "ci95": ci95(r, ne)}


# ------------------------------------------------------------------------------------------ synchronised returns

def _gap_ok(k0, k1, tf: str) -> bool:
    if tf == "D1":
        return (dt.date.fromisoformat(k1) - dt.date.fromisoformat(k0)).days <= MAX_GAP_D1
    return k1 - k0 <= MAX_GAP_S


def _ret(v0: float, v1: float, kind: str) -> float | None:
    if kind == "yield":
        return (v1 - v0) * 100  # basis points
    if v0 <= 0 or v1 <= 0:
        return None
    return math.log(v1 / v0)


def aligned_returns(a: Series, b: Series, tf: str) -> tuple[list, list[float], list[float]]:
    """(end keys, returns of a, returns of b) over the SAME intervals: consecutive keys common to both series."""
    keys = sorted(set(a.points) & set(b.points))
    ks, ra, rb = [], [], []
    for k0, k1 in zip(keys, keys[1:]):
        if not _gap_ok(k0, k1, tf):
            continue
        x = _ret(a.points[k0], a.points[k1], a.kind)
        y = _ret(b.points[k0], b.points[k1], b.kind)
        if x is None or y is None:
            continue
        ks.append(k1)
        ra.append(x)
        rb.append(y)
    return ks, ra, rb


def _key_iso(k, tf: str) -> str:
    return f"{k}T22:00:00+00:00" if tf == "D1" else dt.datetime.fromtimestamp(k + TF_S[tf], UTC).isoformat()


def analyze(a: Series, b: Series, tf: str, now: dt.datetime | None = None) -> dict:
    """Every measured property of the relationship between `a` (gold) and `b`."""
    ks, x, y = aligned_returns(a, b, tf)
    n_all = len(x)
    wins = []
    for w in WINDOWS[tf]:
        n = min(w, n_all)
        st = corr_stats(x[-n:], y[-n:]) if n >= MIN_N else None
        wins.append({"window": w, "n": n, "n_eff": round(st["n_eff"], 1) if st else None,
                     "r": round(st["r"], 3) if st else None, "p": round(st["p"], 6) if st else None,
                     "ci95": st["ci95"] if st else None, "strength": strength(st["r"]) if st else "nepočítá se",
                     "sufficiency": sufficiency(n), "full_window": n == w})
    main, long_w = MAIN[tf], LONG[tf]
    out = {"a": a.key, "b": b.key, "b_code": b.code, "label": b.label, "category": b.category, "tf": tf,
           "observations_total": n_all, "windows": wins, "last_common": _key_iso(ks[-1], tf) if ks else None,
           "sources": [a.source, b.source], "proxy": b.proxy or a.proxy, "kind": b.kind, "related": related(a, b),
           "causality": CAUSALITY}
    if n_all >= main + MIN_N:  # stability of the main window over time (rolling, step = window / 5)
        step = max(1, main // 5)
        roll = [pearson(x[i - main:i], y[i - main:i]) for i in range(main, n_all + 1, step)]
        roll = [r for r in roll if r is not None][-40:]
        cur = roll[-1]
        same = sum(1 for r in roll if (r > 0) == (cur > 0)) / len(roll)
        mean = sum(roll) / len(roll)
        out["stability"] = {"window": main, "rolling_points": len(roll), "mean": round(mean, 3),
                            "sd": round(math.sqrt(sum((r - mean) ** 2 for r in roll) / len(roll)), 3),
                            "min": round(min(roll), 3), "max": round(max(roll), 3), "same_sign_share": round(same, 2),
                            "verdict": ("stabilní" if same >= 0.85 and abs(mean) >= 0.2 else
                                        "proměnlivý" if same < 0.65 else "převážně stejný směr")}
    if n_all >= 2 * main:  # change: the last main window against the one before it (no overlap)
        s_now, s_prev = corr_stats(x[-main:], y[-main:]), corr_stats(x[-2 * main:-main], y[-2 * main:-main])
        if s_now and s_prev:
            p = fisher_diff_p(s_now["r"], s_now["n_eff"], s_prev["r"], s_prev["n_eff"])
            out["change"] = {"window": main, "r_now": round(s_now["r"], 3), "r_prev": round(s_prev["r"], 3),
                             "now_until": _key_iso(ks[-1], tf), "prev_until": _key_iso(ks[-main - 1], tf),
                             "delta": round(s_now["r"] - s_prev["r"], 3), "p": round(p, 4), "significant": p < 0.05}
    short = WINDOWS[tf][0] if tf == "D1" else WINDOWS[tf][1]
    if n_all >= long_w:  # breakdown: a firm long-window relationship that the short window no longer shows
        s_l, s_s = corr_stats(x[-long_w:], y[-long_w:]), corr_stats(x[-short:], y[-short:])
        if s_l and s_s:
            r_l, r_s = s_l["r"], s_s["r"]
            p_d = fisher_diff_p(r_s, s_s["n_eff"], r_l, s_l["n_eff"])
            if abs(r_l) >= 0.4 and s_l["p"] < 0.01:
                state = ("obrat" if (r_s > 0) != (r_l > 0) and abs(r_s) >= 0.2 else
                         "rozpad" if abs(r_s) < 0.15 or (abs(r_s) < abs(r_l) / 2 and p_d < 0.05) else "drží")
            elif abs(r_s) >= 0.5 and s_s["p"] < 0.01:
                state = "nový vztah"
            else:
                state = "bez pevného dlouhodobého vztahu"
            out["breakdown"] = {"state": state, "short_window": short, "r_short": round(r_s, 3), "long_window": long_w,
                                "r_long": round(r_l, 3), "p_difference": round(p_d, 4)}
    else:
        out["breakdown"] = {"state": "málo historie", "short_window": short, "long_window": long_w,
                            "text": f"rozpad lze posoudit od {long_w} společných pozorování, je jich {n_all}"}
    k = MOVE_BARS[tf]
    # the relationship is judged on the window BEFORE the move, so the move itself cannot shape its own yardstick
    n_ref = min(main, n_all - k)
    st_ref = corr_stats(x[-(n_ref + k):-k], y[-(n_ref + k):-k]) if n_ref >= MIN_N else None
    if st_ref:
        gm, om = sum(x[-k:]), sum(y[-k:])
        sd_g, sd_o = _sd(x[:-k]) * math.sqrt(k), _sd(y[:-k]) * math.sqrt(k)
        unit = "b. b." if b.kind == "yield" else "%"
        other = round(om, 2) if b.kind == "yield" else round((math.exp(om) - 1) * 100, 3)
        mv = {"bars": k, "until": _key_iso(ks[-1], tf), "from": _key_iso(ks[-k - 1], tf) if len(ks) > k else None,
              "gold_pct": round((math.exp(gm) - 1) * 100, 3), "other": other, "other_unit": unit,
              "r_used": round(st_ref["r"], 3), "p_used": round(st_ref["p"], 5), "window_used": n_ref,
              "window_note": f"korelace z {n_ref} období před posledním pohybem"}
        if abs(st_ref["r"]) < 0.3 or st_ref["p"] >= 0.01:
            mv.update(verdict="nelze", text="vztah není dost pevný na to, aby potvrzoval nebo vyvracel pohyb zlata")
        elif abs(gm) < 0.25 * sd_g:
            mv.update(verdict="neutrální", text="zlato se za toto období výrazně nepohnulo")
        elif abs(om) < 0.25 * sd_o:
            mv.update(verdict="neutrální", text="trh se nepohnul natolik, aby něco potvrzoval")
        else:
            expected = (gm > 0) == (st_ref["r"] > 0)
            agrees = (om > 0) == expected
            mv.update(verdict="potvrzuje" if agrees else "odporuje",
                      text=("pohybuje se tak, jak by podle dosavadní korelace odpovídalo pohybu zlata" if agrees else
                            "pohybuje se opačně, než by podle dosavadní korelace odpovídalo pohybu zlata"))
        out["move"] = mv
    out["quality"] = _quality(a, b, wins, ks, tf)
    return out


def _sd(v: list[float]) -> float:
    if len(v) < 2:
        return 0.0
    m = sum(v) / len(v)
    return math.sqrt(sum((a - m) ** 2 for a in v) / (len(v) - 1))


def _quality(a: Series, b: Series, wins: list[dict], ks: list, tf: str) -> dict:
    issues = []
    if b.proxy:
        issues.append("CFD na futures — hýbe se s trhem, úroveň není oficiální hodnota")
    if b.category == "vypočtený index":
        issues.append("vypočtený index (vzorec ICE z kurzů), ne oficiální kotace")
    main = next(w for w in wins if w["window"] == MAIN[tf])
    if main["n"] < MIN_N:
        issues.append(f"jen {main['n']} společných pozorování (minimum {MIN_N})")
    elif main["n_eff"] is not None and main["n_eff"] < 0.7 * main["n"]:
        issues.append(f"autokorelace: efektivně jen {main['n_eff']:.0f} nezávislých pozorování z {main['n']}".replace(".", ","))
    if ks:
        common = len(ks)
        if common < 0.6 * min(len(a.points), len(b.points)):
            issues.append(f"společných období je jen {common} z {min(len(a.points), len(b.points))}")
        newest = a.last
        lag = ((dt.date.fromisoformat(newest) - dt.date.fromisoformat(ks[-1])).days if tf == "D1" else (newest - ks[-1]) / 86400)
        if lag > (3 if tf == "D1" else 2):
            issues.append("druhý trh nemá data až do konce historie zlata (zastaralá řada)")
    if tf == "D1" and abs(a.close_ny - b.close_ny) >= 0.5:
        issues.append(f"uzávěrky téhož dne s posunem {abs(a.close_ny - b.close_ny):.1f} h".replace(".", ","))
    label = ("nedostatečná" if main["n"] < MIN_N else "omezená" if len(issues) >= 2 or main["n"] < 60 else
             "dobrá" if not issues else "použitelná")
    return {"label": label, "issues": issues}


# ------------------------------------------------------------------------------------- building synchronised bars

def ny_close_daily(hourly: dict[int, float]) -> dict[str, float]:
    """Daily close at 17:00 New York: the hourly bar that ENDS exactly at 17:00 NY — a day without it has no close
    (an earlier hour would be a different moment, and the markets would no longer be compared at the same instant)."""
    out: dict[str, float] = {}
    for t, c in hourly.items():
        end = dt.datetime.fromtimestamp(t + 3600, UTC).astimezone(NY)
        if end.weekday() < 5 and end.hour == 17 and end.minute == 0:
            out[end.date().isoformat()] = c
    return dict(sorted(out.items()))


def resample_close(points: dict[int, float], src_s: int, dst_s: int) -> dict[int, float]:
    """Closes of `dst_s` bars from `src_s` bars (UTC grid), only where the bar's LAST constituent exists."""
    out = {}
    for t, c in points.items():
        start = t - t % dst_s
        if t == start + dst_s - src_s:
            out[start] = c
    return dict(sorted(out.items()))


def mt5_trading_day(t: int) -> str:
    """MT5's daily bar starts at 17:00 New York the evening before: its trading day is the next New York date."""
    return (dt.datetime.fromtimestamp(t, UTC).astimezone(NY) + dt.timedelta(hours=7)).date().isoformat()


# ICE US Dollar Index: 50.14348112 × EURUSD^-0.576 × USDJPY^0.136 × GBPUSD^-0.119 × USDCAD^0.091 × USDSEK^0.042 × USDCHF^0.036
DXY_WEIGHTS = {"EURUSD": -0.576, "USDJPY": 0.136, "GBPUSD": -0.119, "USDCAD": 0.091, "USDSEK": 0.042, "USDCHF": 0.036}


def dxy_points(fx: dict[str, dict], eursek: dict[str, float], tf: str) -> dict:
    """DXY* by ICE's formula at the instants where all five broker FX closes exist; USD/SEK = EUR/SEK (ECB fixing of
    that date or the last one before) / EUR/USD of the same instant. Nothing is computed where a rate is missing."""
    need = [c for c in DXY_WEIGHTS if c != "USDSEK"]
    if any(c not in fx for c in need) or not eursek:
        return {}
    days = sorted(eursek)
    keys = set.intersection(*(set(fx[c]) for c in need))
    out = {}
    import bisect

    for k in sorted(keys):
        d = k if tf == "D1" else dt.datetime.fromtimestamp(k, UTC).date().isoformat()
        i = bisect.bisect_right(days, d) - 1
        if i < 0 or (dt.date.fromisoformat(d) - dt.date.fromisoformat(days[i])).days > 5:
            continue
        rates = {c: fx[c][k] for c in need}
        rates["USDSEK"] = eursek[days[i]] / rates["EURUSD"]
        out[k] = 50.14348112 * math.prod(rates[c] ** w for c, w in DXY_WEIGHTS.items())
    return out


# ------------------------------------------------------------------------------------------------- loading data

CLOSE_NY = {"treasury": 15.5, "cboe": 16.25, "fred": 16.0, "eia": 14.5, "ny": 17.0, "mt5": 17.0}
OFFICIAL_D1 = [("US10Y", "treasury", "Výnos 10letých dluhopisů USA (nominální)", "yield", "oficiální výnos"),
               ("US02Y", "treasury", "Výnos 2letých dluhopisů USA", "yield", "oficiální výnos"),
               ("US10YR", "treasury", "Reálný výnos 10 let (TIPS)", "yield", "oficiální výnos"),
               ("VIX", "cboe", "VIX (oficiální, CBOE)", "vol", "oficiální index"),
               ("US500", "fred", "S&P 500 (oficiální uzávěrka)", "price", "oficiální index"),
               ("USOIL", "eia", "Ropa WTI spot Cushing (EIA)", "price", "spot komodita")]
FXCM_CODES = {"EURUSD": ("EUR/USD", "spot FX"), "USDJPY": ("USD/JPY", "spot FX")}  # the other three only feed DXY*
SOURCE_NAME = {"dukascopy": "Dukascopy (bid, UTC)", "fxcm": "FXCM archiv (bid, UTC, týden se zpožděním)",
               "mt5": "MT5 broker Purple (historie)", "treasury": "US Treasury",
               "cboe": "CBOE", "fred": "FRED (S&P Dow Jones Indices)", "eia": "EIA"}
MT5_CODES = {"XAUUSD": ("Zlato (XAU/USD)", "spot kov"), "EURUSD": ("EUR/USD", "spot FX"), "USDJPY": ("USD/JPY", "spot FX"),
             "US500.CFD": ("S&P 500 (CFD)", "CFD"), "USOIL.CFD": ("Ropa WTI (CFD)", "CFD"), "UKOIL.CFD": ("Ropa Brent (CFD)", "CFD")}
DXY_FX = ("EURUSD", "USDJPY", "GBPUSD", "USDCAD", "USDCHF")


def _rows(session, code: str, provider: str, tf: str, as_of: int | None) -> list[tuple[int, float]]:
    from sqlalchemy import select

    from app.models import MarketBar

    q = select(MarketBar.t, MarketBar.c).where(MarketBar.code == code, MarketBar.provider == provider, MarketBar.tf == tf,
                                               MarketBar.closed.is_(True))
    if as_of is not None:  # point in time: a bar counts only once it had closed by `as_of`
        q = q.where(MarketBar.t + TF_S.get(tf, 0) <= as_of)
    return [(int(t), float(c)) for t, c in session.execute(q.order_by(MarketBar.t))]


def _intraday(session, code: str, provider: str, tf: str, as_of: int | None) -> dict[int, float]:
    if tf in ("M15", "H1"):
        return dict(_rows(session, code, provider, tf, as_of))
    if tf == "M30":
        return resample_close(dict(_rows(session, code, provider, "M15", as_of)), 900, 1800)
    if tf == "H4":
        return resample_close(dict(_rows(session, code, provider, "H1", as_of)), 3600, 14400)
    raise ValueError(tf)


def _eursek(as_of_date: str | None) -> dict[str, float]:
    try:
        from app.connectors import ecb

        rates = ecb.fetch_history(dt.datetime.now(UTC))
    except Exception:  # noqa: BLE001 — without the fixing there is no DXY*, the rest still works
        return {}
    return {d: v["SEK"] for d, v in rates.items() if "SEK" in v and (as_of_date is None or d <= as_of_date)}


def load(session, tf: str, as_of: dt.datetime | None = None) -> list[Series]:
    from app.market import intermarket_data as imd

    cut = int(as_of.timestamp()) if as_of else None
    out: list[Series] = []
    for code, (sym, label, kind, proxy) in imd.FEEDS.items():
        src_tf = "H1" if tf == "D1" else tf
        pts = _intraday(session, code, "dukascopy", src_tf, cut)
        if tf == "D1":
            pts = {d: c for d, c in ny_close_daily(pts).items() if not as_of or f"{d}T22:00:00+00:00" <= as_of.isoformat()}
        if pts:
            out.append(Series(f"{code}@dukascopy", code, label, SOURCE_NAME["dukascopy"] + (f" {sym}" if proxy else ""), kind,
                              proxy, CLOSE_NY["ny"], pts, "CFD" if proxy else imd.CATEGORY.get(code, "spot")))
    eursek = _eursek(as_of.date().isoformat() if as_of else None)
    from app.connectors import fxcm

    fx_fxcm: dict[str, dict] = {}
    for code in fxcm.SYMBOLS:  # FXCM's archive: an independent dealer on the same UTC hour grid as Dukascopy
        pts = _intraday(session, code, "fxcm", "H1" if tf == "D1" else tf, cut)
        if tf == "D1":
            pts = {d: c for d, c in ny_close_daily(pts).items() if not as_of or f"{d}T22:00:00+00:00" <= as_of.isoformat()}
        if pts:
            fx_fxcm[code] = pts
        if code in FXCM_CODES and pts:
            label, cat = FXCM_CODES[code]
            out.append(Series(f"{code}@fxcm", code, label, SOURCE_NAME["fxcm"], "price", False, CLOSE_NY["ny"], pts, cat))
    dxy = dxy_points(fx_fxcm, eursek, tf)
    if dxy:
        out.append(Series("DXY*@fxcm", "DXY*", "Dolarový index DXY* (vzorec ICE z kurzů FXCM, SEK z fixingu ECB)",
                          "výpočet FTI z FXCM + ECB", "price", False, CLOSE_NY["ny"], dxy, "vypočtený index"))
    fx: dict[str, dict] = {}
    for code in set(MT5_CODES) | set(DXY_FX):
        if tf == "D1":
            pts = {mt5_trading_day(t): c for t, c in _rows(session, code, "mt5", "D1", cut)}
        else:
            pts = _intraday(session, code, "mt5", tf, cut)
        if code in DXY_FX and pts:
            fx[code] = pts
        if code in MT5_CODES and pts:
            label, cat = MT5_CODES[code]
            out.append(Series(f"{code}@mt5", code, label, SOURCE_NAME["mt5"], "price", code.endswith(".CFD"), CLOSE_NY["mt5"], pts, cat))
    dxy = dxy_points(fx, eursek, tf)
    if dxy:
        out.append(Series("DXY*@mt5", "DXY*", "Dolarový index DXY* (vzorec ICE z kurzů brokera, SEK z fixingu ECB)",
                          "výpočet FTI z MT5 + ECB", "price", False, CLOSE_NY["mt5"], dxy, "vypočtený index"))
    if tf == "D1":
        for code, prov, label, kind, cat in OFFICIAL_D1:
            pts = {dt.datetime.fromtimestamp(t, UTC).date().isoformat(): c for t, c in _rows(session, code, prov, "D1", None)}
            if as_of:
                pts = {d: c for d, c in pts.items() if d < as_of.date().isoformat() or (d == as_of.date().isoformat() and
                                                                                         as_of.astimezone(NY).hour >= 17)}
            if pts:
                out.append(Series(f"{code}@{prov}", code, label, SOURCE_NAME[prov], kind, False, CLOSE_NY[prov], pts, cat))
    return [s for s in out if len(s.points) >= MIN_N + 1]


RANK = {"dukascopy": 1, "fxcm": 2, "treasury": 3, "cboe": 3, "fred": 3, "eia": 3, "mt5": 4}
STALE_S = {"M15": 86400, "M30": 86400, "H1": 86400, "H4": 86400, "D1": 3 * 86400}


def _end_ts(s: Series, tf: str) -> float:
    last = s.last
    return dt.datetime.fromisoformat(last).replace(tzinfo=UTC).timestamp() if tf == "D1" else float(last)


def _primary(series: list[Series], tf: str = "H1") -> list[Series]:
    """One series per market: a source that is not behind the market's freshest one, then by source — Dukascopy (every
    market on one UTC grid), FXCM (the same grid, a week late), the official closes (other close times), MT5. DXY*
    (ICE's formula from spot rates) goes before the dollar-index CFD of the same source rank."""
    groups: dict[str, list[Series]] = {}
    for s in series:
        groups.setdefault(s.base, []).append(s)
    out = []
    for ss in groups.values():
        newest = max(_end_ts(s, tf) for s in ss)
        out.append(min(ss, key=lambda s: (newest - _end_ts(s, tf) > STALE_S[tf],
                                          RANK[s.key.split("@")[1]] - (1.5 if "*" in s.code else 0), -len(s.points), s.key)))
    return out


def fingerprint(series: list[Series]) -> str:
    """Changes exactly when an input changes (new bar, revised close) — the correlations are recomputed only then."""
    h = hashlib.sha1()
    for s in sorted(series, key=lambda s: s.key):
        keys = sorted(s.points)
        h.update(f"{s.key}|{len(keys)}|{keys[-1]}|{sum(s.points[k] for k in keys[-20:]):.8f}".encode())
    return h.hexdigest()[:16]


def series_report(series: list[Series], tf: str) -> list[dict]:
    """The data each correlation stands on: observations, first / last, gaps beyond normal market pauses."""
    out = []
    for s in series:
        keys = sorted(s.points)
        if tf == "D1":
            gaps = sum(1 for a, b in zip(keys, keys[1:]) if (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days > 4)
        else:
            gaps = sum(1 for a, b in zip(keys, keys[1:]) if b - a > 3 * 86400)
        out.append({"key": s.key, "label": s.label, "category": s.category, "source": s.source, "kind": s.kind, "proxy": s.proxy,
                    "observations": len(keys), "first": _iso(keys[0], tf), "last": _iso(keys[-1], tf),
                    "gaps_over_market_pause": gaps})
    return out


def _iso(k, tf: str) -> str:
    return k if tf == "D1" else dt.datetime.fromtimestamp(k, UTC).isoformat()


# ---------------------------------------------------------------------------------------------------- the module

def compute(session, tf: str = "D1", target: str = "XAUUSD", now: dt.datetime | None = None,
            as_of: dt.datetime | None = None) -> dict:
    """Deterministic: the same data (and `as_of`) always give the same numbers."""
    now = now or dt.datetime.now(UTC)
    series = load(session, tf, as_of)
    gold = [s for s in series if s.code == target]
    if not gold:
        return {"tf": tf, "computed_at": now.isoformat(), "as_of": as_of.isoformat() if as_of else None,
                "error": f"Pro {target} nejsou synchronizovaná data {tf}.", "relations": [], "series": series_report(series, tf)}
    gold.sort(key=lambda s: (s.key.split("@")[1] != "dukascopy", -len(s.points)))
    g = gold[0] if len(gold[0].points) >= MAIN[tf] + MOVE_BARS[tf] or len(gold) == 1 else gold[1]
    prim = _primary(series, tf)
    relations = [analyze(g, s, tf, now) for s in prim if s.base != g.base]  # one row per market: its best source
    for rel, q in zip(relations, bh([next((w["p"] for w in r["windows"] if w["window"] == MAIN[tf] and w["p"] is not None), 1.0)
                                     for r in relations])):
        rel["q_main"] = round(q, 6)  # the main table tests many markets at once, too
    # the same market from another source should move the same way (r ≈ 1): a check of the sources, not a relationship
    checks = [analyze(g, s, tf, now) for s in gold if s is not g]
    checks += [analyze(p, s, tf, now) for p in prim if p.base != g.base for s in series
               if s.base == p.base and s is not p]
    relations.sort(key=lambda r: -abs(next((w["r"] for w in r["windows"] if w["window"] == MAIN[tf] and w["r"] is not None), 0) or 0))
    disc = discover(prim, tf)
    lead = lead_lag(g, [s for s in prim if s.code != target], tf)
    confirm = [{"market": r["label"], "source": r["b"].split("@")[1], **{k: r["move"][k] for k in ("verdict", "text", "other",
                                                                                                    "other_unit", "r_used")}}
               for r in relations if r.get("move", {}).get("verdict") in ("potvrzuje", "odporuje")]
    return {"tf": tf, "target": g.key, "target_label": g.label, "computed_at": now.isoformat(),
            "as_of": as_of.isoformat() if as_of else None, "fingerprint": fingerprint(series), "windows": list(WINDOWS[tf]),
            "main_window": MAIN[tf], "series": series_report(series, tf), "relations": relations, "source_checks": checks,
            "confirmation": confirm, "discovered": disc, "lead_lag": lead,
            "method": ("Pearsonova korelace synchronizovaných výnosů (log; u výnosů dluhopisů změna v b. b.); p-hodnota a 95% "
                       "interval Fisherovou transformací s efektivním počtem pozorování (Bartlett, autokorelace do 10 zpoždění); "
                       f"q-hodnoty Benjamini–Hochberg; minimum {MIN_N} pozorování; bez dat po okamžiku výpočtu."),
            "causality": CAUSALITY}


def discover(series: list[Series], tf: str, top: int = 15) -> list[dict]:
    """All market pairs on the main window — the relationships the data show, not the ones written in advance. Pairs
    related by construction are kept but marked, so they are never sold as a discovery."""
    pairs = []
    for i, a in enumerate(series):
        for b in series[i + 1:]:
            ks, x, y = aligned_returns(a, b, tf)
            n = min(MAIN[tf], len(x))
            if n < MIN_N:
                continue
            st = corr_stats(x[-n:], y[-n:])
            if st is None:
                continue
            pairs.append({"a": a.label, "b": b.label, "a_key": a.key, "b_key": b.key, "window": MAIN[tf], "n": n,
                          "n_eff": round(st["n_eff"], 1), "r": round(st["r"], 3), "p": st["p"], "strength": strength(st["r"]),
                          "last_common": _key_iso(ks[-1], tf), "proxy": a.proxy or b.proxy, "related": related(a, b)})
    for p, q in zip(pairs, bh([p["p"] for p in pairs])):
        p["q"] = round(q, 6)
        p["p"] = round(p["p"], 8)
    found = [p for p in pairs if p["q"] < 0.05 and abs(p["r"]) >= 0.3]
    return sorted(found, key=lambda p: (p["related"] is not None, -abs(p["r"])))[:top]


def lead_lag(g: Series, others: list[Series], tf: str, lags: tuple[int, ...] = (1, 2, 3)) -> list[dict]:
    """Does another market's move precede gold's? corr(gold now, market `lag` bars earlier), corrected for many tests."""
    tests = []
    for s in others:
        ks, x, y = aligned_returns(g, s, tf)
        n_use = min(len(x), LONG[tf])
        x, y = x[-n_use:], y[-n_use:]
        for lag in lags:
            if len(x) - lag < MIN_N:
                continue
            st = corr_stats(x[lag:], y[:-lag])
            if st:
                tests.append({"market": s.label, "key": s.key, "lag": lag, "n": st["n"], "n_eff": round(st["n_eff"], 1),
                              "r": round(st["r"], 3), "p": st["p"]})
    for t, q in zip(tests, bh([t["p"] for t in tests])):
        t["q"] = round(q, 6)
        t["p"] = round(t["p"], 8)
    hits = [t for t in tests if t["q"] < 0.05 and abs(t["r"]) >= 0.1]
    unit = {"M15": "× 15 min", "M30": "× 30 min", "H1": "h", "H4": "× 4 h", "D1": "d"}[tf]
    for t in hits:
        t["text"] = (f"{t['market']} o {t['lag']} {unit} dříve souvisí s pohybem zlata (r = {t['r']:+.2f}) — statistický souběh, "
                     "ne spolehlivá předpověď.")
    return sorted(hits, key=lambda t: -abs(t["r"]))


# ---------------------------------------------------------------------------------------- results: stored, reused

_mem: dict[str, tuple[float, dict]] = {}


def _summary(res: dict) -> dict:
    main = res.get("main_window")
    return {"computed_at": res["computed_at"], "as_of": res.get("as_of"), "fingerprint": res.get("fingerprint"),
            "relations": {r["b"]: next((w["r"] for w in r["windows"] if w["window"] == main), None) for r in res.get("relations", [])}}


def get(session, tf: str = "D1", refresh: bool = False) -> dict:
    """The current result. Recomputed only when the input data changed (fingerprint) or after TTL_S; stored with a
    short history of earlier results only when the user switched the module on."""
    from app.data import settings_store, store

    hit = _mem.get(tf)
    if hit and not refresh and time.monotonic() - hit[0] < TTL_S:
        return hit[1]
    enabled = settings_store.get("intermarket.enabled", False)
    if enabled and hit and refresh:
        fp = fingerprint(load(session, tf))
        if fp == hit[1].get("fingerprint"):
            _mem[tf] = (time.monotonic(), hit[1])
            return hit[1]  # nothing new in the data: the stored result stands
    res = compute(session, tf)
    _mem[tf] = (time.monotonic(), res)
    if enabled:  # stored only when the user switched the module on
        store.cache_put(CACHE_KEY.format(tf=tf), res, "intermarket", session=session)
        old, _ = store.cache_get(HISTORY_KEY.format(tf=tf), session=session)
        hist = (old if isinstance(old, list) else [])[-(HISTORY_KEEP - 1):] + [_summary(res)]
        store.cache_put(HISTORY_KEY.format(tf=tf), hist, "intermarket", session=session)
    return res


def refresh(session) -> dict:
    """In the data cycle (only when switched on): (1) the files Dukascopy can still give us, within a small budget and a
    time limit, only when something is missing; (2) the correlations, only for timeframes whose data changed."""
    from app.data import settings_store
    from app.market import intermarket_data as imd

    if not settings_store.get("intermarket.enabled", False):
        return {"enabled": False}  # nothing is downloaded or stored until the user turns the module on
    rep: dict = {"enabled": True, "fetch": imd.run_all(session=session)}
    session.commit()
    for tf in ("D1", "H1"):
        r = get(session, tf, refresh=True)
        rep[tf] = {"relations": len(r.get("relations", [])), "fingerprint": r.get("fingerprint")}
    return rep
