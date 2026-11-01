"""The analysis cycle for XAUUSD (spot gold) and the market overview.

Gold price: ONLY XAUUSD's own feeds (app/data/bars.py, app/data/universe.py) — the user's
broker terminal (MT5) or OANDA when the user connects one, else the NBP daily reference price
for daily/weekly analysis. PAXG (a token on Kraken) is a separate instrument and is never used
for XAUUSD (user's spec 2026-11-01); the FRED gold futures index is not used as a fallback either.
Gold volatility: FRED `GVZCLS` (CBOE Gold ETF Volatility Index).
Stooq (daily XAUUSD CSV) was rejected: robots.txt disallows all bots — see docs/DECISIONS.md.
"""

from __future__ import annotations

import datetime as dt
import logging
import statistics

from app.connectors import calendar_ics, cot, ecb, ffcal, fred, fred_calendar, intl_macro, kraken, nbp, worldbank
from app.connectors.cot import CotUnavailableError
from app.connectors.fred import FredUnavailableError
from app.market import (central_banks, decision, dxy, econ_calendar, fx_model, headline_risk, market_status, markets, mtf,
                        scorecard, seasonality, sources, tra)
from app.market.cot_analysis import analyze as analyze_cot, analyze_usd, long_short_view
from app.market.technical import MIN_HISTORY, InsufficientPriceHistory, analyze
from app.scoring.xauusd import FOMC_DECISION_DATES_2026
from app.verdict import build_verdict

logger = logging.getLogger(__name__)

GOLD_SERIES = "NASDAQQGLDI"
GOLD_VOL_SERIES = "GVZCLS"
SOURCES = {
    "gold": "XAUUSD jen z vlastních zdrojů: terminál MT5 nebo OANDA (po připojení), jinak denní referenční cena NBP; PAXG se pro XAUUSD nepoužívá",
    "calendar": "Oficiální kalendáře zveřejnění: BEA (HDP, PCE), BLS (CPI, NFP, PPI, JOLTS), Fed (FOMC)",
    "gold_vol": "FRED GVZCLS — CBOE Gold ETF Volatility Index",
    "drivers": "Dolar (DXY) a EUR/USD z denních kurzů ECB; FRED: DFII10, DGS10, SP500, DCOILWTICO, VIXCLS, CBBTCUSD",
    "cot": "CFTC Commitments of Traders — Legacy Futures Only, zlato COMEX (týdně)",
    "news": "RSS: fxstreet.cz, FXStreet, Investing.com, CNBC, MarketWatch, Fed/ECB/BoE, GDELT",
}


def _dxy_section(gold_candles: dict, now: dt.datetime, warnings: list[str]) -> tuple[dict | None, dict]:
    """DXY rebuilt from its ICE formula + its link to gold. Never fatal for the cycle.
    Returns (analysis, DXY candles by timeframe)."""
    try:
        fixings = dxy._JpySek(ecb.fetch_history(now))
    except ecb.EcbUnavailableError as exc:
        warnings.append(f"DXY nelze spočítat: {exc}")
        return None, {}
    dxy_candles, errors = dxy.fetch_candles(fixings, kraken.TIMEFRAMES)
    warnings += errors
    try:
        live = dxy.live_quote(kraken.fetch_last(kraken.DXY_PAIRS), fixings, now.date().isoformat())
    except kraken.KrakenUnavailableError:
        live = None
    return dxy.analyze(gold_candles, dxy_candles, live, ecb_date=fixings.days[-1] if fixings.days else None), dxy_candles


DAILY_TICKERS = [("spx", "S&P 500", 2), ("yield10", "US 10Y výnos", 2),
                 ("vix", "VIX", 2), ("oil", "Ropa WTI", 2)]


def _daily_markets(drivers: dict[str, dict[str, float]]) -> list[dict]:
    """Daily FRED closes for the ticker strip (marked with their date — they are not live)."""
    out = []
    for key, label, digits in DAILY_TICKERS:
        series = drivers.get(key) or {}
        dates = sorted(series)
        if len(dates) < 2:
            continue
        last, prev = series[dates[-1]], series[dates[-2]]
        out.append({"symbol": key, "label": label, "price": round(last, digits), "digits": digits,
                    "change_pct": round((last / prev - 1) * 100, 2) if prev else None,
                    "source": "FRED", "live": False, "as_of": dates[-1]})
    return out


