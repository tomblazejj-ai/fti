"""„Zdroje a čerstvost dat“ — for every input: where it comes from, what date
the data is for, how often it changes, and whether that is as fresh as it
can be. The trader must be able to see at a glance that nothing is stale.

Status: "ok" (as fresh as the source allows), "closed" (spot market shut —
old candles are correct), "late" (older than the source's rhythm), "missing".
"""

from __future__ import annotations

import datetime as dt

from app.news.timebasis import unknown_age_note

MACRO_LABELS = {
    "real_yield_10y": ("Reálné výnosy 10 let", "FRED DFII10", "denně (zpoždění 1 den)"),
    "usd_index": ("Dolar – široký index", "FRED DTWEXBGS", "týdně za každý den"),
    "fed_funds_target": ("Sazby Fedu", "FRED DFEDTARU", "po zasedání FOMC"),
    "core_cpi": ("Jádrová inflace CPI", "FRED CPILFESL (BLS)", "měsíčně"),
    "core_pce": ("Jádrová inflace PCE", "FRED PCEPILFE (BEA)", "měsíčně"),
    "nfp": ("Pracovní místa NFP", "FRED PAYEMS (BLS)", "měsíčně"),
    "unemployment": ("Nezaměstnanost", "FRED UNRATE (BLS)", "měsíčně"),
    "gdp": ("HDP", "FRED GDPC1 (BEA)", "čtvrtletně"),
}
# how old the data may be before it counts as late, by frequency
MAX_AGE_DAYS = {"D": 6, "W": 14, "M": 80, "Q": 230}
# series whose FRED "daily" data is itself published with a lag
MAX_AGE_OVERRIDE = {"usd_index": 14}


def _age_days(as_of: str | None, now: dt.datetime) -> float | None:
    if not as_of:
        return None
    try:
        t = dt.datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return (now - t).total_seconds() / 86400


def _row(key: str, label: str, provider: str, rhythm: str, as_of: str | None, status: str, note: str = "") -> dict:
    return {"key": key, "label": label, "provider": provider, "rhythm": rhythm, "as_of": as_of, "status": status, "note": note}


