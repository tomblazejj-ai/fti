"""Fundamental calendar for gold: which official US releases are coming, how
much they matter for XAUUSD, how they usually move it, and the last value.

Importance is a fixed editorial rating based on how the release feeds the
XAUUSD model (Fed and inflation pillars carry the most weight) — it is a
rule, not a measurement, and the UI says so.

Sources: FRED release calendar (CPI, NFP, PPI, JOLTS, retail sales, jobless
claims, GDP, PCE), BEA ICS (tells which GDP estimate it is), FOMC dates from
federalreserve.gov. One release on one day appears once (BEA wins over FRED
because it names the estimate).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from app.connectors.calendar_ics import IcsEvent

PRAGUE = ZoneInfo("Europe/Prague")
NEW_YORK = ZoneInfo("America/New_York")
WINDOW_PAST_DAYS = 7
WINDOW_AHEAD_DAYS = 45
INSTRUMENT = "XAUUSD"
# FOMC statement time, published on every meeting page of federalreserve.gov
# ("2:00 p.m. EDT"); the press conference follows at 2:30 p.m.
FOMC_STATEMENT = dt.time(14, 0)
# The countdown to the next red (high-impact) release and the hour after it.
LOCK_HOURS = 2
CONFIRM_MINUTES = 60
HISTORY_POINTS = 6


@dataclass(frozen=True)
class Rule:
    key: str  # family — one per release type, used for de-duplication
    pattern: str  # matched against the source's title
    name: str
    importance: int  # 3 vysoká, 2 střední, 1 nízká
    impact: str  # how it usually moves gold
    macro_key: str | None = None  # key in the FRED macro dict for "minulá hodnota"
    up_if: str = ""  # what result would push gold up
    down_if: str = ""  # … and down


RULES: list[Rule] = [
    Rule("cpi", r"^(fred:cpi\||Consumer Price Index)", "Inflace CPI (USA)", 3,
         "Vyšší inflace než čekal trh → Fed spíš drží vysoké sazby → zlato obvykle dolů. Nižší → zlato nahoru.", "core_cpi",
         "inflace zpomalí", "inflace bude vyšší"),
    Rule("nfp", r"^(fred:nfp\||Employment Situation)", "Zaměstnanost NFP a nezaměstnanost (USA)", 3,
         "Silný trh práce (hodně nových míst) → silnější dolar a výnosy → zlato obvykle dolů. Slabý → zlato nahoru.", "nfp",
         "přibude málo pracovních míst", "přibude hodně pracovních míst"),
    Rule("pce", r"^(fred:pce\||Personal Income and Outlays)", "Inflace PCE – oblíbené měřítko Fedu (USA)", 3,
         "Vyšší PCE inflace → jestřábí Fed → zlato obvykle dolů. Nižší → zlato nahoru.", "core_pce",
         "PCE inflace zpomalí", "PCE inflace bude vyšší"),
    Rule("gdp", r"^(Gross Domestic Product|GDP)\b.*Advance", "HDP – první odhad (USA)", 3,
         "Silný růst ekonomiky → vyšší výnosy a dolar → zlato spíš dolů. Slabý růst → zlato nahoru.", "gdp",
         "ekonomika zpomalí", "ekonomika poroste rychle"),
    Rule("gdp", r"^(Gross Domestic Product|GDP)\b.*Second", "HDP – druhý odhad (USA)", 2,
         "Revize prvního odhadu; trh hýbe jen větší změna.", "gdp", "revize dolů", "revize nahoru"),
    Rule("gdp", r"^(Gross Domestic Product|GDP)\b.*Third", "HDP – třetí odhad (USA)", 1,
         "Poslední revize, obvykle bez velké reakce.", "gdp", "revize dolů", "revize nahoru"),
    Rule("gdp", r"^fred:gdp\|", "HDP (USA)", 2,
         "Silný růst → zlato spíš dolů, slabý → nahoru.", "gdp", "ekonomika zpomalí", "ekonomika poroste rychle"),
    Rule("ppi", r"^(fred:ppi\||Producer Price Index)", "Ceny výrobců PPI (USA)", 2,
         "Předzvěst spotřebitelské inflace; vyšší → zlato spíš dolů.", None, "ceny výrobců zpomalí", "ceny výrobců zrychlí"),
    Rule("jolts", r"^(fred:jolts\||Job Openings and Labor Turnover)", "Volná pracovní místa JOLTS (USA)", 2,
         "Hodně volných míst = silný trh práce → zlato spíš dolů.", None, "volných míst ubude", "volných míst přibude"),
    Rule("retail", r"^fred:retail\|", "Maloobchodní tržby (USA)", 2,
         "Silná spotřeba → vyšší výnosy → zlato spíš dolů. Slabá → nahoru.", None, "tržby zklamou", "tržby překvapí silou"),
    Rule("claims", r"^fred:claims\|", "Žádosti o podporu v nezaměstnanosti (USA, týdně)", 1,
         "Víc žádostí = slábnoucí trh práce → zlato spíš nahoru.", None, "žádostí přibude", "žádostí ubude"),
    Rule("eci", r"^Employment Cost Index", "Náklady práce ECI (USA)", 2,
         "Rychlý růst mezd živí inflaci → zlato spíš dolů.", None, "mzdy zpomalí", "mzdy zrychlí"),
]

FOMC_RULE = Rule("fomc", "", "Rozhodnutí Fedu o sazbách (FOMC)", 3,
                 "Zvýšení sazeb nebo jestřábí tón → zlato dolů. Snížení nebo holubičí tón → zlato nahoru. Největší událost pro zlato.",
                 None, "Fed sníží sazby nebo zjemní tón", "Fed zůstane přísný nebo zvýší sazby")

@dataclass(frozen=True)
class Detail:
    """What the event detail shows: how often it comes, why traders care, the usual
    effect on the dollar and the last values from the official FRED series."""
    freq: str
    why: str
    usd: str
    series: str | None = None  # FRED series with the history
    transform: str = "level"  # yoy | mom_diff | mom_pct | qoq_ann | qoq_pct | level | steps
    label: str = ""
    unit: str = ""
    digits: int = 1
    scale: float = 1.0
    link: str = ""  # official page of the release


DETAILS: dict[str, Detail] = {
    "cpi": Detail("Měsíčně, obvykle mezi 10. a 15. dnem.",
                  "Inflace rozhoduje, jestli Fed drží, zvyšuje nebo snižuje sazby. Sazby jsou pro zlato nejsilnější hybatel — "
                  "zlato nenese úrok, takže vysoké sazby ho znevýhodňují.",
                  "Vyšší inflace → trh čeká přísnější Fed → dolar obvykle posílí.",
                  "CPILFESL", "yoy", "Jádrová inflace CPI", "% r/r", 1, link="https://www.bls.gov/cpi/"),
    "nfp": Detail("Měsíčně, obvykle první pátek v měsíci.",
                  "Nejsledovanější zpráva o trhu práce. Silné zaměstnání znamená, že ekonomika snese vyšší sazby; "
                  "slabé otevírá cestu ke snižování.",
                  "Hodně nových míst → silnější dolar; málo → slabší dolar.",
                  "PAYEMS", "mom_diff", "Nová pracovní místa", "tis.", 0, link="https://www.bls.gov/ces/"),
    "pce": Detail("Měsíčně, ke konci měsíce.",
                  "Fed cílí právě na PCE inflaci (2 %), proto ji bere vážněji než CPI. Trh ji ale často odhadne předem z CPI a PPI.",
                  "Vyšší PCE inflace → přísnější Fed → silnější dolar.",
                  "PCEPILFE", "yoy", "Jádrová inflace PCE", "% r/r", 1,
                  link="https://www.bea.gov/data/personal-consumption-expenditures-price-index"),
    "gdp": Detail("Čtvrtletně, ve třech odhadech (první, druhý, třetí).",
                  "Celkový výkon ekonomiky. Rychlý růst znamená silný dolar a vyšší výnosy, zpomalení prostor pro nižší sazby. "
                  "Trhem hýbe hlavně první odhad.",
                  "Silný růst → silnější dolar.",
                  "GDPC1", "qoq_ann", "Růst reálného HDP", "% anualizovaně", 1, link="https://www.bea.gov/data/gdp/gross-domestic-product"),
    "ppi": Detail("Měsíčně, kolem zveřejnění CPI.",
                  "Ceny výrobců se často propisují do spotřebitelských cen — předzvěst inflace.",
                  "Vyšší PPI → obava z inflace → silnější dolar.",
                  "PPIFIS", "yoy", "Ceny výrobců PPI (konečná poptávka)", "% r/r", 1, link="https://www.bls.gov/ppi/"),
    "jolts": Detail("Měsíčně, s měsíčním zpožděním.",
                    "Kolik lidí firmy hledají. Hodně volných míst = napjatý trh práce a tlak na mzdy.",
                    "Víc volných míst → silnější dolar.",
                    "JTSJOL", "level", "Volná pracovní místa", "mil.", 2, scale=0.001, link="https://www.bls.gov/jlt/"),
    "retail": Detail("Měsíčně, kolem 15. dne.",
                     "Spotřeba domácností tvoří zhruba dvě třetiny americké ekonomiky.",
                     "Silné tržby → silnější dolar.",
                     "RSAFS", "mom_pct", "Maloobchodní tržby", "% m/m", 1, link="https://www.census.gov/retail/index.html"),
    "claims": Detail("Týdně, každý čtvrtek.",
                     "Nejrychlejší pohled na propouštění. Jeden týden trhem hýbe málo, důležitý je trend.",
                     "Víc žádostí (slábnoucí trh práce) → slabší dolar.",
                     "ICSA", "level", "Nové žádosti o podporu", "tis.", 0, scale=0.001, link="https://www.dol.gov/ui/data.pdf"),
    "eci": Detail("Čtvrtletně.",
                  "Nejúplnější měřítko růstu mezd a benefitů; Fed ho sleduje kvůli inflaci z mzdových nákladů.",
                  "Rychlý růst mezd → silnější dolar.",
                  "ECIALLCIV", "qoq_pct", "Náklady práce ECI", "% q/q", 1, link="https://www.bls.gov/eci/"),
    "fomc": Detail("8× ročně. Prohlášení ve 14:00 newyorského času, tisková konference o 30 minut později.",
                   "Fed přímo určuje sazby. Kromě samotného rozhodnutí hýbe trhem tón prohlášení a tiskové konference — "
                   "co Fed naznačí o dalších krocích.",
                   "Zvýšení sazeb nebo jestřábí tón → silnější dolar; snížení nebo holubičí tón → slabší dolar.",
                   "DFEDTARU", "steps", "Horní hranice sazby Fedu", "%", 2,
                   link="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"),
}
HISTORY_SERIES = sorted({d.series for d in DETAILS.values() if d.series})

MACRO_TEXT = {
    "core_cpi": ("jádrová inflace CPI", "% r/r"),
    "core_pce": ("jádrová inflace PCE", "% r/r"),
    "nfp": ("nová pracovní místa", "tis."),
    "gdp": ("růst HDP", "% anualizovaně"),
}


def _num(v: float, digits: int = 1) -> str:
    return f"{v:,.{digits}f}".replace(",", " ").replace(".", ",").replace("-", "−")


def _previous(macro: dict, key: str | None) -> str | None:
    if not key or key not in macro:
        return None
    p = macro[key]
    actual = getattr(p, "actual", None)
    if actual is None:
        return None
    label, unit = MACRO_TEXT[key]
    digits = 0 if key == "nfp" else 1
    period = getattr(p, "period", "") or ""
    if period and key == "gdp":
        when = f"Q{(int(period[5:7]) - 1) // 3 + 1} {period[:4]}"
    elif period:
        when = f"{int(period[5:7])}/{period[:4]}"
    else:
        when = ""
    return f"{label} {_num(actual, digits)} {unit}" + (f" (za {when})" if when else "")


def _match(summary: str) -> Rule | None:
    return next((r for r in RULES if re.search(r.pattern, summary, re.IGNORECASE)), None)


def _shift(day: str, months: int) -> str:
    y, m = int(day[:4]), int(day[5:7]) - months
    while m <= 0:
        m, y = m + 12, y - 1
    return f"{y:04d}-{m:02d}-01"


def _at(series: dict[str, float], day: str) -> float | None:
    """Value of a monthly/quarterly series; one missing month (e.g. October 2025, when the US
    shutdown stopped the CPI survey) is bridged by the average of its neighbours."""
    if day in series:
        return series[day]
    before, after = series.get(_shift(day, 1)), series.get(_shift(day, -1))
    return (before * after) ** 0.5 if before and after else None


def _period(day: str, how: str) -> str:
    if how in ("qoq_ann", "qoq_pct"):
        return f"Q{(int(day[5:7]) - 1) // 3 + 1} {day[:4]}"
    if how in ("level_w", "steps"):
        d = dt.date.fromisoformat(day)
        return f"{d.day}. {d.month}. {d.year}"
    return f"{int(day[5:7])}/{day[:4]}"


def history(series: dict[str, float] | None, d: Detail) -> list[dict]:
    """Last values of the release's FRED series, oldest first, already transformed
    the way the market reads them (y/y, m/m, annualized …)."""
    if not series or not d.series:
        return []
    days = sorted(series)
    out: list[dict] = []
    if d.transform == "steps":  # policy rate: every change with the day it took effect
        runs: list[tuple[str, float]] = []
        for day in days:
            if not runs or runs[-1][1] != series[day]:
                runs.append((day, series[day]))
        for day, v in runs[-HISTORY_POINTS:]:
            out.append({"period": f"od {_period(day, 'steps')}", "value": round(v, d.digits),
                        "text": f"{_num(v, d.digits)} {d.unit}"})
        return out
    weekly = d.transform == "level" and len(days) > 2 and (dt.date.fromisoformat(days[-1]) - dt.date.fromisoformat(days[-2])).days < 20
    for day in days:
        v = series[day]
        if d.transform == "yoy":
            prev = _at(series, _shift(day, 12))
            val = (v / prev - 1) * 100 if prev else None
        elif d.transform in ("mom_diff", "mom_pct", "qoq_ann", "qoq_pct"):
            prev = _at(series, _shift(day, 3 if d.transform.startswith("qoq") else 1))
            if prev is None or not prev:
                val = None
            elif d.transform == "mom_diff":
                val = v - prev
            elif d.transform == "qoq_ann":
                val = ((v / prev) ** 4 - 1) * 100
            else:
                val = (v / prev - 1) * 100
        else:
            val = v * d.scale
        if val is not None:
            out.append({"period": _period(day, "level_w" if weekly else d.transform), "value": round(val, d.digits),
                        "text": f"{'+' if d.transform in ('mom_diff', 'mom_pct', 'qoq_pct') and val > 0 else ''}"
                                f"{_num(val, d.digits)} {d.unit}"})
    return out[-HISTORY_POINTS:]


def _detail(key: str, series: dict[str, dict[str, float]]) -> dict | None:
    d = DETAILS.get(key)
    if not d:
        return None
    return {
        "freq": d.freq,
        "why": d.why,
        "usd": d.usd,
        "history_label": d.label,
        "history_unit": d.unit,
        "history": history(series.get(d.series or ""), d),
        "series": d.series,
        "series_url": f"https://fred.stlouisfed.org/series/{d.series}" if d.series else None,
        "link": d.link,
    }


def news_lock(events: list[dict], now: dt.datetime) -> dict:
    """The 2-hour rule at `now` (the UI recomputes it every few seconds from the same events)."""
    after = None
    for e in events:
        if e["importance"] < 3 or not e.get("datetime"):
            continue
        minutes = (dt.datetime.fromisoformat(e["datetime"]) - now).total_seconds() / 60
        if 0 < minutes <= LOCK_HOURS * 60:
            return {"state": "lock", "event": e["name"], "datetime": e["datetime"], "minutes": round(minutes),
                    "text": f"Za {round(minutes)} min vychází {e['name']} — počítej se zvýšenou volatilitou."}
        if -CONFIRM_MINUTES <= minutes <= 0:
            after = {"state": "after", "event": e["name"], "datetime": e["datetime"], "minutes": round(minutes),
                     "text": f"{e['name']} právě vyšla — trh na ni teď reaguje."}
    return after or {"state": "clear", "text": f"Žádná červená zpráva v příštích {LOCK_HOURS} hodinách."}


def _event(rule: Rule, date: str, time: str | None, start: dt.datetime | None, original: str, source: str,
           past: bool, macro: dict, detail: dict | None = None) -> dict:
    return {
        "key": rule.key,
        "date": date,
        "time": time,
        "datetime": start.isoformat() if start else None,
        "name": rule.name,
        "original": original,
        "importance": rule.importance,
        "impact": rule.impact,
        "up_if": rule.up_if,
        "down_if": rule.down_if,
        "previous": _previous(macro, rule.macro_key),
        "forecast": None,
        "source": source,
        "past": past,
        "instruments": [INSTRUMENT],
        "detail": detail,
    }


def build(ics_events: list[IcsEvent], fomc_dates: list[str], macro: dict, now: dt.datetime, notes: list[str],
          series: dict[str, dict[str, float]] | None = None) -> dict:
    """`series`: FRED history for the event details (HISTORY_SERIES), may be partial or empty."""
    series = series or {}
    details: dict[str, dict | None] = {}

    def detail(key: str) -> dict | None:
        if key not in details:
            details[key] = _detail(key, series)
        return details[key]

    out: list[dict] = []
    lo, hi = now - dt.timedelta(days=WINDOW_PAST_DAYS), now + dt.timedelta(days=WINDOW_AHEAD_DAYS)
    seen: set[tuple[str, str]] = set()
    # BEA first: it names the GDP estimate; FRED then only fills what is missing
    ordered = sorted(ics_events, key=lambda e: 0 if e.source == "BEA" else 1)
    for ev in ordered:
        rule = _match(ev.summary)
        if not rule or not (lo <= ev.start <= hi):
            continue
        local = ev.start.astimezone(PRAGUE)
        timed = not (ev.start.hour == 0 and ev.start.minute == 0 and ev.source == "FRED")
        date = (local.date() if timed else ev.start.date()).isoformat()
        if (rule.key, date) in seen:
            continue
        seen.add((rule.key, date))
        original = ev.summary.split("|", 1)[-1]
        out.append(_event(rule, date, local.strftime("%H:%M") if timed else None, ev.start if timed else None,
                          original, ev.source, ev.start < now, macro, detail(rule.key)))
    for d in fomc_dates:
        day = dt.date.fromisoformat(d)
        if lo.date() <= day <= hi.date():
            start = dt.datetime.combine(day, FOMC_STATEMENT, NEW_YORK).astimezone(dt.timezone.utc)
            out.append(_event(FOMC_RULE, d, start.astimezone(PRAGUE).strftime("%H:%M"), start,
                              "FOMC statement, 2:00 p.m. New York", "Fed", start < now, macro, detail("fomc")))
    out.sort(key=lambda e: (e["date"], e["time"] or "99"))
    upcoming = [e for e in out if not e["past"]]
    missing = [DETAILS[k].label for k in sorted({e["key"] for e in out}) if k in DETAILS and DETAILS[k].series
               and not (details.get(k) or {}).get("history")]
    if missing:
        notes = notes + [f"Historie hodnot teď chybí u: {', '.join(missing)} (FRED neodpověděl)."]
    return {
        "instrument": INSTRUMENT,
        "events": out,
        "next_high": next((e for e in upcoming if e["importance"] == 3), None),
        "lock": news_lock(out, now),
        "rules": {"lock_hours": LOCK_HOURS, "confirm_minutes": CONFIRM_MINUTES},
        "timezone": "Europe/Prague",
        "notes": notes + ["Prognózy (konsenzus trhu) zdarma a legálně k dispozici nejsou — u událostí je proto jen minulá hodnota "
                          "a historie z oficiálních dat (FRED)."],
        "sources": ["FRED – kalendář zveřejnění a historie hodnot (fred.stlouisfed.org)", "BEA (bea.gov)", "Fed (federalreserve.gov)"],
    }