# Slow inputs change at most daily/weekly; the 5-minute market refresh reuses them.
_slow: dict[str, tuple[float, object]] = {}
SLOW_TTL = {"fred": 3600.0, "cot": 3600.0, "bea": 6 * 3600.0, "macro": 3 * 3600.0, "worldbank": 12 * 3600.0}
FAIL_RETRY_SECONDS = 900.0  # a source that just failed is not asked again on every 5-minute refresh
_failed: dict[str, float] = {}
TRA_HISTORY_DAYS = 1300  # y/y three months back for a whole year of score history
CAL_HISTORY_DAYS = 2000  # the Fed rate history in the FOMC detail goes back several changes
# The last inputs of the fundamental score — the ingestion uses them to rebuild the score history.
LAST_TRA: dict[str, object] = {"inputs": None}


def _slow_cached(key: str, kind: str, fn):
    import time

    hit = _slow.get(key)
    if hit and time.monotonic() - hit[0] < SLOW_TTL[kind]:
        return hit[1]
    value = fn()
    _slow[key] = (time.monotonic(), value)
    return value


def _soft(key: str, kind: str, fn, warnings: list[str], label: str):
    """A slow input that may be missing: None + a warning instead of an exception."""
    import time

    failed_at = _failed.get(key)
    if failed_at and time.monotonic() - failed_at < FAIL_RETRY_SECONDS:
        return None
    from app.data import health, store

    source_key = "src:" + key.split(":")[0]
    t0 = time.monotonic()
    try:
        value = _slow_cached(key, kind, fn)
    except (FredUnavailableError, CotUnavailableError, worldbank.WorldBankUnavailableError, ecb.EcbUnavailableError,
            nbp.NbpUnavailableError, intl_macro.MacroUnavailableError, ffcal.CalendarFeedUnavailableError,
            kraken.KrakenUnavailableError) as exc:
        _failed[key] = time.monotonic()
        health.record(source_key, SOURCE_NAMES.get(source_key, label), ok=False, error=f"{label}: {exc}")
        # The last good answer, shown with its real date — never as if it were current.
        last, fetched_at = store.cache_get(key)
        if last is not None and fetched_at is not None:
            warnings.append(f"{label} nedostupné ({exc}) — používám poslední data stažená {fetched_at:%d. %m. %Y %H:%M} UTC.")
            STALE_INPUTS[key] = {"label": label, "fetched_at": fetched_at.isoformat(), "error": str(exc)[:300]}
            return last
        warnings.append(f"{label} nedostupné: {exc}")
        return None
    _failed.pop(key, None)
    STALE_INPUTS.pop(key, None)
    health.record(source_key, SOURCE_NAMES.get(source_key, label), ok=True, ms=(time.monotonic() - t0) * 1000,
                  records=len(value) if hasattr(value, "__len__") else None)
    if isinstance(value, (dict, list)) and _slow.get(key, (0, None))[0] >= t0:  # freshly fetched, not from memory
        try:
            import json

            json.dumps(value)
            store.cache_put(key, value, label)
        except (TypeError, ValueError):
            pass
    return value


SOURCE_NAMES = {
    "src:macro": "FRED (makro řady)", "src:cot": "CFTC COT", "src:ecb": "ECB Data Portal", "src:eurostat": "Eurostat",
    "src:ons": "ONS (Británie)", "src:mof": "Ministerstvo financí Japonska", "src:eia": "EIA", "src:worldbank": "Světová banka",
    "src:nbp": "NBP", "src:ffcal": "ForexFactory kalendář", "src:fred": "FRED", "src:bea": "BEA kalendář",
}
# inputs currently served from the last good copy because their source failed (key -> info)
STALE_INPUTS: dict[str, dict] = {}


def _series(fred_id: str) -> dict[str, float]:
    return _slow_cached(f"fred:{fred_id}", "fred", lambda: {o["date"]: o["value"] for o in fred.fetch_observations(fred_id)})


