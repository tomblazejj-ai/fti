"""Turn raw FRED levels into the number a trader actually reads.

Why this exists: FRED publishes most macro series as *levels* — the CPI
index (~337), total nonfarm employment (~160M), real GDP in dollars. Levels
almost always rise, so comparing "latest level vs previous level" says
nothing about whether inflation accelerated or the labour market cooled.
Every series is therefore converted to its conventional reading first:

  level     daily market series (yields, USD index, Fed funds target):
            latest value vs the value N observations earlier, so a daily
            series isn't scored on yesterday's noise
  yoy       price indices (Core CPI, Core PCE): year-over-year % change,
            latest month vs the prior month's YoY rate
  mom_diff  employment level (PAYEMS): monthly change (the "NFP print",
            thousands), latest vs prior month's change
  qoq_ann   real GDP: quarter-over-quarter growth, annualized %, latest vs
            prior quarter

Pure functions only, no I/O — tested in tests/test_transforms.py.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class SeriesSpec:
    key: str  # XauInputs field name
    external_id: str  # FRED series id
    frequency: str  # "D" | "M" | "Q"
    transform: str  # "level" | "yoy" | "mom_diff" | "qoq_ann"
    unit: str  # display unit of the TRANSFORMED value
    lookback: int = 1  # only for "level": comparison point N observations back


@dataclass
class DerivedPoint:
    actual: float
    previous: float
    period: str
    previous_period: str


class InsufficientHistoryError(ValueError):
    pass


def _shift_month(date_str: str, months: int) -> str:
    d = dt.date.fromisoformat(date_str)
    total = d.year * 12 + (d.month - 1) + months
    return dt.date(total // 12, total % 12 + 1, 1).isoformat()


def _require(observations: list[dict], n: int, spec: SeriesSpec) -> None:
    if len(observations) < n:
        raise InsufficientHistoryError(
            f"{spec.external_id}: pro transformaci '{spec.transform}' je potřeba {n} pozorování, k dispozici {len(observations)}."
        )


def derive(observations: list[dict], spec: SeriesSpec) -> DerivedPoint:
    """`observations` must be valid (no None values), oldest first."""
    if spec.transform == "level":
        _require(observations, spec.lookback + 1, spec)
        latest, comparison = observations[-1], observations[-1 - spec.lookback]
        return DerivedPoint(latest["value"], comparison["value"], latest["date"], comparison["date"])

    if spec.transform == "yoy":
        by_date = {o["date"]: o["value"] for o in observations}
        _require(observations, 2, spec)
        latest, prior = observations[-1], observations[-2]

        def yoy(date_str: str) -> float:
            base = by_date.get(_shift_month(date_str, -12))
            if base is None or base == 0:
                raise InsufficientHistoryError(f"{spec.external_id}: chybí hodnota o 12 měsíců dříve než {date_str}.")
            return (by_date[date_str] / base - 1.0) * 100.0

        return DerivedPoint(yoy(latest["date"]), yoy(prior["date"]), latest["date"], prior["date"])

    if spec.transform == "mom_diff":
        _require(observations, 3, spec)
        v3, v2, v1 = (o["value"] for o in observations[-3:])
        return DerivedPoint(v1 - v2, v2 - v3, observations[-1]["date"], observations[-2]["date"])

    if spec.transform == "qoq_ann":
        _require(observations, 3, spec)
        v3, v2, v1 = (o["value"] for o in observations[-3:])
        if v2 == 0 or v3 == 0:
            raise InsufficientHistoryError(f"{spec.external_id}: nulová hodnota, nelze spočítat růst.")
        return DerivedPoint(
            ((v1 / v2) ** 4 - 1.0) * 100.0,
            ((v2 / v3) ** 4 - 1.0) * 100.0,
            observations[-1]["date"],
            observations[-2]["date"],
        )

    raise ValueError(f"Neznámá transformace '{spec.transform}'")