def build(payload: dict, macro: dict, now: dt.datetime, market_open: bool) -> list[dict]:
    rows: list[dict] = []
    m = payload.get("mtf") or {}

    # prices — the only truly live input
    price_time = m.get("price_time")
    age_min = (_age_days(price_time, now) or 0) * 1440
    gold = (payload.get("gold_data") or {})
    best = next((gold[tf] for tf in ("M15", "H1", "D1") if (gold.get(tf) or {}).get("bars")), None)
    if not price_time:
        st, note = "missing", "Pro XAUUSD teď není připojený žádný zdroj (MT5 nebo OANDA); PAXG se nepoužívá."
    elif not market_open:
        st, note = "closed", "Spotový trh je zavřený — poslední svíčka je z jeho uzavření, to je správně."
    else:
        st, note = ("ok", "") if age_min <= 30 else ("late", f"Poslední svíčka je stará {age_min:.0f} min.")
    if best and best.get("close_only"):
        note = (note + " " if note else "") + "Jen denní referenční cena (NBP), intradenní data XAUUSD nejsou připojena."
    rows.append(_row("price", "Cena XAUUSD a svíčky", (best or {}).get("source") or "není připojen zdroj XAUUSD",
                     "podle zdroje", price_time, st, note))

    rows.append(_row("tech", "Technika, trendy, úrovně, verdikt", "výpočet aplikace", "každých 5 minut", now.isoformat(), "ok",
                     "Denní svíčka končí o půlnoci UTC (OANDA/TradingView ve 23:00 našeho času) — hodnoty se mohou mírně lišit."))

    d = payload.get("dxy")
    if d:
        ecb_date = d.get("ecb_date")
        late = ecb_date is not None and (_age_days(ecb_date, now) or 0) > 5
        rows.append(_row("dxy", "Dolarový index DXY", "Kraken (EUR, GBP, CAD, CHF) + ECB (JPY, SEK)", "živě · fixing ECB denně",
                         (d.get("trends") or {}).get("price_time"), "late" if late else ("ok" if market_open else "closed"),
                         f"Fixing ECB k {ecb_date}." if ecb_date else ""))
    else:
        rows.append(_row("dxy", "Dolarový index DXY", "Kraken + ECB", "živě", None, "missing"))

    for key, (label, provider, rhythm) in MACRO_LABELS.items():
        p = macro.get(key)
        period = getattr(p, "period", None) if p else None
        freq = getattr(p, "frequency", "") if p else ""
        if not p or getattr(p, "actual", None) is None:
            rows.append(_row(f"macro:{key}", label, provider, rhythm, None, "missing", "Hodnotu se nepodařilo stáhnout."))
            continue
        age = _age_days(period, now)
        late = age is not None and age > MAX_AGE_OVERRIDE.get(key, MAX_AGE_DAYS.get(freq, 400))
        rows.append(_row(f"macro:{key}", label, provider, rhythm, period, "late" if late else "ok",
                         "Novější číslo zatím nevyšlo." if not late else "Zdroj je pozadu proti obvyklému rytmu."))

    cot = payload.get("cot")
    if cot:
        sched = cot.get("schedule") or {}
        rows.append(_row("cot", "COT – pozice fondů", "CFTC (podrobný report)", "týdně · v pátek 21:30 za úterý", cot.get("as_of"),
                         "late" if sched.get("late") else "ok",
                         "CFTC report zatím nevydala." if sched.get("late") else "Novější report ještě nevyšel."))
    else:
        rows.append(_row("cot", "COT – pozice fondů", "CFTC", "týdně", None, "missing"))

    cal = payload.get("calendar") or {}
    upcoming = [e for e in cal.get("events", []) if not e.get("past")]
    rows.append(_row("calendar", "Ekonomický kalendář", "FRED (termíny BLS, BEA, Census) + BEA + Fed", "termíny 2× denně",
                     now.isoformat() if upcoming else None, "ok" if upcoming else "missing",
                     f"{len(upcoming)} nadcházejících událostí." if upcoming else "Žádné termíny se nepodařilo načíst."))

    news = payload.get("news") or {}
    latest = (news.get("top") or [{}])[0].get("published_at")
    news_age_h = (_age_days(latest, now) or 99) * 24
    rows.append(_row("news", "Zprávy", "RSS: fxstreet.cz, FXStreet, Investing.com, CNBC, MarketWatch, Fed, ECB, BoE",
                     "portály každých 10 min, centrální banky 30 min",
                     latest, "ok" if latest and (news_age_h <= 12 or not market_open) else ("late" if latest else "missing"),
                     f"{news.get('count', 0)} zpráv o zlatě za {news.get('hours', 72)} h."
                     + (" " + unknown_age_note(news["unknown_age"]) if news.get("unknown_age") else "")))

    gv = payload.get("gold_vol")
    rows.append(_row("gvz", "Volatilita zlata (GVZ)", "FRED GVZCLS (CBOE)", "denně", gv.get("as_of") if gv else None,
                     "ok" if gv and (_age_days(gv.get("as_of"), now) or 99) <= 6 else ("late" if gv else "missing")))

    daily = payload.get("daily_markets") or []
    if daily:
        # oil (EIA via FRED) is published once a week — it may be up to ~10 days behind
        late = [q for q in daily if (_age_days(q["as_of"], now) or 99) > (10 if q["symbol"] == "oil" else 6)]
        oldest = min(q["as_of"] for q in daily)
        oil = next((q for q in daily if q["symbol"] == "oil"), None)
        rows.append(_row("markets", "Akcie, výnosy, VIX, ropa (pro korelace)", "FRED (S&P 500, US10Y, VIX, ropa WTI)",
                         "denně · ropa týdně", oldest, "late" if late else "ok",
                         (f"Zpožděné: {', '.join(q['label'] for q in late)}." if late else
                          f"Ropa WTI k {oil['as_of']} — EIA ji zveřejňuje jednou týdně." if oil else "")))
    rows.append(_row("corr", "Korelace zlata s dolarem a EUR/USD", "ECB (denní kurzy) + XAUUSD", "denně",
                     (payload.get("dxy") or {}).get("ecb_date"), "ok" if (payload.get("dxy") or {}).get("ecb_date") else "missing"))

    s = payload.get("seasonality")
    rows.append(_row("season", "Sezónnost", "XAUUSD týdenní", "týdně", f"{s['years_from']}–{s['years_to']}" if s else None,
                     "ok" if s else "missing", ""))

    # --- fundamental score and the extra data sets (2026-10)
    tra = payload.get("tra") or {}
    xau = tra.get("xau") or {}
    rows.append(_row("tra", "Fundamentální skóre (11 kategorií)", "FRED, CFTC, Světová banka, XAUUSD — výpočet aplikace",
                     "každých 5 minut · makro data měsíčně", tra.get("as_of"), "ok" if xau and not xau.get("missing") else
                     "late" if xau else "missing",
                     f"Bez dat: {', '.join(xau['missing'])}." if xau.get("missing") else ""))
    cu = payload.get("cot_usd")
    rows.append(_row("cot_usd", "COT – dolar (hedgeové fondy)", "CFTC Traders in Financial Futures", "týdně · v pátek 21:30 za úterý",
                     (cu or {}).get("as_of"), ("late" if cu["schedule"]["late"] else "ok") if cu else "missing"))
    sl = (payload.get("seasonality_long") or {}).get("gold")
    rows.append(_row("season_long", "Sezónnost 5/10/15 let", "Světová banka — měsíční ceny zlata (Pink Sheet)", "měsíčně",
                     (sl or {}).get("updated"), "ok" if sl else "missing"))
    sd = (payload.get("season_daily") or {}).get("gold")
    rows.append(_row("season_daily", "Sezónní okna (denní zlato)", "Narodowy Bank Polski — denní cena zlata od 2013", "denně",
                     (sd or {}).get("last_date"), "ok" if sd else "missing",
                     "Přepočet z PLN/g kurzem USD/PLN téhož dne." if sd else ""))
    return rows