def _macro_series(ids: list[str], days: int, warnings: list[str]) -> dict[str, dict[str, float]]:
    out = {}
    for sid in ids:
        series = _soft(f"macro:{sid}:{days}", "macro",
                       lambda sid=sid: {o["date"]: o["value"] for o in fred.fetch_observations(sid, history_days=days)},
                       warnings, f"Řada FRED {sid}")
        if series:
            out[sid] = series
    return out


GOLD_TFS = ("M15", "H1", "H4", "D1", "W1")


def gold_bars(now: dt.datetime, warnings: list[str]) -> tuple[dict[str, list], dict[str, dict]]:
    """XAUUSD candles of every timeframe from XAUUSD's own feeds, plus where each came from.
    A timeframe without an XAUUSD feed is left out (reported), never filled with PAXG."""
    from app.data import bars as bars_mod

    candles: dict[str, list] = {}
    info: dict[str, dict] = {}
    for tf in GOLD_TFS:
        bs = bars_mod.get_bars("XAUUSD", tf, now=now)
        d = bs.describe()
        info[tf] = {k: d[k] for k in ("provider", "source", "kind", "kind_cs", "proxy", "close_only", "quality", "notes", "bars", "tried")}
        if bs.ok:
            candles[tf] = bars_mod.to_candles(bs)
        else:
            warnings.append(f"XAUUSD {tf}: " + (bs.notes[0] if bs.notes else "bez dat"))
    return candles, info


def _closes(candles: list) -> list[tuple[str, float]]:
    return [(c.time.date().isoformat(), c.close) for c in candles]


def _tra_section(gold_rows: list[dict], candles: dict, dxy_candles: dict, ecb_rates: dict | None, now: dt.datetime,
                 warnings: list[str]) -> tuple[dict | None, dict | None, dict | None]:
    """The 11-category fundamental score for XAU/USD and the USD, plus the long seasonality
    and the dollar COT. Returns (tra, seasonality_long, cot_usd)."""
    fred_hist = _macro_series(tra.TRA_FRED_IDS, TRA_HISTORY_DAYS, warnings)
    usd_rows = _soft("cot:tff_usd", "cot", cot.fetch_usd_index_tff, warnings, "COT dolaru (CFTC TFF)") or []
    wb = _soft("worldbank:gold", "worldbank", lambda: worldbank.fetch_gold_monthly(now), warnings,
               "Měsíční ceny zlata (Světová banka)")
    usd_daily = dict(dxy.daily_from_ecb(ecb_rates)) if ecb_rates else {}
    inputs = tra.TraInputs(
        fred=fred_hist, gold_cot=gold_rows, usd_cot=usd_rows, gold_monthly=(wb or {}).get("prices", {}), usd_daily=usd_daily,
        gold_d1=candles.get("D1", []), gold_w1=candles.get("W1", []),
        dxy_d1=dxy_candles.get("D1", []), dxy_w1=dxy_candles.get("W1", []),
    )
    LAST_TRA["inputs"] = inputs
    score = tra.compute(inputs, now, live=True)
    score["proxies_note"] = ("Kde by bylo potřeba placených dat (ISM PMI, sentiment brokerů, pravděpodobnosti sazeb), "
                             "počítáme s oficiálními veřejnými daty — u položky je to vždy napsané.")

    long_season = {}
    if wb:
        long_season["gold"] = seasonality.analyze_long(wb["prices"], now, updated=wb.get("updated"))
    if usd_daily:
        long_season["usd"] = seasonality.analyze_long(
            tra.daily_monthly_avg(usd_daily), now, label="Dolar (DXY)",
            source="DXY přepočtený z denních kurzů ECB od roku 1999 (měsíční průměry)")
    cot_usd = None
    if usd_rows:
        cot_usd = analyze_usd(usd_rows, _closes(dxy_candles.get("D1", [])) or sorted(usd_daily.items()), now)
        if cot_usd:
            cot_usd["retail"] = long_short_view(usd_rows, "small_long", "small_short", asset="usd", who="Malí obchodníci")
    return score, ({k: v for k, v in long_season.items() if v} or None), cot_usd


