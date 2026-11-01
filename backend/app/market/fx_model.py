"""Fundamental score of a currency pair, −10 … +10 (the overview cards).

Every category compares the two currencies of the pair; positive = the first currency
(EUR in EUR/USD) should be stronger. Rates and inflation weigh most, as they move FX most and add up to 10:

    category        range   from
    Úrokové sazby    ±3     change of the 2-year yield gap over 3 months + priced hikes/cuts
    Inflace          ±2     core (else headline) inflation: level vs. 2 % target and its trend
    Ekonomika        ±2     real GDP growth, q/q annualized
    Trh práce        ±1     change of the unemployment rate over 3 months
    COT              ±1     hedge funds (leveraged funds) in the currency future, 4-week flow + level
    Sezónnost        ±1     same calendar days in the last 10 years (daily data)

A category without data on either side counts as missing: the score is then scaled
from the categories that exist and the UI lists what is missing. Every rule is a
fixed threshold written next to it; nothing is estimated.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

RANGES = {"rates": 3, "inflation": 2, "growth": 2, "labor": 1, "cot": 1, "season": 1}
LABELS = {"rates": "Úrokové sazby", "inflation": "Inflace", "growth": "Ekonomika (HDP)", "labor": "Trh práce",
          "cot": "COT – hedgeové fondy", "season": "Sezónnost"}
ORDER = ["rates", "inflation", "growth", "labor", "cot", "season"]
COUNTRY = {"USD": "USA", "EUR": "eurozóna", "GBP": "Británie", "JPY": "Japonsko"}
COUNTRY_GEN = {"USD": "americká", "EUR": "eurozónová", "GBP": "britská", "JPY": "japonská"}
BANK = {"USD": "Fed", "EUR": "ECB", "GBP": "BoE", "JPY": "BoJ"}


@dataclass
class CurrencyData:
    code: str
    cpi: dict[str, float] = field(default_factory=dict)  # y/y %, monthly
    core: dict[str, float] = field(default_factory=dict)  # y/y %, monthly
    unemp: dict[str, float] = field(default_factory=dict)  # %, monthly
    gdp_qoq: dict[str, float] = field(default_factory=dict)  # % q/q (not annualized), quarterly
    rate2y: dict[str, float] = field(default_factory=dict)  # 2-year yield, daily
    policy: dict[str, float] = field(default_factory=dict)  # policy / overnight rate, daily or monthly
    notes: list[str] = field(default_factory=list)


def _num(v: float, digits: int = 1, signed: bool = False) -> str:
    s = f"{v:+.{digits}f}" if signed else f"{v:.{digits}f}"
    return s.replace(".", ",").replace("-", "−")


def _clip(x: float, lim: int) -> int:
    return int(max(-lim, min(lim, round(x))))


def _last(series: dict[str, float]) -> tuple[str, float] | None:
    if not series:
        return None
    d = max(series)
    return d, series[d]


def _before(series: dict[str, float], day: str) -> float | None:
    keys = [d for d in series if d <= day]
    return series[max(keys)] if keys else None


def _shift_months(day: str, months: int) -> str:
    y, m = int(day[:4]), int(day[5:7]) - months
    while m <= 0:
        m, y = m + 12, y - 1
    return f"{y:04d}-{m:02d}-{day[8:10]}"


def _period(day: str) -> str:
    return f"{int(day[5:7])}/{day[:4]}"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


# --- per-currency pieces ---------------------------------------------------------------

def inflation(c: CurrencyData) -> dict | None:
    # core inflation when it is current; a core series that stopped (e.g. a discontinued
    # flash estimate) must not win over a fresh headline figure
    core_last, cpi_last = _last(c.core), _last(c.cpi)
    use_core = core_last and (not cpi_last or core_last[0] >= _shift_months(cpi_last[0], 2))
    series, kind = (c.core, "jádrová") if use_core else (c.cpi, "celková")
    last = _last(series)
    if not last:
        return None
    day, level = last
    prev = _before(series, _shift_months(day, 3))
    trend = level - prev if prev is not None else 0.0
    pts = 2 if level >= 4.0 else 1 if level >= 3.0 else -2 if level <= 1.0 else -1 if level <= 1.5 else 0
    pts += 1 if trend >= 0.3 else -1 if trend <= -0.3 else 0
    word = "zrychluje" if trend >= 0.3 else "zpomaluje" if trend <= -0.3 else "je stabilní"
    return {"score": _clip(pts, 2), "level": level, "trend": trend, "as_of": day,
            "text": f"{_cap(COUNTRY[c.code])}: {kind} inflace {_num(level)} % ({_period(day)}), {word}"}


def growth(c: CurrencyData) -> dict | None:
    last = _last(c.gdp_qoq)
    if not last:
        return None
    day, q = last
    ann = ((1 + q / 100) ** 4 - 1) * 100
    pts = 2 if ann >= 3 else 1 if ann >= 2 else -2 if ann < 0 else -1 if ann < 1 else 0
    return {"score": pts, "annualized": ann, "as_of": day,
            "text": f"{_cap(COUNTRY[c.code])}: HDP {_num(q, 1, True)} % q/q (≈ {_num(ann)} % ročně, Q{(int(day[5:7]) - 1) // 3 + 1})"}


def labor(c: CurrencyData) -> dict | None:
    last = _last(c.unemp)
    if not last:
        return None
    day, level = last
    prev = _before(c.unemp, _shift_months(day, 3))
    if prev is None:
        return None
    ch = level - prev
    pts = 1 if ch <= -0.2 else -1 if ch >= 0.2 else 0
    word = "klesá" if ch <= -0.2 else "roste" if ch >= 0.2 else "nemění se"
    return {"score": pts, "level": level, "change": ch, "as_of": day,
            "text": f"{_cap(COUNTRY[c.code])}: nezaměstnanost {_num(level)} % a {word} ({_num(ch, 1, True)} p.b. za 3 měsíce)"}


def _rate_series(c: CurrencyData) -> tuple[dict[str, float], str]:
    return (c.rate2y, "2letý výnos") if c.rate2y else (c.policy, "sazba centrální banky")


def expectations(c: CurrencyData) -> dict | None:
    """2-year yield above the policy rate = the market prices hikes; below = cuts."""
    if not c.rate2y or not c.policy:
        return None
    y2, pol = _last(c.rate2y), _last(c.policy)
    gap = y2[1] - pol[1]
    pts = 1 if gap >= 0.25 else -1 if gap <= -0.25 else 0
    word = "zvyšování" if pts > 0 else "snižování" if pts < 0 else "žádnou velkou změnu"
    return {"score": pts, "gap": gap, "text": f"{BANK[c.code]}: trh čeká {word} sazeb (2letý výnos {_num(y2[1], 2)} % vs. sazba {_num(pol[1], 2)} %)"}


# --- the pair ----------------------------------------------------------------------------

def _component(key: str, score: int | None, text: str, details: list[str] | None = None) -> dict:
    return {"key": key, "label": LABELS[key], "score": score, "max": RANGES[key], "text": text, "details": details or []}


def rates_component(base: CurrencyData, quote: CurrencyData, now: dt.datetime) -> dict:
    sb, nb = _rate_series(base)
    sq, nq = _rate_series(quote)
    if not sb or not sq:
        return _component("rates", None, "Chybí úrokové sazby jedné z měn.")
    day = now.date().isoformat()
    past = (now.date() - dt.timedelta(days=91)).isoformat()
    b_now, q_now = _before(sb, day), _before(sq, day)
    b_then, q_then = _before(sb, past), _before(sq, past)
    if None in (b_now, q_now, b_then, q_then):
        return _component("rates", None, "Krátká historie sazeb.")
    gap_now, gap_then = b_now - q_now, b_then - q_then
    move = gap_now - gap_then
    pts = 2 if move >= 0.25 else 1 if move >= 0.10 else -2 if move <= -0.25 else -1 if move <= -0.10 else 0
    eb, eq = expectations(base), expectations(quote)
    exp_pts = _clip((eb["score"] if eb else 0) - (eq["score"] if eq else 0), 1)
    total = _clip(pts + exp_pts, 3)
    lead = base.code if move > 0 else quote.code
    text = (f"Rozdíl sazeb {base.code}–{quote.code} je {_num(gap_now, 2, True)} p.b. a za 3 měsíce se změnil o "
            f"{_num(move, 2, True)} p.b." + (f" — výhoda se přelévá k {lead}." if abs(move) >= 0.10 else " — beze změny."))
    details = [f"{base.code}: {nb} {_num(b_now, 2)} %", f"{quote.code}: {nq} {_num(q_now, 2)} %"]
    details += [e["text"] for e in (eb, eq) if e]
    if not base.rate2y or not quote.rate2y:
        details.append("U jedné měny chybí 2letý výnos zdarma — použita sazba centrální banky.")
    return _component("rates", total, text, details)


def pair_component(key: str, fn, base: CurrencyData, quote: CurrencyData) -> dict:
    b, q = fn(base), fn(quote)
    if not b or not q:
        miss = [x.code for x, v in ((base, b), (quote, q)) if not v]
        return _component(key, None, f"Chybí data: {', '.join(COUNTRY[m] for m in miss)}.")
    score = _clip(b["score"] - q["score"], RANGES[key])
    stronger = base.code if score > 0 else quote.code if score < 0 else None
    verdict = f" → mluví pro {stronger}." if stronger else " → vyrovnané."
    return _component(key, score, f"{b['text']}; {q['text']}{verdict}", [b["text"], q["text"]])


def cot_component(rows: list[dict] | None, invert: bool, label: str) -> dict:
    """Hedge funds (leveraged funds) in the currency future; `invert` for USD/JPY (yen future)."""
    if not rows or len(rows) < 10:
        return _component("cot", None, "COT data chybí.")
    pct = [r["lev_long"] / (r["lev_long"] + r["lev_short"]) * 100 for r in rows if r["lev_long"] + r["lev_short"]]
    p, ch4 = pct[-1], pct[-1] - pct[-5]
    flow = 1 if ch4 >= 8 else -1 if ch4 <= -8 else 0
    level = 1 if p >= 65 else -1 if p <= 35 else 0
    s = flow if flow else level
    s = -s if invert else s
    text = (f"Hedgeové fondy v {label}: {_num(p, 0)} % long ({_num(ch4, 1, True)} p.b. za 4 týdny)"
            + (" — pro pár to čteme obráceně." if invert else "."))
    return _component("cot", s, text)


def season_component(view: dict | None, invert: bool = False) -> dict:
    if not view or not view.get("next30"):
        return _component("season", None, "Málo historie pro sezónnost.")
    n = view["next30"]
    lean = view.get("lean", 0)
    text = f"Příštích 30 dní: pár rostl v {n['up']} z {n['n']} let, průměr {_num(n['avg'], 1, True)} %."
    if view.get("texts"):
        text += " " + view["texts"][0]
    return _component("season", lean, text)


def verdict(score10: int) -> dict:
    if score10 >= 6:
        word, bias = "Silně pozitivní fundamentální výhled", "LONG"
    elif score10 >= 3:
        word, bias = "Mírně pozitivní fundamentální výhled", "LONG"
    elif score10 <= -6:
        word, bias = "Silně negativní fundamentální výhled", "SHORT"
    elif score10 <= -3:
        word, bias = "Mírně negativní fundamentální výhled", "SHORT"
    else:
        word, bias = "Neutrální fundamentální výhled", "NEUTRÁLNÍ"
    return {"word": word, "bias": bias}


def score_pair(base: CurrencyData, quote: CurrencyData, cot_rows: list[dict] | None, cot_invert: bool, cot_label: str,
               season: dict | None, now: dt.datetime) -> dict:
    comps = [
        rates_component(base, quote, now),
        pair_component("inflation", inflation, base, quote),
        pair_component("growth", growth, base, quote),
        pair_component("labor", labor, base, quote),
        cot_component(cot_rows, cot_invert, cot_label),
        season_component(season),
    ]
    return finish(comps)


def finish(comps: list[dict]) -> dict:
    have = [c for c in comps if c["score"] is not None]
    raw = sum(c["score"] for c in have)
    possible = sum(c["max"] for c in have)
    score10 = round(raw / possible * 10) if possible else 0
    missing = [c["label"] for c in comps if c["score"] is None]
    return {"components": comps, "raw": raw, "possible": possible, "score10": max(-10, min(10, score10)), "missing": missing,
            **verdict(score10)}
