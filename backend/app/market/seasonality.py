"""Seasonality of gold: how it did in each calendar month in past years.

Source: weekly PAXG/USD closes from Kraken (PAXG trades since 09/2019, so
~7 years — a short sample; the UI says so). A month's return = last weekly
close of the month vs. last weekly close of the previous month.
"""

from __future__ import annotations

import datetime as dt
import statistics

from app.connectors.kraken import Candle

MONTHS_CZ = ["leden", "únor", "březen", "duben", "květen", "červen", "červenec", "srpen", "září", "říjen", "listopad", "prosinec"]


def _pct(v: float) -> str:
    return f"{v:+.1f} %".replace(".", ",").replace("-", "−")


def analyze(weekly: list[Candle], now: dt.datetime, source: str = "XAUUSD") -> dict | None:
    if len(weekly) < 60:
        return None
    month_close: dict[tuple[int, int], float] = {}
    for c in weekly:
        # a weekly candle is stamped with its OPEN; its close belongs to the day it ends
        end = c.time + dt.timedelta(days=6)
        month_close[(end.year, end.month)] = c.close  # last weekly close of the month wins
    keys = sorted(month_close)
    returns: dict[int, list[dict]] = {m: [] for m in range(1, 13)}
    for prev, cur in zip(keys, keys[1:]):
        if cur == (now.year, now.month):
            continue  # the running month is not finished
        expected = (prev[0] + (prev[1] == 12), prev[1] % 12 + 1)
        if cur != expected:
            continue
        r = (month_close[cur] / month_close[prev] - 1) * 100
        returns[cur[1]].append({"year": cur[0], "ret": round(r, 2)})

    months = []
    for m in range(1, 13):
        rs = [x["ret"] for x in returns[m]]
        months.append({
            "month": m,
            "name": MONTHS_CZ[m - 1],
            "avg": round(statistics.mean(rs), 2) if rs else None,
            "median": round(statistics.median(rs), 2) if rs else None,
            "win_rate": round(sum(r > 0 for r in rs) / len(rs) * 100) if rs else None,
            "years": len(rs),
            "by_year": returns[m],
        })
    cur, nxt = months[now.month - 1], months[now.month % 12]

    def verdict(mo: dict) -> str:
        if mo["avg"] is None or mo["years"] < 4:
            return f"{mo['name'].capitalize()}: málo let historie na závěr."
        if mo["avg"] > 0.5 and (mo["win_rate"] or 0) >= 60:
            return f"{mo['name'].capitalize()} bývá pro zlato silný: průměrně {_pct(mo['avg'])}, růst v {mo['win_rate']} % let."
        if mo["avg"] < -0.5 and (mo["win_rate"] or 0) <= 40:
            return f"{mo['name'].capitalize()} bývá pro zlato slabý: průměrně {_pct(mo['avg'])}, růst jen v {mo['win_rate']} % let."
        return f"{mo['name'].capitalize()} nemá výrazný sezónní sklon (průměr {_pct(mo['avg'])}, růst v {mo['win_rate']} % let)."

    signal = 0.0
    if cur["avg"] is not None and cur["years"] >= 4:
        signal = max(-1.0, min(1.0, cur["avg"] / 3.0)) * (abs((cur["win_rate"] or 50) - 50) / 50)
    first_year = keys[0][0]
    return {
        "months": months,
        "current_month": now.month,
        "current_text": verdict(cur),
        "next_text": verdict(nxt),
        "signal": round(signal, 2),
        "years_from": first_year,
        "years_to": now.year,
        "note": (f"Z týdenních cen ({source}) od {first_year} — {now.year - first_year} let dat. "
                 "Měsíc = poslední týdenní závěr v měsíci, hranice se proto může o pár dní posunout."),
    }


# --- Long history: 5 / 10 / 15-year averages, heatmap with the average ----------------

def _month_returns(monthly: dict[str, float]) -> dict[str, float]:
    keys = sorted(monthly)
    out = {}
    for a, b in zip(keys, keys[1:]):
        ya, ma = int(a[:4]), int(a[5:])
        if (int(b[:4]), int(b[5:])) == (ya + (ma == 12), ma % 12 + 1) and monthly[a]:
            out[b] = (monthly[b] / monthly[a] - 1) * 100
    return out