def compute_market_analysis(fundamental: dict, next_fomc: str | None, news: dict | None = None,
                            macro: dict | None = None, now: dt.datetime | None = None) -> tuple[dict, list[str]]:
    """Returns (payload, warnings). Never raises for a data problem — a
    missing piece is reported as unavailable, never filled in."""
    warnings: list[str] = []
    now = now or dt.datetime.now(dt.timezone.utc)

    cot_result = None
    gold_rows: list[dict] = []
    try:
        gold_rows = _slow_cached("cot:dis", "cot", cot.fetch_gold_disaggregated)
        cot_result = analyze_cot(gold_rows, now=now, source="disaggregated")
    except CotUnavailableError as exc:
        warnings.append(f"Podrobný COT nedostupný, použit základní report: {exc}")
        try:
            gold_rows = _slow_cached("cot:legacy", "cot", cot.fetch_gold_history)
            cot_result = analyze_cot(gold_rows, now=now)
        except CotUnavailableError as exc2:
            warnings.append(f"COT historie nedostupná: {exc2}")

    candles, gold_data = gold_bars(now, warnings)
    multi_tf = mtf.analyze_all(candles) if candles else None

    technical = None
    daily = candles.get("D1", [])
    if len(daily) >= MIN_HISTORY:
        try:
            technical = analyze([c.time.date().isoformat() for c in daily], [c.close for c in daily], unit="USD")
        except InsufficientPriceHistory as exc:
            warnings.append(f"Trend zlata nelze spočítat: {exc}")
    else:
        warnings.append("Technika XAUUSD: málo denních dat XAUUSD — nepočítá se (jiný instrument se nedosazuje).")

    ics_events, cal_notes = _slow_cached("bea", "bea", calendar_ics.fetch_all)
    ics_events, cal_notes = list(ics_events), list(cal_notes)
    try:
        fred_events, fred_notes = fred_calendar.fetch(now)
        ics_events += fred_events
        cal_notes += fred_notes
    except calendar_ics.CalendarUnavailableError as exc:
        cal_notes.append(f"Termíny CPI, NFP, PPI a dalších dat USA se teď nepodařilo stáhnout z FRED: {exc}")
    hist_ids = econ_calendar.HISTORY_SERIES
    cal_series = _macro_series([sid for sid in hist_ids if sid in tra.FRED_SPECS], TRA_HISTORY_DAYS, warnings)
    cal_series |= _macro_series([sid for sid in hist_ids if sid not in tra.FRED_SPECS], CAL_HISTORY_DAYS, warnings)
    calendar = econ_calendar.build(ics_events, FOMC_DECISION_DATES_2026, macro or {}, now, cal_notes, cal_series)

    # Correlations were removed on 2026-10-31 (the user wants a simpler platform); the ECB
    # fixings stay — they feed the dollar index, seasonality and the yen.
    correlations = None
    drivers: dict[str, dict[str, float]] = {}
    try:
        ecb_rates = ecb.fetch_history(now)
    except ecb.EcbUnavailableError as exc:
        ecb_rates = None
        warnings.append(f"Kurzy ECB nedostupné: {exc}")

    gold_vol = None
    try:
        gvz = _series(GOLD_VOL_SERIES)
        values = [gvz[d] for d in sorted(gvz)][-252:]
        if len(values) >= 60:
            q75 = statistics.quantiles(values, n=4)[2]
            gold_vol = {
                "last": round(values[-1], 2),
                "median": round(statistics.median(values), 2),
                "p75": round(q75, 2),
                "elevated": values[-1] > q75,
                "as_of": sorted(gvz)[-1],
            }
    except FredUnavailableError as exc:
        warnings.append(f"Volatilita zlata ({GOLD_VOL_SERIES}) nedostupná: {exc}")

    verdict = build_verdict(fundamental, technical, correlations, gold_vol, next_fomc, cot=cot_result, news=news)
    season = seasonality.analyze(candles.get("W1", []), now, source=(gold_data.get("W1") or {}).get("source") or "XAUUSD")
    dollar, dxy_candles = _dxy_section(candles, now, warnings)
    market = market_status.status(now)

    # --- fundamental score, long seasonality and the dollar COT (each part optional, never breaks the rest)
    tra_score = season_long = cot_usd = None
    try:
        tra_score, season_long, cot_usd = _tra_section(gold_rows, candles, dxy_candles, ecb_rates, now, warnings)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Fundamental score failed")
        warnings.append(f"Fundamentální skóre se nepodařilo spočítat: {exc}")
    if cot_result and gold_rows:
        cot_result["long_short"] = long_short_view(gold_rows, "spec_long", "spec_short", _closes(daily), asset="gold", who="Fondy")
        cot_result["retail"] = long_short_view(gold_rows, "small_long", "small_short", asset="gold", who="Malí obchodníci")
    if dollar:
        dxy_d1 = dxy_candles.get("D1", [])
        dxy_tech = None
        if len(dxy_d1) >= MIN_HISTORY:
            try:
                dxy_tech = analyze([c.time.date().isoformat() for c in dxy_d1], [c.close for c in dxy_d1], unit="DXY")
            except InsufficientPriceHistory:
                dxy_tech = None
        corr60 = ((dollar.get("correlation") or {}).get("d60") or {}).get("value")
        dollar["key_levels"] = dxy.levels_view(dxy_tech, dollar.get("trends"))
        dollar["mirror"] = dxy.mirror(technical if technical and technical.get("unit") == "USD" else None, dxy_tech, corr60)
        dollar["weights"] = dxy.WEIGHTS
        dollar["usd_score"] = (tra_score or {}).get("usd")
    headline = headline_risk.build((news or {}).get("headline") or [], candles.get("M15", []), market, now)

    # daily seasonal windows (data only — gold from NBP, the dollar from ECB fixings)
    season_daily: dict = {}
    try:
        gold_daily = _soft("nbp:gold", "worldbank", lambda: nbp.fetch_gold_usd(now), warnings, "Denní cena zlata (NBP)")
        if gold_daily:
            season_daily["gold"] = seasonality.daily_view(
                gold_daily, now, "gold", "Zlato", source="Narodowy Bank Polski — denní cena zlata od 2013 (přepočet na USD kurzem NBP)")
        if ecb_rates:
            season_daily["usd"] = seasonality.daily_view(
                dict(dxy.daily_from_ecb(ecb_rates)), now, "usd", "Dolar (DXY)", source="DXY přepočtený z denních kurzů ECB od 1999")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Seasonality failed")
        warnings.append(f"Sezónnost se nepodařilo spočítat: {exc}")
    market_view = None
    events_all: list[dict] = []
    try:
        events_all = _all_events(calendar, now, warnings)
        market_view = _markets_section(tra_score, gold_rows, ecb_rates, dollar, news, events_all, season_daily, candles, now, warnings,
                                       gold_data)
    except Exception as exc:  # noqa: BLE001 — the overview of other markets must never cost us gold
        logger.exception("Markets overview failed")
        warnings.append(f"Přehled trhů se nepodařilo sestavit: {exc}")
    dec = decision.build(verdict, technical, multi_tf, calendar, cot_result, fundamental.get("pillar_breakdown"), now, dollar)
    payload = {
        "technical": technical,
        "correlations": correlations,
        "gold_vol": gold_vol,
        "cot": cot_result,
        "mtf": multi_tf,
        "calendar": calendar,
        "decision": dec,
        "seasonality": season,
        "dxy": dollar,
        "scorecard": scorecard.build_scorecard(fundamental.get("pillar_breakdown"), verdict, technical, multi_tf,
                                               cot_result, news, season, dollar),
        "summary": scorecard.build_summary(verdict, technical, multi_tf, calendar, cot_result, dec, now, dollar),
        "daily_markets": _daily_markets(drivers),
        "news": {k: v for k, v in news.items() if k != "headline"} if news else news,
        "verdict": verdict,
        "sources": SOURCES,
        "tra": tra_score,
        "seasonality_long": season_long,
        "cot_usd": cot_usd,
        "headline_risk": headline,
        "season_daily": season_daily or None,
        "markets": market_view,
        "calendar_all": _calendar_payload(events_all, now),
        "gold_data": gold_data,
    }
    payload["market"] = market
    payload["sources_status"] = sources.build(payload, macro or {}, now, market["open"])
    return payload, warnings


