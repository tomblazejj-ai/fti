"""Generic, instrument-agnostic scoring primitives.

Design rule (see ARCHITECTURE.md section 5 / CLAUDE.md-style philosophy for
this project): a pillar's *gate* (does it fire at all) and its *scale* (how
strong is the signal) are separate concerns. Every pillar must return a
human-readable reason for its signal — no bare numbers without explanation.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


def cz(value: float, fmt: str = ".1f") -> str:
    """Number in Czech notation: decimal comma, real minus sign."""
    return format(value, fmt).replace(".", ",").replace("-", "\u2212")


def cz_date(iso: str) -> str:
    """'2026-08-27' -> '27. 8. 2026' (returns the input unchanged if unparseable)."""
    try:
        d = dt.date.fromisoformat(iso[:10])
    except ValueError:
        return iso
    return f"{d.day}. {d.month}. {d.year}"


HORIZON_CZ = {"intraday": "během dne", "1-3d": "1–3 dny", "1-10d": "1–10 dní", "1-4w": "1–4 týdny", "1-3m": "1–3 měsíce"}


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def decay_factor(age_days: float, half_life_days: float, floor: float = 0.3) -> float:
    """How much weight a piece of information still carries after `age_days`.

    Exponential decay toward `floor`, never all the way to zero — per the
    brief's explicit requirement that important long-run fundamentals must
    not vanish purely from age (only fresh news should decay hard). At
    age_days=0 this returns 1.0; as age grows it approaches `floor`.
    """
    if half_life_days <= 0:
        return 1.0
    age_days = max(0.0, age_days)
    decayed = 0.5 ** (age_days / half_life_days)
    return floor + (1.0 - floor) * decayed


def bullish_bearish_label(bias: str) -> str:
    return {"LONG": "BULLISH", "SHORT": "BEARISH", "NEUTRAL": "NEUTRAL"}.get(bias, "NEUTRAL")


@dataclass
class PillarResult:
    name: str
    weight: float
    raw_signal: float  # in [-1, 1]: -1 fully bearish, +1 fully bullish, 0 neutral
    reasons: list[str] = field(default_factory=list)
    data_quality: str = "ok"  # "ok" | "partial" | "unavailable"
    source: str = ""  # e.g. "FRED DFII10", "CFTC COT (COMEX Gold)", "News: fed_tone (RSS+GDELT)"
    gaps: list[str] = field(default_factory=list)  # what is MISSING when data_quality != "ok" (not the data that is present)
    as_of: str | None = None  # period/date the underlying data refers to, for time-relevance transparency

    @property
    def points(self) -> float:
        """Signed contribution to the -weight..+weight range."""
        return clamp(self.raw_signal, -1.0, 1.0) * self.weight

    @property
    def has_evidence(self) -> bool:
        """True when real data moved (or fully assessed) this pillar — a
        partial pillar whose available half still moved the score counts."""
        return self.data_quality == "ok" or (self.data_quality == "partial" and abs(self.points) >= 0.05)

    @property
    def impact(self) -> str:
        if self.raw_signal > 0.1:
            return "bullish"
        if self.raw_signal < -0.1:
            return "bearish"
        return "neutral"


@dataclass
class Scenario:
    name: str  # "base" | "bull" | "bear"
    narrative: str
    supports: list[str] = field(default_factory=list)  # co ho podporuje
    would_change: list[str] = field(default_factory=list)  # co by ho změnilo
    key_risks: list[str] = field(default_factory=list)  # hlavní rizika


@dataclass
class InstrumentScoreResult:
    instrument_code: str
    computed_at: dt.datetime
    horizon: str
    score: float  # 0-100, 50 = neutral midpoint
    bias: str  # "LONG" | "NEUTRAL" | "SHORT"
    pillars: list[PillarResult]
    drivers: list[str]
    contrarian: list[str]
    risks: list[str]
    scenarios: dict[str, Scenario]
    invalidation: list[str] = field(default_factory=list)

    @property
    def direction(self) -> str:
        return bullish_bearish_label(self.bias)

    def pillar_breakdown_json(self) -> dict:
        return {
            p.name: {
                "weight": p.weight,
                "raw_signal": round(p.raw_signal, 3),
                "points": round(p.points, 2),
                "impact": p.impact,
                "reasons": p.reasons,
                "data_quality": p.data_quality,
                "source": p.source,
                "as_of": p.as_of,
                "gaps": p.gaps,
            }
            for p in self.pillars
        }

    def scenarios_json(self) -> dict:
        return {
            key: {
                "narrative": s.narrative,
                "supports": s.supports,
                "would_change": s.would_change,
                "key_risks": s.key_risks,
            }
            for key, s in self.scenarios.items()
        }


def signed_total_to_score(signed_total: float, max_abs: float = 100.0) -> float:
    """Map a signed total in [-max_abs, +max_abs] to a 0-100 scale, 50 = neutral."""
    normalized = signed_total / max_abs if max_abs else 0.0
    return clamp(50.0 + normalized * 50.0, 0.0, 100.0)


def bias_from_score(score: float, long_threshold: float = 65.0, short_threshold: float = 35.0) -> str:
    if score >= long_threshold:
        return "LONG"
    if score <= short_threshold:
        return "SHORT"
    return "NEUTRAL"


def trend_signal(
    actual: float | None,
    previous: float | None,
    higher_is_bullish: bool,
    reason_label: str,
    scale: float = 1.0,
    mode: str = "relative",
) -> tuple[float, str, str]:
    """Generic "did this series move in the bullish or bearish direction" signal.

    Returns (raw_signal in [-1,1], reason string, data_quality).
    `mode="relative"`: the move is (actual-previous)/|previous| — for levels
    like an FX index or a position count. `mode="absolute"`: the move is
    actual-previous in the series' own unit — for anything already expressed
    as a rate or % (yields, Fed funds, YoY inflation, unemployment rate),
    where "0.25 percentage points" is the meaningful quantity.
    `scale` = the move that maps to a full +/-1 signal, in the chosen mode's
    unit. Tuned per series, never shared blindly (same lesson as ISZ PRO's
    "gate vs scale" split, see docs/DECISIONS.md).
    """
    if actual is None or previous is None:
        return 0.0, f"{reason_label}: chybí data (actual/previous), signál neutrální.", "unavailable"
    delta = actual - previous
    if mode == "absolute":
        move = delta
    elif previous != 0:
        move = delta / abs(previous)
    else:
        move = delta
    direction = 1.0 if higher_is_bullish else -1.0
    raw = clamp((move / scale) * direction, -1.0, 1.0)
    if abs(delta) < 0.005:
        move_desc = "prakticky beze změny"  # e.g. Core PCE YoY 3.3436 % -> 3.3441 %
    else:
        move_desc = "vzrostlo" if delta > 0 else "kleslo"
    reason = f"{reason_label}: {move_desc} ({cz(previous, '.3f')} → {cz(actual, '.3f')})."
    return raw, reason, "ok"


def reference_period_end(period_start: dt.date, frequency: str) -> dt.date:
    """FRED dates monthly/quarterly observations by the FIRST day of the
    reference period (August CPI = 2026-08-01). Measuring age from that date
    would overstate it by a whole month; the end of the reference period is
    the earliest honest anchor. The actual release is still later (typically
    2–6 weeks) — we don't have release dates without a FRED API key, so age
    remains an upper-bound-ish approximation, documented in DECISIONS.md.
    """
    if frequency == "M":
        first_of_next = (period_start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        return first_of_next - dt.timedelta(days=1)
    if frequency == "Q":
        month = period_start.month + 2
        mid = period_start.replace(month=month, day=28) + dt.timedelta(days=4)
        return mid.replace(day=1) - dt.timedelta(days=1)
    return period_start


def parse_period_date(period: str) -> dt.date | None:
    """Parse a FRED/CFTC-style 'YYYY-MM-DD' period string. Returns None if
    unparseable rather than raising — callers must treat that as "unknown
    age", not crash the whole scoring cycle over a formatting surprise.
    """
    if not period:
        return None
    try:
        return dt.date.fromisoformat(period[:10])
    except ValueError:
        return None
