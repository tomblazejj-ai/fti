"""XAUUSD fundamental scoring — first instrument, per zadání section 3 (Gold).

Drivers modeled: Fed / rate expectations, inflation, real yields, USD,
economic growth, geopolitics, central bank tone/buying, positioning.

Every pillar is a pure function over already-fetched, already-classified
data (macro observations + classified news) plus the target horizon and the
"as of" timestamp. No network calls happen here — that split keeps this
module trivially testable (see tests/test_scoring.py).

Time-weighting model (see docs/DECISIONS.md "Modul 3"): a piece of
information's *weight* depends on how it ages, not on the horizon changing
which pillars exist. Two decay families:
  - daily series (real yields, USD index, Fed funds level) never decay —
    they represent the currently-known state of the world, always "fresh".
  - discrete releases (monthly macro prints, weekly CFTC, news articles)
    decay from the moment of publication, with a horizon-specific half-life:
    short horizons (intraday) care almost only about the freshest print/
    article; long horizons (1-3m) smooth over many prints. Decay never goes
    below a floor (see base.decay_factor) — a 2-month-old CPI print still
    counts for something even on an intraday view, per the brief's explicit
    "long-term fundamentals must not vanish from age alone" requirement.
This is why the same inputs produce five different scores/biases, one per
horizon — not five copies of the same number.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from app.scoring.base import (
    InstrumentScoreResult,
    PillarResult,
    Scenario,
    bias_from_score,
    HORIZON_CZ,
    clamp,
    cz,
    cz_date,
    decay_factor,
    parse_period_date,
    reference_period_end,
    signed_total_to_score,
    trend_signal,
)

PILLAR_WEIGHTS = {
    "fed": 20.0,
    "inflation": 15.0,
    "real_yields": 20.0,
    "usd": 15.0,
    "economy": 10.0,
    "geopolitics": 5.0,
    "central_banks": 8.0,
    "positioning": 7.0,
}
assert abs(sum(PILLAR_WEIGHTS.values()) - 100.0) < 1e-9

PILLAR_DISPLAY = {
    "fed": "Fed", "inflation": "Inflace", "real_yields": "Reálné výnosy", "usd": "USD",
    "economy": "Ekonomika", "geopolitics": "Geopolitika", "central_banks": "Centrální banky", "positioning": "Pozicování",
}
# Czech forms of the impact words: nominative, genitive (used in "z ... na ...")
IMPACT_CZ = {"bullish": "býčí", "bearish": "medvědí", "neutral": "neutrální"}
IMPACT_CZ_GEN = {"bullish": "býčího", "bearish": "medvědího", "neutral": "neutrálního"}
BIAS_CZ = {"LONG": "býčí (LONG)", "SHORT": "medvědí (SHORT)", "NEUTRAL": "neutrální"}

_QUALITY_RANK = {"ok": 0, "partial": 1, "unavailable": 2}


def _worst_quality(*qualities: str) -> str:
    return max(qualities, key=lambda q: _QUALITY_RANK[q])


SUPPORTED_HORIZONS = ["intraday", "1-3d", "1-10d", "1-4w", "1-3m"]

# Half-life (days) for a discrete news article's influence, per horizon.
NEWS_HALF_LIFE_DAYS = {"intraday": 0.5, "1-3d": 2.0, "1-10d": 5.0, "1-4w": 12.0, "1-3m": 30.0}
# Half-life (days) for a monthly/quarterly macro print's influence, per horizon.
MONTHLY_RELEASE_HALF_LIFE_DAYS = {"intraday": 3.0, "1-3d": 5.0, "1-10d": 10.0, "1-4w": 25.0, "1-3m": 60.0}
# Half-life (days) for the weekly CFTC COT print's influence, per horizon.
WEEKLY_RELEASE_HALF_LIFE_DAYS = {"intraday": 2.0, "1-3d": 4.0, "1-10d": 8.0, "1-4w": 20.0, "1-3m": 45.0}

# Official FOMC decision dates, verified live against
# https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm on
# 2026-09-27 (see docs/DECISIONS.md) — hardcoded because it is a small, slow-
# changing public calendar, not something to re-fetch every cycle. Extend
# this list when 2027 dates are published; never guess future dates.
FOMC_DECISION_DATES_2026 = [
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]


def _gaps(*sub_signals: tuple[str, str]) -> list[str]:
    """Reasons of the sub-signals that lack data — used for the "risks" list."""
    return [reason for quality, reason in sub_signals if quality != "ok"]


def _next_fomc_date(now: dt.datetime) -> str | None:
    today = now.date()
    upcoming = [d for d in FOMC_DECISION_DATES_2026 if dt.date.fromisoformat(d) >= today]
    return upcoming[0] if upcoming else None


@dataclass
class MacroPoint:
    """One (actual, previous) reading for a FRED/CFTC-style series."""

    actual: float | None
    previous: float | None
    period: str = ""
    observation_id: int | None = None  # MacroObservation.id — for score_history traceability
    previous_period: str = ""  # date of the comparison observation
    frequency: str = ""  # "D" | "W" | "M" | "Q" — decides how age is anchored


def _lbl(label: str, point: MacroPoint) -> str:
    if point.previous_period and point.period:
        return f"{label} [{cz_date(point.previous_period)} → {cz_date(point.period)}]"
    return label


@dataclass
class NewsDataPoint:
    """One classified news item's contribution to a single factor tag."""

    sentiment: float  # -1..1, this item's polarity for this specific factor tag
    published_at: dt.datetime
    item_id: int
    description: str  # human-readable "title (source, date)" for the reasons list