def _avg(rets: dict[str, float], month: int, before: str, years: int) -> tuple[float | None, float | None, int]:
    vals = [v for k, v in sorted(rets.items()) if int(k[5:]) == month and k < before][-years:]
    if len(vals) < max(3, years // 2):
        return None, None, len(vals)
    return statistics.mean(vals), sum(v > 0 for v in vals) / len(vals) * 100, len(vals)


def analyze_long(monthly: dict[str, float], now: dt.datetime, updated: str | None = None,
                 label: str = "Zlato", source: str = "Světová banka – měsíční průměry cen (Pink Sheet)") -> dict | None:
    rets = _month_returns(monthly)
    if len(rets) < 60:
        return None
    before = f"{now.year:04d}-{now.month:02d}"
    months, raw10 = [], {}
    for m in range(1, 13):
        a5, w5, n5 = _avg(rets, m, before, 5)
        a10, w10, n10 = _avg(rets, m, before, 10)
        a15, w15, n15 = _avg(rets, m, before, 15)
        raw10[m] = (a10, w10)
        months.append({"month": m, "name": MONTHS_CZ[m - 1], "avg5": _r(a5), "avg10": _r(a10), "avg15": _r(a15),
                       "win10": _r(w10, 0), "n10": n10})

    # forward path from the current month (cumulative average performance, like "Seasonality performance")
    path = {"5": [0.0], "10": [0.0], "15": [0.0]}
    labels = [MONTHS_CZ[now.month - 1]]
    for i in range(12):
        m = (now.month - 1 + i) % 12 + 1
        labels.append(MONTHS_CZ[m % 12])
        for key in path:
            a = months[m - 1][f"avg{key}"] or 0.0
            path[key].append(round((1 + path[key][-1] / 100) * (1 + a / 100) * 100 - 100, 2))

    years = sorted({int(k[:4]) for k in rets if k < before})[-10:]
    heat = [{"year": y, "months": [_r(rets.get(f"{y:04d}-{m:02d}")) for m in range(1, 13)]} for y in years]

    cur = months[now.month - 1]
    nxt = months[now.month % 12]

    def verdict(mo: dict) -> str:
        a, w = raw10[mo["month"]]
        if a is None:
            return f"{mo['name'].capitalize()}: málo historie."
        if a >= 0.5 and (w or 0) >= 60:
            return f"{mo['name'].capitalize()} bývá silný: za 10 let průměrně {_pct(a)}, růst v {w:.0f} % let."
        if a <= -0.5 and (w or 0) <= 40:
            return f"{mo['name'].capitalize()} bývá slabý: za 10 let průměrně {_pct(a)}, růst jen v {w:.0f} % let."
        return f"{mo['name'].capitalize()} nemá výrazný sklon (10 let: {_pct(a)}, růst v {w:.0f} % let)."

    a, w = raw10[now.month]
    w = w or 0
    score = 0
    if a is not None:
        score = 2 if a >= 1.5 and w >= 70 else 1 if a >= 0.5 and w >= 60 else -2 if a <= -1.5 and w <= 30 else -1 if a <= -0.5 and w <= 40 else 0
    return {
        "label": label,
        "months": months,
        "path": {"labels": labels, "lines": path},
        "heatmap": heat,
        "current_text": verdict(cur),
        "next_text": verdict(nxt),
        "score": score,
        "source": source,
        "updated": updated,
        "note": ("Měsíční průměry cen: změna = průměr měsíce proti průměru předchozího měsíce. "
                 "Sezónnost je filtr pro swing obchody — nepoužívej ji samostatně ani na intraday."),
    }


def _r(v: float | None, digits: int = 2) -> float | None:
    return None if v is None else round(v, digits)


# --- Daily seasonal windows: the same calendar days in each of the last N years.
import bisect  # noqa: E402

WINDOW_LENGTHS = (14, 21, 30, 42)  # calendar days
WINDOW_AHEAD = 21  # windows starting today … in three weeks
WINDOW_MIN_WIN = 70.0  # % of years in the same direction
WINDOW_MIN_AVG = {"gold": 1.0, "usd": 0.5}  # % average move worth mentioning
PATH_BACK, PATH_AHEAD = 14, 91


def _years_back(d: dt.date, k: int) -> dt.date:
    try:
        return d.replace(year=d.year - k)
    except ValueError:  # 29 February
        return d.replace(year=d.year - k, day=28)


class _Daily:
    def __init__(self, prices: dict[str, float]):
        self.days = sorted(prices)
        self.prices = prices

    def on(self, d: dt.date, max_back: int = 6) -> float | None:
        """Last price on or before `d` (weekends and holidays fall back up to 6 days)."""
        i = bisect.bisect_right(self.days, d.isoformat()) - 1
        if i < 0:
            return None
        day = self.days[i]
        if (d - dt.date.fromisoformat(day)).days > max_back:
            return None
        return self.prices[day]


def _cz_day(d: dt.date) -> str:
    return f"{d.day}. {d.month}."


def window_stats(px: _Daily, start: dt.date, end: dt.date, years: int, today: dt.date) -> dict | None:
    rets = []
    for k in range(1, years + 1):
        s, e = _years_back(start, k), _years_back(end, k)
        if e >= today:
            continue
        a, b = px.on(s), px.on(e)
        if a and b:
            rets.append((s.year, (b / a - 1) * 100))
    if len(rets) < max(4, int(years * 0.7)):
        return None
    vals = [r for _, r in rets]
    return {"avg": round(statistics.mean(vals), 2), "win": round(sum(v > 0 for v in vals) / len(vals) * 100),
            "up": sum(v > 0 for v in vals), "n": len(vals), "by_year": [{"year": y, "ret": round(r, 2)} for y, r in rets]}


def _window_text(w: dict, label: str, up: bool) -> str:
    n_dir = w["up"] if up else w["n"] - w["up"]
    verb = "rostl" if up else "klesal"
    verb += "o" if label.startswith("Zlato") else "a" if label.startswith("Ropa") else ""
    return (f"{label} od {w['from_text']} do {w['to_text']}: v {n_dir} z {w['n']} let {verb}, "
            f"průměrně {_pct(w['avg'])}.")


def daily_view(prices: dict[str, float], now: dt.datetime, asset: str = "gold", label: str = "Zlato",
               source: str = "") -> dict | None:
    """Seasonal windows ahead + the average daily path around today for 5 / 10 / 15 years."""
    if len(prices) < 260 * 5:
        return None
    px = _Daily(prices)
    today = now.date()
    first_year = int(px.days[0][:4])
    windows = []
    for off in range(0, WINDOW_AHEAD + 1):
        s = today + dt.timedelta(days=off)
        for length in WINDOW_LENGTHS:
            e = s + dt.timedelta(days=length)
            st = window_stats(px, s, e, 10, today)
            if st:
                windows.append({**st, "from": s.isoformat(), "to": e.isoformat(), "from_text": _cz_day(s), "to_text": _cz_day(e),
                                "days": length})
    min_avg = WINDOW_MIN_AVG.get(asset, 1.0)
    ups = [w for w in windows if w["win"] >= WINDOW_MIN_WIN and w["avg"] >= min_avg]
    downs = [w for w in windows if w["win"] <= 100 - WINDOW_MIN_WIN and w["avg"] <= -min_avg]
    best_up = max(ups, key=lambda w: (w["win"], w["avg"])) if ups else None
    best_down = min(downs, key=lambda w: (w["win"], w["avg"])) if downs else None
    nxt = window_stats(px, today, today + dt.timedelta(days=30), 10, today)
    if nxt:
        nxt = {**nxt, "from": today.isoformat(), "to": (today + dt.timedelta(days=30)).isoformat(), "from_text": _cz_day(today),
               "to_text": _cz_day(today + dt.timedelta(days=30)), "days": 30}
    lean = 0
    if nxt and nxt["win"] >= 60 and nxt["avg"] >= min_avg / 2:
        lean = 1
    elif nxt and nxt["win"] <= 40 and nxt["avg"] <= -min_avg / 2:
        lean = -1

    # average path from 2 weeks back to 3 months ahead, every year rebased to today's date
    offsets = list(range(-PATH_BACK, PATH_AHEAD + 1, 1))
    lines: dict[str, list[float]] = {}
    used: dict[str, int] = {}
    for n in (5, 10, 15):
        rows = []
        for k in range(1, n + 1):
            base = _years_back(today, k)
            if base.year < first_year:
                continue
            p0 = px.on(base)
            if not p0:
                continue
            row = []
            for t in offsets:
                d = base + dt.timedelta(days=t)
                p = px.on(d) if d < today else None
                row.append(None if p is None else (p / p0 - 1) * 100)
            if all(v is not None for v in row):
                rows.append(row)
        if len(rows) >= n - 1:  # a "15 years" line needs (almost) 15 real years
            lines[str(n)] = [round(statistics.mean(col), 2) for col in zip(*rows)]
            used[str(n)] = len(rows)
    texts = []
    if best_up:
        texts.append(_window_text(best_up, label, True))
    if best_down:
        texts.append(_window_text(best_down, label, False))
    return {
        "label": label,
        "next30": nxt,
        "lean": lean,
        "best_up": best_up,
        "best_down": best_down,
        "texts": texts,
        "path": {"offsets": offsets, "dates": [(today + dt.timedelta(days=t)).isoformat() for t in offsets], "lines": lines,
                 "years_used": used},
        "years_from": first_year,
        "last_date": px.days[-1],
        "source": source,
        "note": ("Stejné kalendářní dny v každém z posledních 10 let. Okno je vodítko pro swing obchody — počítej s odchylkou "
                 "jeden až tři týdny, nikdy s přesným datem."),
    }