# --- Market overview for all instruments (2026-10-31) ------------------------------------------

_titles_cs: dict[str, str] = {}


def _title_cs(title: str) -> str:
    """Czech name of a calendar event: fixed names first, then the local translator, else English."""
    if title in _titles_cs:
        return _titles_cs[title]
    # machine translation of three-word release names reads badly ("Non- Manufacturing SZP"),
    # so names outside the dictionary stay in English — traders know them that way
    _titles_cs[title] = ffcal.czech_title(title) or title
    return _titles_cs[title]


def _all_events(us_calendar: dict | None, now: dt.datetime, warnings: list[str]) -> list[dict]:
    """ForexFactory this week (all currencies, with consensus) + rate decisions of the four central
    banks + the official US release calendar for the weeks the FF file does not cover yet."""
    ff = _soft("ffcal", "fred", lambda: ffcal.fetch_week(now), warnings, "Kalendář ForexFactory") or []
    events = []
    for e in ff:
        events.append({**e, "title_cs": _title_cs(e["title_en"]), "timed": True})
    ff_end = max((e["datetime"] for e in ff), default=now.isoformat())[:10]
    for e in central_banks.upcoming({"USD", "EUR", "GBP", "JPY"}, now, days=60):
        if e["datetime"][:10] > ff_end:
            events.append(e)
    for e in (us_calendar or {}).get("events", []):
        when = e.get("datetime") or f"{e['date']}T12:00:00+00:00"
        if e["date"] > ff_end and e.get("key") != "fomc":
            events.append({"datetime": when, "timed": bool(e.get("datetime")), "currency": "USD", "title_cs": e["name"],
                           "title_en": e.get("original") or e["name"], "impact": e["importance"], "forecast": None,
                           "previous": e.get("previous"), "source": e.get("source")})
    events.sort(key=lambda e: e["datetime"])
    return events