@dataclass
class NewsSignal:
    """All (non-duplicate) news items relevant to one factor tag, undecayed.

    Decay is applied at scoring time (per horizon), not at aggregation time —
    that is what lets the same aggregated data produce different signals for
    "intraday" vs "1-3m" (see module docstring).
    """

    factor_tag: str
    points: list[NewsDataPoint] = field(default_factory=list)

    @property
    def item_count(self) -> int:
        return len(self.points)

    @property
    def item_ids(self) -> list[int]:
        return [p.item_id for p in self.points]


@dataclass
class XauInputs:
    """Everything the XAUUSD scoring engine needs, already fetched/classified."""

    real_yield_10y: MacroPoint  # FRED DFII10
    usd_index: MacroPoint  # FRED DTWEXBGS
    fed_funds_target: MacroPoint  # FRED DFEDTARU (upper bound)
    core_cpi: MacroPoint  # FRED CPILFESL (YoY or index level, previous = prior print)
    core_pce: MacroPoint  # FRED PCEPILFE
    gdp: MacroPoint  # FRED GDP or GDPC1
    unemployment: MacroPoint  # FRED UNRATE
    nfp: MacroPoint  # FRED PAYEMS
    fed_tone_news: NewsSignal | None = None  # factor_tag "fed_tone"
    geopolitics_news: NewsSignal | None = None  # factor_tag "geopolitics"
    central_bank_buying_news: NewsSignal | None = None  # factor_tag "cb_gold_buying"
    positioning: MacroPoint | None = None  # CFTC COT net non-commercial longs (weekly, lagged)


