"""How gold currently moves together with its main drivers — pure functions.

For each driver: correlation of DAILY moves over the last 60 common trading
days (the relationship now) and over ~250 days (the usual relationship),
the driver's own move over the last 20 days, and what that move means for
gold GIVEN the current correlation ("pomáhá" / "brzdí" / bez vlivu).

Moves are % changes for prices and point changes for yields (a yield going
from 2,00 to 2,10 % is a 0,10 p.b. move, not a 5 % move).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

STRONG = 0.5
MODERATE = 0.3
WINDOW_NOW = 60
WINDOW_USUAL = 250
MOVE_WINDOW = 20


@dataclass(frozen=True)
class Driver:
    key: str
    fred_id: str
    label: str
    transform: str  # "pct" | "diff"
    expected_sign: int  # usual sign of the correlation with gold; 0 = no stable textbook relation
    unit: str


DRIVERS: list[Driver] = [
    # dollar and EUR/USD from the ECB's daily reference rates (current to the day);
    # FRED's DTWEXBGS / DEXUSEU come out a week late — they are only the fallback
    Driver("usd", "ECB:DXY", "Dolar (DXY)", "pct", -1, "%"),
    Driver("real_yield", "DFII10", "Reálný výnos 10letých dluhopisů", "diff", -1, "p.b."),
    Driver("yield10", "DGS10", "Nominální výnos 10letých dluhopisů", "diff", -1, "p.b."),
    Driver("eurusd", "ECB:EURUSD", "EUR/USD", "pct", 1, "%"),
    Driver("spx", "SP500", "Akcie USA (S&P 500)", "pct", 0, "%"),
    Driver("oil", "DCOILWTICO", "Ropa WTI", "pct", 1, "%"),
    Driver("vix", "VIXCLS", "Strach na akciích (VIX)", "diff", 0, "b."),
    Driver("btc", "CBBTCUSD", "Bitcoin", "pct", 0, "%"),
]


def _moves(values: list[float], transform: str) -> list[float]:
    if transform == "pct":
        return [(values[i] / values[i - 1] - 1.0) * 100.0 if values[i - 1] else 0.0 for i in range(1, len(values))]
    return [values[i] - values[i - 1] for i in range(1, len(values))]


def pearson(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 10 or n != len(y):
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(sxx * syy)


def strength_label(r: float | None) -> str:
    if r is None:
        return "nelze určit"
    a = abs(r)
    if a >= STRONG:
        return "silná"
    if a >= MODERATE:
        return "střední"
    if a >= 0.15:
        return "slabá"
    return "žádná"


def analyze_driver(driver: Driver, gold: dict[str, float], other: dict[str, float]) -> dict:
    common = sorted(set(gold) & set(other))
    base = {"key": driver.key, "label": driver.label, "fred_id": driver.fred_id, "unit": driver.unit}
    if len(common) < WINDOW_NOW + 1:
        return {**base, "available": False, "note": f"Málo společných dnů s cenou zlata ({len(common)})."}

    g = [gold[d] for d in common]
    o = [other[d] for d in common]
    g_moves = _moves(g, "pct")
    o_moves = _moves(o, driver.transform)

    r_now = pearson(g_moves[-WINDOW_NOW:], o_moves[-WINDOW_NOW:])
    r_usual = pearson(g_moves[-WINDOW_USUAL:], o_moves[-WINDOW_USUAL:]) if len(g_moves) >= WINDOW_USUAL else None

    if driver.transform == "pct":
        move = (o[-1] / o[-1 - MOVE_WINDOW] - 1.0) * 100.0 if o[-1 - MOVE_WINDOW] else 0.0
        meaningful = abs(move) >= 1.0
    else:
        move = o[-1] - o[-1 - MOVE_WINDOW]
        meaningful = abs(move) >= (0.1 if driver.unit == "p.b." else 1.0)

    effect = 0
    if r_now is not None and abs(r_now) >= MODERATE and meaningful:
        effect = 1 if (r_now > 0) == (move > 0) else -1

    unusual = (
        driver.expected_sign != 0 and r_now is not None and abs(r_now) >= 0.2 and (r_now > 0) != (driver.expected_sign > 0)
    )

    return {
        **base,
        "available": True,
        "as_of": common[-1],
        "corr_now": round(r_now, 2) if r_now is not None else None,
        "corr_usual": round(r_usual, 2) if r_usual is not None else None,
        "strength": strength_label(r_now),
        "move20": round(move, 2),
        "effect": effect,  # +1 pomáhá zlatu, -1 brzdí zlato, 0 bez vlivu
        "unusual": unusual,
    }


def analyze_all(gold: dict[str, float], drivers: dict[str, dict[str, float]]) -> list[dict]:
    """`drivers` maps driver key -> {date: value}. Missing drivers are reported unavailable."""
    out = []
    for d in DRIVERS:
        series = drivers.get(d.key)
        if not series:
            out.append({"key": d.key, "label": d.label, "fred_id": d.fred_id, "unit": d.unit, "available": False,
                        "note": "Data se nepodařilo stáhnout."})
            continue
        out.append(analyze_driver(d, gold, series))
    out.sort(key=lambda x: -abs(x.get("corr_now") or 0.0))
    return out