def _calendar_payload(events: list[dict], now: dt.datetime) -> dict:
    lo, hi = (now - dt.timedelta(days=2)).isoformat(), (now + dt.timedelta(days=21)).isoformat()
    shown = [e for e in events if lo <= e["datetime"] <= hi and e["currency"] in ("USD", "EUR", "GBP", "JPY")]
    return {"events": shown, "timezone": "Europe/Prague",
            "sources": ["ForexFactory (export kalendáře na tento týden, s prognózami)", "Fed, ECB, BoE, BoJ (oficiální termíny zasedání)",
                        "FRED a BEA (termíny dat USA)"]}


def _yoy_index(series: dict[str, float] | None) -> dict[str, float]:
    if not series:
        return {}
    out = {}
    for d, v in series.items():
        prev = series.get(f"{int(d[:4]) - 1:04d}{d[4:]}")
        if prev:
            out[d] = (v / prev - 1) * 100
    return out


def _qoq_level(series: dict[str, float] | None) -> dict[str, float]:
    if not series:
        return {}
    days = sorted(series)
    return {b: (series[b] / series[a] - 1) * 100 for a, b in zip(days, days[1:]) if series[a]}


def _currency_data(warnings: list[str]) -> dict[str, fx_model.CurrencyData]:
    tra_fred = _macro_series(tra.TRA_FRED_IDS, TRA_HISTORY_DAYS, warnings)
    intl = _macro_series(["CLVMNACSCAB1GQEA19", "ECBDFR", "IUDSOIA", "LRUN64TTJPM156S", "JPNRGDPEXP", "IRSTCI01JPM156N"],
                         TRA_HISTORY_DAYS, warnings)

    def ecb(name, flow_key, start="2018-01"):
        return _soft(f"ecb:{flow_key[1]}", "macro", lambda: intl_macro.ecb_series(*flow_key, start=start), warnings, name) or {}

    def eurostat(name, coicop):
        return _soft(f"eurostat:{coicop}", "macro", lambda: intl_macro.eurostat_hicp(coicop), warnings, name) or {}

    def ons(name, path):
        return _soft(f"ons:{path}", "macro", lambda: intl_macro.ons_series(path), warnings, name) or {}

    return {
        "USD": fx_model.CurrencyData("USD", cpi=_yoy_index(tra_fred.get("CPIAUCSL")), core=_yoy_index(tra_fred.get("CPILFESL")),
                                     unemp=tra_fred.get("UNRATE", {}), gdp_qoq=_qoq_level(tra_fred.get("GDPC1")),
                                     rate2y=tra_fred.get("DGS2", {}), policy=tra_fred.get("DFF", {})),
        "EUR": fx_model.CurrencyData("EUR", cpi={**ecb("Inflace eurozóny (ECB)", intl_macro.ECB_HICP),
                                                 **eurostat("Inflace eurozóny (Eurostat)", intl_macro.EUROSTAT_HICP_TOTAL)},
                                     core={**ecb("Jádrová inflace eurozóny (ECB)", intl_macro.ECB_CORE),
                                           **eurostat("Jádrová inflace eurozóny (Eurostat)", intl_macro.EUROSTAT_HICP_CORE)},
                                     unemp=ecb("Nezaměstnanost eurozóny (ECB)", intl_macro.ECB_UNEMP),
                                     gdp_qoq=_qoq_level(intl.get("CLVMNACSCAB1GQEA19")),
                                     rate2y=ecb("2letý výnos eurozóny (ECB)", intl_macro.ECB_2Y, start="2024-01-01"),
                                     policy=intl.get("ECBDFR", {})),
        "GBP": fx_model.CurrencyData("GBP", cpi=ons("Inflace Británie (ONS)", intl_macro.ONS_CPI),
                                     core=ons("Jádrová inflace Británie (ONS)", intl_macro.ONS_CORE),
                                     unemp=ons("Nezaměstnanost Británie (ONS)", intl_macro.ONS_UNEMP),
                                     gdp_qoq=ons("HDP Británie (ONS)", intl_macro.ONS_GDP),
                                     rate2y={}, policy=intl.get("IUDSOIA", {})),
        "JPY": fx_model.CurrencyData("JPY", unemp=intl.get("LRUN64TTJPM156S", {}), gdp_qoq=_qoq_level(intl.get("JPNRGDPEXP")),
                                     rate2y=_soft("mof:jgb2y", "macro", intl_macro.mof_jgb_2y, warnings, "2letý výnos Japonska (MOF)") or {},
                                     policy=intl.get("IRSTCI01JPM156N", {})),
    }