def _as_aware_utc(value: dt.datetime) -> dt.datetime:
    """SQLite drops tzinfo on round-trip even for DateTime(timezone=True)
    columns — treat any naive datetime coming back from the DB as UTC
    rather than crashing on a naive/aware subtraction.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.timezone.utc)


def _weighted_news(signal: NewsSignal | None, now: dt.datetime, horizon: str) -> tuple[float, list[str], list[int], str]:
    if signal is None or not signal.points:
        return 0.0, [], [], "partial"
    now = _as_aware_utc(now)
    half_life = NEWS_HALF_LIFE_DAYS[horizon]
    weights = [
        decay_factor(max(0.0, (now - _as_aware_utc(p.published_at)).total_seconds() / 86400.0), half_life)
        for p in signal.points
    ]
    total_weight = sum(weights)
    weighted_avg = sum(w * p.sentiment for w, p in zip(weights, signal.points)) / total_weight if total_weight else 0.0
    recent = sorted(signal.points, key=lambda p: p.published_at, reverse=True)[:3]
    reasons = [p.description for p in recent]
    return clamp(weighted_avg, -1.0, 1.0), reasons, signal.item_ids, "ok"


def _decay_release(raw: float, reason: str, quality: str, point: MacroPoint, now: dt.datetime, half_life_table: dict[str, float], horizon: str) -> tuple[float, str, str | None]:
    """Apply release-age decay to an already-computed trend_signal result.

    Returns (decayed_raw, annotated_reason, as_of_date_str).
    """
    period_date = parse_period_date(point.period)
    if quality != "ok" or period_date is None:
        return raw, reason, point.period or None
    anchor = reference_period_end(period_date, point.frequency)
    age_days = max(0, (now.date() - anchor).days)
    factor = decay_factor(age_days, half_life_table[horizon])
    decayed = clamp(raw * factor, -1.0, 1.0)
    annotated = f"{reason} [stáří {age_days} dní, časová váha {cz(factor, '.2f')} pro horizont {HORIZON_CZ[horizon]}]"
    return decayed, annotated, period_date.isoformat()


def _pillar_real_yields(inp: XauInputs, horizon: str, now: dt.datetime) -> PillarResult:
    raw, reason, quality = trend_signal(
        inp.real_yield_10y.actual,
        inp.real_yield_10y.previous,
        higher_is_bullish=False,  # rising real yields raise gold's opportunity cost -> bearish
        reason_label=_lbl("Reálný výnos 10letých dluhopisů v % (FRED DFII10)", inp.real_yield_10y),
        scale=0.25, mode="absolute",  # a 0.25pp move vs ~1 month earlier = full signal
    )
    # Daily series: no age decay — this is the current known state of the world at every horizon.
    return PillarResult(
        "real_yields", PILLAR_WEIGHTS["real_yields"], raw, [reason], data_quality=quality, gaps=_gaps((quality, reason)),
        source="FRED DFII10 (výnos 10letých dluhopisů chráněných proti inflaci)", as_of=inp.real_yield_10y.period or None,
    )


def _pillar_usd(inp: XauInputs, horizon: str, now: dt.datetime) -> PillarResult:
    raw, reason, quality = trend_signal(
        inp.usd_index.actual,
        inp.usd_index.previous,
        higher_is_bullish=False,  # stronger USD -> bearish gold (inverse correlation)
        reason_label=_lbl("Obchodně vážený index USD (FRED DTWEXBGS)", inp.usd_index),
        scale=0.02,  # a 2% move vs ~1 month earlier = full signal
    )
    return PillarResult(
        "usd", PILLAR_WEIGHTS["usd"], raw, [reason], data_quality=quality, gaps=_gaps((quality, reason)),
        source="FRED DTWEXBGS (obchodně vážený index amerického dolaru)", as_of=inp.usd_index.period or None,
    )


def _pillar_inflation(inp: XauInputs, horizon: str, now: dt.datetime) -> PillarResult:
    """Cooling inflation -> dovish Fed path expected -> bullish gold (and vice versa).

    This mirrors the worked example in the brief (section 8): "inflation data
    cooling" was listed as a LONG driver alongside a dovish Fed and falling
    yields — inflation surprises are read through their effect on Fed policy,
    not as a standalone "inflation = gold up" rule. Both prints are monthly,
    so their influence decays with horizon-specific half-life (see module
    docstring) — a hot CPI print from 6 weeks ago should barely move the
    intraday view anymore, but still counts for something on 1-3m.
    """
    cpi_raw, cpi_reason, cpi_quality = trend_signal(
        inp.core_cpi.actual, inp.core_cpi.previous, higher_is_bullish=False,
        reason_label=_lbl("Jádrová inflace CPI meziročně v % (FRED CPILFESL)", inp.core_cpi), scale=0.2, mode="absolute",
    )
    cpi_raw, cpi_reason, cpi_as_of = _decay_release(
        cpi_raw, cpi_reason, cpi_quality, inp.core_cpi, now, MONTHLY_RELEASE_HALF_LIFE_DAYS, horizon
    )
    pce_raw, pce_reason, pce_quality = trend_signal(
        inp.core_pce.actual, inp.core_pce.previous, higher_is_bullish=False,
        reason_label=_lbl("Jádrová inflace PCE meziročně v % (FRED PCEPILFE)", inp.core_pce), scale=0.2, mode="absolute",
    )
    pce_raw, pce_reason, pce_as_of = _decay_release(
        pce_raw, pce_reason, pce_quality, inp.core_pce, now, MONTHLY_RELEASE_HALF_LIFE_DAYS, horizon
    )
    combined = clamp((cpi_raw + pce_raw) / 2.0, -1.0, 1.0)
    as_of = max(filter(None, [cpi_as_of, pce_as_of]), default=None)
    return PillarResult(
        "inflation", PILLAR_WEIGHTS["inflation"], combined, [cpi_reason, pce_reason],
        data_quality=_worst_quality(cpi_quality, pce_quality),
        gaps=_gaps((cpi_quality, cpi_reason), (pce_quality, pce_reason)),
        source="FRED CPILFESL + PCEPILFE (jádrová inflace CPI a PCE)", as_of=as_of,
    )


def _pillar_fed(inp: XauInputs, horizon: str, now: dt.datetime) -> PillarResult:
    rate_raw, rate_reason, rate_quality = trend_signal(
        inp.fed_funds_target.actual, inp.fed_funds_target.previous,
        higher_is_bullish=False,  # rate hikes -> bearish gold, cuts -> bullish
        reason_label=_lbl("Horní hranice sazby Fedu v % (FRED DFEDTARU)", inp.fed_funds_target), scale=0.5, mode="absolute",
    )
    # Daily-ish series, no age decay.
    reasons = [rate_reason]
    gaps = _gaps((rate_quality, rate_reason))

    tone_raw, tone_reasons, tone_ids, tone_quality = _weighted_news(inp.fed_tone_news, now, horizon)
    if tone_reasons:
        reasons.extend(tone_reasons)
    else:
        no_tone = "Fed tón z tiskových zpráv: žádná klasifikovaná zpráva k dispozici za sledované okno."
        reasons.append(no_tone)
        gaps.append(no_tone)

    combined = clamp(0.6 * rate_raw + 0.4 * tone_raw, -1.0, 1.0)
    return PillarResult(
        "fed", PILLAR_WEIGHTS["fed"], combined, reasons,
        data_quality=_worst_quality(rate_quality, tone_quality), gaps=gaps,
        source="FRED DFEDTARU + zprávy o tónu Fedu (RSS Fed/ECB/BoE + GDELT)", as_of=inp.fed_funds_target.period or None,
    )


def _pillar_economy(inp: XauInputs, horizon: str, now: dt.datetime) -> PillarResult:
    """Stronger economy -> less safe-haven demand + hawkish Fed room -> bearish gold."""
    gdp_raw, gdp_reason, gdp_quality = trend_signal(
        inp.gdp.actual, inp.gdp.previous, higher_is_bullish=False,
        reason_label=_lbl("Růst reálného HDP, mezičtvrtletně anualizovaně v % (FRED GDPC1)", inp.gdp), scale=1.5, mode="absolute",
    )
    gdp_raw, gdp_reason, gdp_as_of = _decay_release(
        gdp_raw, gdp_reason, gdp_quality, inp.gdp, now, MONTHLY_RELEASE_HALF_LIFE_DAYS, horizon
    )
    unemp_raw, unemp_reason, unemp_quality = trend_signal(
        inp.unemployment.actual, inp.unemployment.previous, higher_is_bullish=True,  # rising unemployment -> bullish gold
        reason_label=_lbl("Míra nezaměstnanosti v % (FRED UNRATE)", inp.unemployment), scale=0.2, mode="absolute",
    )
    unemp_raw, unemp_reason, unemp_as_of = _decay_release(
        unemp_raw, unemp_reason, unemp_quality, inp.unemployment, now, MONTHLY_RELEASE_HALF_LIFE_DAYS, horizon
    )
    nfp_raw, nfp_reason, nfp_quality = trend_signal(
        inp.nfp.actual, inp.nfp.previous, higher_is_bullish=False,
        reason_label=_lbl("Nová pracovní místa (NFP), měsíční změna v tisících (FRED PAYEMS)", inp.nfp), scale=150.0, mode="absolute",
    )
    nfp_raw, nfp_reason, nfp_as_of = _decay_release(
        nfp_raw, nfp_reason, nfp_quality, inp.nfp, now, MONTHLY_RELEASE_HALF_LIFE_DAYS, horizon
    )
    combined = clamp((gdp_raw + unemp_raw + nfp_raw) / 3.0, -1.0, 1.0)
    as_of = max(filter(None, [gdp_as_of, unemp_as_of, nfp_as_of]), default=None)
    return PillarResult(
        "economy", PILLAR_WEIGHTS["economy"], combined, [gdp_reason, unemp_reason, nfp_reason],
        data_quality=_worst_quality(gdp_quality, unemp_quality, nfp_quality),
        gaps=_gaps((gdp_quality, gdp_reason), (unemp_quality, unemp_reason), (nfp_quality, nfp_reason)),
        source="FRED GDPC1 + UNRATE + PAYEMS (HDP, nezaměstnanost, pracovní místa)", as_of=as_of,
    )


def _pillar_geopolitics(inp: XauInputs, horizon: str, now: dt.datetime) -> PillarResult:
    raw, reasons, ids, quality = _weighted_news(inp.geopolitics_news, now, horizon)
    if not reasons:
        reasons = ["Žádné relevantní geopolitické zprávy za sledované okno."]
    return PillarResult(
        "geopolitics", PILLAR_WEIGHTS["geopolitics"], raw, reasons, data_quality=quality,
        source="Zprávy o geopolitice (RSS centrálních bank + GDELT)", as_of=now.date().isoformat(),
    )


def _pillar_central_banks(inp: XauInputs, horizon: str, now: dt.datetime) -> PillarResult:
    raw, reasons, ids, quality = _weighted_news(inp.central_bank_buying_news, now, horizon)
    if not reasons:
        reasons = ["Žádné zprávy o nákupech zlata centrálními bankami za sledované okno."]
    return PillarResult(
        "central_banks", PILLAR_WEIGHTS["central_banks"], raw, reasons, data_quality=quality,
        source="Zprávy o nákupech zlata centrálními bankami (RSS + GDELT)", as_of=now.date().isoformat(),
    )


def _pillar_positioning(inp: XauInputs, horizon: str, now: dt.datetime) -> PillarResult:
    if inp.positioning is None:
        return PillarResult(
            "positioning", PILLAR_WEIGHTS["positioning"], 0.0,
            ["CFTC COT data k dispozici (konektor zapojen), ale pro tento cyklus nedostupná — pilíř neutrální, nevymýšlí se hodnota."],
            data_quality="unavailable", source="CFTC Commitments of Traders (zlato COMEX, týdně)",
        )
    raw, reason, quality = trend_signal(
        inp.positioning.actual, inp.positioning.previous, higher_is_bullish=True,
        reason_label=_lbl("Čisté dlouhé pozice spekulantů podle CFTC (zlato COMEX)", inp.positioning), scale=0.10,
    )
    raw, reason, as_of = _decay_release(raw, reason, quality, inp.positioning, now, WEEKLY_RELEASE_HALF_LIFE_DAYS, horizon)
    return PillarResult(
        "positioning", PILLAR_WEIGHTS["positioning"], raw, [reason], data_quality=quality,
        source="CFTC Commitments of Traders (zlato COMEX, týdně, zveřejňováno se zpožděním)", as_of=as_of,
    )


def _build_scenarios(pillars: list[PillarResult], bias: str, score: float) -> dict[str, Scenario]:
    # Bucket by the SAME threshold as PillarResult.impact (0.1) — using a
    # different cutoff here caused a real bug: a pillar could be "bearish"
    # by .impact but land in the neutral bucket below, producing a
    # nonsensical "would need to flip from bearish to bearish" invalidation
    # line (caught via live smoke test, see docs/DECISIONS.md).
    ok_pillars = [p for p in pillars if p.has_evidence]
    bullish_pillars = [p for p in ok_pillars if p.impact == "bullish"]
    bearish_pillars = [p for p in ok_pillars if p.impact == "bearish"]
    neutral_ok = [p for p in ok_pillars if p.impact == "neutral"]

    by_impact = sorted(ok_pillars, key=lambda p: abs(p.points), reverse=True)
    base_supports = [p.reasons[0] for p in by_impact[:4]] or ["Žádný pilíř aktuálně nemá dostatek dat."]
    base_would_change = [
        f"Obrat trendu v pilíři {PILLAR_DISPLAY[p.name]} (aktuálně {IMPACT_CZ[p.impact]}, {cz(p.points, '+.1f')} b. z {p.weight:.0f})"
        for p in by_impact[:3]
    ]
    base_risks = [g for p in pillars if p.data_quality != "ok" for g in (p.gaps or p.reasons[:1])] or ["Žádná datová mezera k okamžiku výpočtu."]

    bull_supports = [p.reasons[0] for p in bullish_pillars] or ["Zatím žádný pilíř není jednoznačně býčí."]
    bull_would_need = [
        f"Pilíř {PILLAR_DISPLAY[p.name]} by se musel obrátit z {IMPACT_CZ_GEN[p.impact]} na býčí (aktuálně {cz(p.points, '+.1f')} b.)"
        for p in bearish_pillars + neutral_ok
    ] or ["Všechny pilíře s daty už jsou býčí — scénář je blízko základnímu."]
    bull_risks = [
        "Jestřábí překvapení od Fedu (rychlejší či vyšší zvyšování sazeb, než trh čeká).",
        "Silnější než očekávaná ekonomická data (NFP, HDP) posilující dolar.",
        "Prudké zklidnění geopolitického rizika (mírové dohody, deeskalace).",
    ]

    bear_supports = [p.reasons[0] for p in bearish_pillars] or ["Zatím žádný pilíř není jednoznačně medvědí."]
    bear_would_need = [
        f"Pilíř {PILLAR_DISPLAY[p.name]} by se musel obrátit z {IMPACT_CZ_GEN[p.impact]} na medvědí (aktuálně {cz(p.points, '+.1f')} b.)"
        for p in bullish_pillars + neutral_ok
    ] or ["Všechny pilíře s daty už jsou medvědí — scénář je blízko základnímu."]
    bear_risks = [
        "Holubičí překvapení od Fedu (rychlejší či hlubší snižování sazeb, než trh čeká).",
        "Slabší než očekávaná ekonomická data oslabující dolar.",
        "Eskalace geopolitického rizika zvyšující poptávku po zlatě jako bezpečném přístavu.",
    ]

    return {
        "base": Scenario(
            "base",
            f"Aktuální fundamentální výhled {BIAS_CZ[bias]} ({score:.0f}/100) přetrvá, pokud se hlavní faktory nezmění.",
            base_supports, base_would_change, base_risks,
        ),
        "bull": Scenario(
            "bull",
            "Fundamentální prostředí se posouvá výrazněji ve prospěch růstu zlata (LONG).",
            bull_supports, bull_would_need, bull_risks,
        ),
        "bear": Scenario(
            "bear",
            "Fundamentální prostředí se posouvá výrazněji ve prospěch poklesu zlata (SHORT).",
            bear_supports, bear_would_need, bear_risks,
        ),
    }


def _build_invalidation(scenarios: dict[str, Scenario], bias: str, now: dt.datetime) -> list[str]:
    if bias == "LONG":
        items = list(scenarios["bear"].would_change)
    elif bias == "SHORT":
        items = list(scenarios["bull"].would_change)
    else:
        items = list(scenarios["bull"].would_change) + list(scenarios["bear"].would_change)

    next_fomc = _next_fomc_date(now)
    if next_fomc:
        d = dt.date.fromisoformat(next_fomc)
        items.append(
            f"Příští rozhodnutí FOMC o sazbách: {d.day}. {d.month}. {d.year} (zdroj: federalreserve.gov/monetarypolicy/"
            f"fomccalendars.htm) — může výrazně posunout pilíř Fed."
        )
    return items or ["Žádný konkrétní invalidační faktor nebyl identifikován z aktuálních dat."]


def compute_xauusd_score(inp: XauInputs, horizon: str, now: dt.datetime | None = None) -> InstrumentScoreResult:
    if horizon not in SUPPORTED_HORIZONS:
        raise ValueError(f"Nepodporovaný horizont '{horizon}', povolené: {SUPPORTED_HORIZONS}")
    now = now or dt.datetime.now(dt.timezone.utc)
    pillars = [
        _pillar_fed(inp, horizon, now),
        _pillar_inflation(inp, horizon, now),
        _pillar_real_yields(inp, horizon, now),
        _pillar_usd(inp, horizon, now),
        _pillar_economy(inp, horizon, now),
        _pillar_geopolitics(inp, horizon, now),
        _pillar_central_banks(inp, horizon, now),
        _pillar_positioning(inp, horizon, now),
    ]
    signed_total = sum(p.points for p in pillars)
    score = signed_total_to_score(signed_total, max_abs=100.0)
    bias = bias_from_score(score)

    ranked = sorted(pillars, key=lambda p: p.points, reverse=True)
    drivers = [f"{PILLAR_DISPLAY[p.name]}: {r}" for p in ranked if p.points > 5 for r in p.reasons[:1]]
    contrarian = [f"{PILLAR_DISPLAY[p.name]}: {r}" for p in ranked if p.points < -5 for r in p.reasons[:1]]
    risks = [gap for p in pillars if p.data_quality != "ok" for gap in (p.gaps or p.reasons[:1])]
    if not risks:
        risks = ["Žádná datová mezera zjištěna k okamžiku výpočtu."]

    scenarios = _build_scenarios(pillars, bias, score)
    invalidation = _build_invalidation(scenarios, bias, now)

    return InstrumentScoreResult(
        instrument_code="XAUUSD",
        computed_at=now,
        horizon=horizon,
        score=score,
        bias=bias,
        pillars=pillars,
        drivers=drivers,
        contrarian=contrarian,
        risks=risks,
        scenarios=scenarios,
        invalidation=invalidation,
    )