_fx_cache: dict[str, tuple[float, object]] = {}
FX_CANDLE_TTL = 900.0


def _fx_trend(code: str, warnings: list[str]) -> tuple[str | None, dict | None]:
    """Swing trend (D1 + W1) and the current price of one instrument from ITS OWN feeds
    (app/data/bars.py), cached 15 minutes. The price carries its source and data-quality label."""
    import time

    from app.data import bars as bars_mod

    hit = _fx_cache.get(code)
    if hit and time.monotonic() - hit[0] < FX_CANDLE_TTL:
        return hit[1]  # type: ignore[return-value]
    d1s, w1s = bars_mod.get_bars(code, "D1"), bars_mod.get_bars(code, "W1")
    if not d1s.ok:
        warnings.append(f"Ceny {code} nedostupné: {' '.join(d1s.notes)[:300]}")
        return None, None
    clean = dxy.clean_wicks if d1s.provider == "kraken" else (lambda c: c)
    d1, w1 = clean(bars_mod.to_candles(d1s)), clean(bars_mod.to_candles(w1s)) if w1s.ok else []
    view = mtf.analyze_all({"D1": d1, "W1": w1}, unit="")
    swing = view.get("swing") or {}
    now_bs = bars_mod.get_bars(code, "H1")  # the freshest price this instrument has (broker, or a labelled proxy)
    cur = now_bs if now_bs.ok else d1s
    last = cur.bars[-1][4]
    prev = d1s.bars[-2][4] if len(d1s.bars) > 1 else None
    if cur is now_bs and d1s.provider != now_bs.provider:
        prev = None  # never compare prices of two different feeds
    price = {"value": last, "change_pct": round((last / prev - 1) * 100, 2) if prev else None,
             "as_of": cur.quality.get("as_of"), "live": cur.quality.get("status") == "LIVE", "source": cur.source,
             "quality": cur.quality, "proxy": cur.proxy, "kind": cur.kind}
    out = (swing.get("word"), price)
    _fx_cache[code] = (time.monotonic(), out)
    return out


def _daily_trend(closes: dict[str, float]) -> str | None:
    days = sorted(closes)
    if len(days) < MIN_HISTORY:
        return None
    try:
        t = analyze(days, [closes[d] for d in days])
    except InsufficientPriceHistory:
        return None
    return {"up": "Nahoru", "down": "Dolů"}.get(t["trend"], "Do strany")


def _markets_section(tra_score, gold_rows, ecb_rates, dollar, news, events, season_daily, candles, now, warnings,
                     gold_data: dict | None = None) -> dict:
    currencies = _currency_data(warnings)
    tff = {cur: _soft(f"cot:tff:{cur}", "cot", lambda m=m: cot.fetch_tff(m), warnings, f"COT {cur}") or []
           for cur, m in cot.TFF_MARKETS.items() if cur != "USD"}
    crude = _soft("cot:crude", "cot", cot.fetch_crude_disaggregated, warnings, "COT ropy") or []
    stocks = _soft("eia:crude", "macro", intl_macro.eia_weekly, warnings, "Zásoby ropy (EIA)")
    wti = _macro_series(["DCOILWTICO"], 4500, warnings).get("DCOILWTICO", {})
    cfnai = _macro_series(["CFNAI"], TRA_HISTORY_DAYS, warnings).get("CFNAI")

    seasons = {"XAUUSD": season_daily.get("gold")}
    if ecb_rates:
        eurusd = {d: r["USD"] for d, r in ecb_rates.items() if r.get("USD")}
        gbpusd = {d: r["USD"] / r["GBP"] for d, r in ecb_rates.items() if r.get("USD") and r.get("GBP")}
        usdjpy = {d: r["JPY"] / r["USD"] for d, r in ecb_rates.items() if r.get("USD") and r.get("JPY")}
        seasons["EURUSD"] = seasonality.daily_view(eurusd, now, "usd", "EUR/USD", source="ECB denní kurzy od 1999")
        seasons["GBPUSD"] = seasonality.daily_view(gbpusd, now, "usd", "GBP/USD", source="ECB denní kurzy od 1999")
        seasons["USDJPY"] = seasonality.daily_view(usdjpy, now, "usd", "USD/JPY", source="ECB denní kurzy od 1999")
    else:
        usdjpy = {}
    if wti:
        seasons["USOIL"] = seasonality.daily_view(wti, now, "gold", "Ropa WTI", source="FRED DCOILWTICO (EIA) od 1986")

    prices, trends = {}, {}
    for code in ("EURUSD", "GBPUSD", "USDJPY", "USOIL"):
        trends[code], prices[code] = _fx_trend(code, warnings)
    gold_d1 = candles.get("D1", [])
    if gold_d1:
        prev = gold_d1[-2].close if len(gold_d1) > 1 else None
        fine = next((tf for tf in ("M15", "H1") if candles.get(tf)), None)
        info = (gold_data or {}).get(fine or "D1") or {}
        last = candles[fine][-1].close if fine else gold_d1[-1].close
        q = info.get("quality") or {}
        prices["XAUUSD"] = {"value": last, "change_pct": round((last / prev - 1) * 100, 2) if prev else None,
                            "as_of": q.get("as_of") or gold_d1[-1].time.isoformat(), "live": q.get("status") == "LIVE",
                            "source": info.get("source") or "XAUUSD", "quality": q}
    swing = (mtf.analyze_all({"D1": gold_d1, "W1": candles.get("W1", [])}, unit="$").get("swing") or {}) if gold_d1 else {}
    trends["XAUUSD"] = swing.get("word")

    ctx = {"currencies": currencies, "tff": tff, "crude_cot": crude, "gold_cot": gold_rows, "seasons": seasons, "tra": tra_score,
           "stocks": stocks, "cfnai": cfnai, "dxy_swing": ((dollar or {}).get("trends") or {}).get("swing"),
           "headlines": (news or {}).get("headline") or [], "key_news": (news or {}).get("key") or [], "events": events,
           "prices": prices, "trends": trends}
    view = markets.build(ctx, now)
    for e in view.get("errors", []):
        warnings.append(f"Přehled trhů — {e}")
    return view
