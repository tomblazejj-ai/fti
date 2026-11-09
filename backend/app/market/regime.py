"""Market Regime Detection for gold (Ú2, 9. 11. 2026) — what kind of market it is now, from data FTI already has.

Deterministic, no AI and nothing fetched here: the same inputs always give the same regime, so the historical test
(Ú6) can recompute it for any past day from the data known then. Every dimension names its inputs with source and
time. The regime is CONTEXT, not a vote: it does not change the rule verdict until a historical test shows it helps.

  trend       D1 ADX(14) and direction (EMA20/50 and close, mtf.py), H4 as confirmation → trend / weak trend / range
  volatilita  ATR(14) D1 in % of the price as a percentile of the last 250 closed trading days, GVZ, realised volatility
  riziko      VIX level and 5-day change, S&P 500 20-day change; whether gold moves with stocks now (60-day r)
  dolar       DXY direction on D1 and W1
  sazby       10-year real yield (TIPS) and nominal yield over 20 days
  korelace    Intermarket Intelligence D1: stable and broken relationships (with its own computation time)

Thresholds are the textbook ones and are written here, not tuned: ADX 20 / 25 (Wilder), VIX 15 / 20 / 30, ATR
percentile 20 / 80 / 95, a real-yield move of 0.15 p. b. in 20 days.
"""

from __future__ import annotations

import datetime as dt

from app.data import market_hours

ADX_TREND, ADX_WEAK = 25.0, 20.0
ATR_N, ATR_WINDOW, ATR_MIN = 14, 250, 120
ATR_CLASSES = ((20, "low", "nízká"), (80, "normal", "běžná"), (95, "high", "zvýšená"), (101, "extreme", "extrémní"))
VIX_CLASSES = ((15, "klid"), (20, "běžná"), (30, "zvýšená nervozita"), (1e9, "stres"))
RATE_STEP = 0.15
CORR_LINK = 0.3  # |r| from which gold and another market are said to move together / against each other
NOTE = ("Režim trhu je kontext, ne hlas ve verdiktu: říká, jaký typ obchodu dává teď smysl. Do pravidlového verdiktu "
        "nevstupuje, dokud historický test neukáže, že pomáhá.")


def _num(v, digits: int = 2) -> str:
    return "—" if v is None else f"{v:,.{digits}f}".replace(",", " ").replace(".", ",")


def _signed(v, digits: int = 2) -> str:
    return "—" if v is None else ("+" if v > 0 else "−" if v < 0 else "") + _num(abs(v), digits)


def atr_series(candles: list, n: int = ATR_N) -> list[float]:
    """Wilder's ATR after every bar from the (n+1)-th on — the same method as mtf.atr, so the last value is the ATR
    the trend tables show."""
    if len(candles) <= n:
        return []
    trs = [max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)) for p, c in zip(candles, candles[1:])]
    a = sum(trs[:n]) / n
    out = [a]
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
        out.append(a)
    return out


def _tf(mtf: dict | None, tf: str) -> dict:
    return next((t for t in (mtf or {}).get("timeframes", []) if t.get("tf") == tf), {})


def _item(intermarket: dict | None, sid: str) -> dict:
    return next((i for i in (intermarket or {}).get("items", []) if i.get("id") == sid), {})


def _dim(key, label, state, word, detail, implication, inputs, available=True) -> dict:
    return {"key": key, "label": label, "state": state, "word": word, "detail": detail, "implication": implication,
            "inputs": [i for i in inputs if i], "available": available}


def _missing(key, label, why) -> dict:
    return _dim(key, label, "unknown", "nelze určit", why, None, [], available=False)


def _inp(name, value, source, as_of, unit=None) -> dict:
    return {"name": name, "value": value, "unit": unit, "source": source, "as_of": as_of}


def trend(mtf: dict | None, technical: dict | None, sources: dict) -> dict:
    d1, h4 = _tf(mtf, "D1"), _tf(mtf, "H4")
    adx, direction = d1.get("adx"), d1.get("direction")
    if adx is None or direction is None:
        return _missing("trend", "Trend", "Trend D1 FTI teď nemá (málo denních svíček nebo chybí zdroj).")
    side = {"up": ("rostoucí", "up"), "down": ("klesající", "down")}.get(direction)
    if side and adx >= ADX_TREND:
        state, word = f"trend_{side[1]}", f"{side[0].capitalize()} trend"
        implication = ("Trendový trh: dávají smysl obchody ve směru trendu (návraty k EMA20/50 na H4 a D1); proti trendu "
                       "jen s potvrzeným obratem.")
    elif side and adx >= ADX_WEAK:
        state, word = f"weak_{side[1]}", f"Slabý {side[0]} trend"
        implication = "Trend se teprve tvoří nebo slábne: menší pozice a potvrzení na H4 před vstupem."
    else:
        state, word = "range", "Pásmo bez trendu"
        implication = ("Trh bez trendu: okraje pásma (swing high a low) jsou místa reakce, průrazy často selhávají — "
                       "čekat na potvrzení, ne na průraz sám.")
    h4_dir = h4.get("direction")
    if h4_dir and side:
        if h4_dir == direction:
            h4_text = "H4 jde stejným směrem"
        elif h4_dir == "sideways":
            h4_text = "H4 je bez směru"
        else:
            h4_text = "H4 jde proti D1 (korekce v trendu, nebo začátek obratu)"
            implication += " H4 teď jde proti D1: vstup ve směru D1 až po obratu H4."
    else:
        h4_text = f"H4: {h4.get('word', '—').lower()}"
    detail = (f"D1: {d1.get('word', '—').lower()}, ADX {_num(adx, 1)} (trend od {ADX_TREND:.0f}, slabý od {ADX_WEAK:.0f}), "
              f"EMA20 {_num(d1.get('ema20'))}, EMA50 {_num(d1.get('ema50'))}; {h4_text}"
              + (f", ADX H4 {_num(h4.get('adx'), 1)}" if h4.get("adx") is not None else "") + ".")
    if technical and technical.get("sma200_pct") is not None:
        p = technical["sma200_pct"]
        detail += f" SMA200 je {_num(abs(p))} % {'pod' if p < 0 else 'nad'} cenou."
    return _dim("trend", "Trend", state, word, detail, implication, [
        _inp("ADX D1", adx, sources.get("D1"), d1.get("as_of")), _inp("směr D1", d1.get("word"), sources.get("D1"), d1.get("as_of")),
        _inp("ADX H4", h4.get("adx"), sources.get("H4"), h4.get("as_of")) if h4 else None,
        _inp("směr H4", h4.get("word"), sources.get("H4"), h4.get("as_of")) if h4 else None])


def volatility(d1_candles: list, technical: dict | None, gold_vol: dict | None, sources: dict, now: dt.datetime) -> dict:
    """From CLOSED daily candles only: the forming day would move the percentile every cycle (and the AI trigger with it)."""
    closed = [c for c in d1_candles if c.time + dt.timedelta(days=1) <= now]
    d1_as_of = market_hours.trading_date(closed[-1].time).isoformat() if closed else None
    atrs = atr_series(closed)
    if len(atrs) < ATR_MIN:
        return _missing("volatilita", "Volatilita", f"Na percentil ATR je potřeba {ATR_MIN} denních ATR, FTI jich má {len(atrs)}.")
    # ATR as a share of the price: a year in which gold rose by a third would otherwise call today "calm" only because
    # the same move in dollars is bigger at a higher price (atrs[k] belongs to closed[k + ATR_N])
    rel = [a / c.close for a, c in zip(atrs, closed[ATR_N:])]
    window = rel[-ATR_WINDOW:]
    now_atr, price = atrs[-1], closed[-1].close
    pct = round(100 * sum(1 for a in window if a <= rel[-1]) / len(window))
    state, word = next((s, w) for lim, s, w in ATR_CLASSES if pct < lim)
    implication = {
        "low": "Klidný trh: denní rozpětí je mezi nejnižšími za rok; stlačená volatilita často předchází silnějšímu pohybu.",
        "normal": "Běžná volatilita: stop-loss a velikost pozice podle obvyklého ATR.",
        "high": "Zvýšená volatilita: širší stop-loss a menší pozice, aby riziko v penězích zůstalo stejné.",
        "extreme": "Extrémní volatilita (horní 5 % roku): velké skoky ceny, stop-loss může proklouznout — výrazně menší pozice.",
    }[state]
    detail = (f"ATR(14) D1 {_num(now_atr)} USD = {_num(100 * now_atr / price)} % ceny, {pct}. percentil ATR v % ceny za "
              f"posledních {len(window)} obchodních dní (uzavřené dny do {d1_as_of}).")
    inputs = [_inp("ATR(14) D1", round(now_atr, 2), sources.get("D1"), d1_as_of, "USD"),
              _inp("percentil ATR", pct, "výpočet FTI", d1_as_of, "%")]
    if gold_vol and gold_vol.get("last") is not None:
        detail += (f" GVZ (implikovaná volatilita zlata) {_num(gold_vol['last'])}, roční medián {_num(gold_vol.get('median'))}, "
                   f"75. percentil {_num(gold_vol.get('p75'))}.")
        inputs.append(_inp("GVZ", gold_vol["last"], "CBOE GVZ (FRED GVZCLS)", gold_vol.get("as_of")))
    if technical and technical.get("volatility20") is not None:
        detail += f" Realizovaná volatilita 20 dní {_num(technical['volatility20'], 1)} % ročně."
        if technical.get("squeeze"):
            detail += " Bollingerova pásma jsou stlačená."
    out = _dim("volatilita", "Volatilita", state, word.capitalize(), detail, implication, inputs)
    out["atr"] = {"d1": round(now_atr, 2), "pct_of_price": round(100 * now_atr / price, 3), "percentile": pct,
                  "window": len(window), "as_of": d1_as_of}
    return out


def risk(intermarket: dict | None) -> dict:
    vix, spx = _item(intermarket, "VIXCLS"), _item(intermarket, "SP500")
    if vix.get("last") is None:
        return _missing("riziko", "Riziková nálada", "VIX FTI teď nemá.")
    level = next(w for lim, w in VIX_CLASSES if vix["last"] < lim)
    ch5, spx20 = vix.get("change_5"), spx.get("change_20")
    if vix["last"] >= 20 and ((ch5 is not None and ch5 >= 2) or (spx20 is not None and spx20 <= -3)):
        state, word = "risk_off", "Riziková averze"
    elif vix["last"] < 16 and (spx20 is None or spx20 >= 0) and (ch5 is None or ch5 <= 0):
        state, word = "risk_on", "Chuť riskovat"
    else:
        state, word = "neutral", "Neutrální"
    detail = f"VIX {_num(vix['last'])} ({level}), za 5 dní {_signed(ch5)} bodu"
    if spx20 is not None:
        detail += f"; S&P 500 za 20 dní {_signed(spx20)} %"
    detail += "."
    stale = [x["label"] for x in (vix, spx) if x.get("stale")]
    if stale:
        detail += f" Zastaralé: {', '.join(stale)}."
    r = spx.get("corr_gold")
    if r is None:
        implication = "Vztah zlata k akciím teď FTI nezná."
    elif r >= CORR_LINK:
        implication = (f"Zlato se teď s akciemi pohybuje souběžně (r {spx.get('corr_days')} dní {_signed(r)}): výprodej akcií "
                       "může stáhnout i zlato — role bezpečného přístavu se v datech teď neukazuje.")
    elif r <= -CORR_LINK:
        implication = (f"Zlato se teď pohybuje proti akciím (r {spx.get('corr_days')} dní {_signed(r)}): riziková averze ho "
                       "v datech podporuje.")
    else:
        implication = f"Vztah zlata k akciím je teď slabý (r {spx.get('corr_days')} dní {_signed(r)}) — nálada na akciích zlato přímo neurčuje."
    return _dim("riziko", "Riziková nálada", state, word, detail, implication, [
        _inp("VIX", vix["last"], vix.get("source"), vix.get("as_of")),
        _inp("VIX změna 5 dní", ch5, vix.get("source"), vix.get("as_of"), "body"),
        _inp("S&P 500 změna 20 dní", spx20, spx.get("source"), spx.get("as_of"), "%") if spx else None,
        _inp("korelace zlato × S&P 500", r, "výpočet FTI", spx.get("as_of")) if r is not None else None])


def dollar(dxy: dict | None, im_d1: dict | None) -> dict:
    trends = {t.get("tf"): t for t in ((dxy or {}).get("trends") or {}).get("timeframes", [])}
    d1, w1 = trends.get("D1") or {}, trends.get("W1") or {}
    if not d1.get("direction"):
        return _missing("dolar", "Dolar", "Trend dolarového indexu FTI teď nemá.")
    a, b = d1.get("direction"), w1.get("direction")
    if a == b == "up":
        state, word = "usd_up", "Dolar posiluje"
    elif a == b == "down":
        state, word = "usd_down", "Dolar oslabuje"
    else:
        state, word = "usd_mixed", "Dolar bez jednoznačného směru"
    detail = (f"DXY D1 {d1.get('word', '—').lower()} (ADX {_num(d1.get('adx'), 1)}), W1 {w1.get('word', '—').lower()}"
              + (f", cena {_num(dxy.get('price'), 3)}" if dxy and dxy.get("price") is not None else "") + ".")
    rel = next((r for r in (im_d1 or {}).get("relations", []) if str(r.get("b", "")).startswith("DXY")), None)
    implication = "Vztah zlata k dolaru FTI teď nemá změřený."
    if rel:
        w = next((x for x in rel.get("windows", []) if x.get("window") == im_d1.get("main_window")), {})
        if w.get("r") is not None:
            implication = (f"Zlato a dolar ({rel['label'].split(' (')[0]}) mají teď korelaci {_signed(w['r'])} "
                           f"({im_d1.get('main_window')} dní, {(rel.get('stability') or {}).get('verdict', '—')})"
                           + (": silnější dolar zlatu obvykle škodí." if w["r"] <= -CORR_LINK else
                              ": dolar teď zlato výrazně neurčuje." if w["r"] > -0.2 else "."))
    return _dim("dolar", "Dolar", state, word, detail, implication, [
        _inp("DXY D1", d1.get("word"), (dxy or {}).get("source"), d1.get("as_of")),
        _inp("DXY W1", w1.get("word"), (dxy or {}).get("source"), w1.get("as_of")) if w1 else None])


def rates(intermarket: dict | None) -> dict:
    real, nom = _item(intermarket, "DFII10"), _item(intermarket, "DGS10")
    if real.get("change_20") is None:
        return _missing("sazby", "Reálné výnosy", "Reálný výnos 10 let FTI teď nemá.")
    ch = real["change_20"]
    if ch >= RATE_STEP:
        state, word = "real_up", "Reálné výnosy rostou"
    elif ch <= -RATE_STEP:
        state, word = "real_down", "Reálné výnosy klesají"
    else:
        state, word = "real_flat", "Reálné výnosy beze změny"
    detail = f"Reálný výnos 10 let {_num(real.get('last'))} %, za 20 dní {_signed(ch)} p. b."
    if nom.get("change_20") is not None:
        detail += f" Nominální výnos 10 let {_num(nom.get('last'))} %, za 20 dní {_signed(nom['change_20'])} p. b."
    r = real.get("corr_gold")
    implication = ("Rostoucí reálné výnosy zdražují držení zlata (nenese úrok), klesající ho zlevňují — to je obvyklý "
                   "mechanismus, ne pravidlo.")
    if r is not None:
        implication += f" V datech FTI je korelace zlata s reálným výnosem teď {real.get('corr_word') or ''} ({_signed(r)}, {real.get('corr_days')} dní)."
    return _dim("sazby", "Reálné výnosy", state, word, detail, implication, [
        _inp("reálný výnos 10 let — změna 20 dní", ch, real.get("source"), real.get("as_of"), "p. b."),
        _inp("nominální výnos 10 let — změna 20 dní", nom.get("change_20"), nom.get("source"), nom.get("as_of"), "p. b.") if nom else None])


def correlations(im_d1: dict | None) -> dict:
    rels = (im_d1 or {}).get("relations") or []
    if not rels:
        return _missing("korelace", "Vztahy se zlatem", "Výsledek Intermarket Intelligence D1 FTI teď nemá.")
    stable = [r["label"] for r in rels if (r.get("stability") or {}).get("verdict") == "stabilní"]
    broken = [r["label"] for r in rels if (r.get("breakdown") or {}).get("state") in ("rozpad", "obrat")]
    new = [r["label"] for r in rels if (r.get("breakdown") or {}).get("state") == "nový vztah"]
    if broken:
        state, word = "breaking", "Vztahy se rozpadají"
        implication = "Část obvyklých vztahů teď neplatí — nepoužívat je jako argument, dokud se neobnoví."
    elif len(stable) >= 2:
        state, word = "stable", "Vztahy drží"
        implication = "Stabilní vztahy lze brát jako potvrzení nebo varování k pohybu zlata (souběh, ne příčina)."
    else:
        state, word = "loose", "Vztahy jsou volné"
        implication = "Pevný vztah má zlato teď jen s málo trhy — mezitrh pohyb zlata potvrzuje jen slabě."
    short = lambda xs: ", ".join(x.split(" (")[0] for x in xs) or "žádný"  # noqa: E731
    detail = (f"Stabilní: {short(stable)}. Rozpad nebo obrat: {short(broken)}. Nový vztah: {short(new)}. "
              f"Okno {im_d1.get('main_window')} dní, spočteno {str(im_d1.get('computed_at'))[:16].replace('T', ' ')} UTC.")
    return _dim("korelace", "Vztahy se zlatem", state, word, detail, implication, [
        _inp("stabilní vztahy", len(stable), "Intermarket Intelligence FTI", im_d1.get("computed_at")),
        _inp("rozpadlé vztahy", len(broken), "Intermarket Intelligence FTI", im_d1.get("computed_at"))])


def compute(d1_candles: list, mtf: dict | None, technical: dict | None, gold_vol: dict | None, intermarket: dict | None,
            dxy: dict | None, im_d1: dict | None, sources: dict, as_of: str) -> dict:
    """The regime of gold from the engine's own results. sources = {tf: source text of gold's candles}."""
    now = dt.datetime.fromisoformat(as_of)
    now = now if now.tzinfo else now.replace(tzinfo=dt.timezone.utc)
    dims = [trend(mtf, technical, sources), volatility(d1_candles, technical, gold_vol, sources, now), risk(intermarket),
            dollar(dxy, im_d1), rates(intermarket), correlations(im_d1)]
    by = {d["key"]: d for d in dims}
    parts = [by["trend"]["word"], f"volatilita {by['volatilita']['word'].lower()}", by["riziko"]["word"].lower()]
    label = " · ".join(p for p in parts if p and "nelze" not in p)
    summary = "; ".join(f"{d['label']}: {d['word'].lower()}" for d in dims if d["available"]) + "."
    return {"as_of": as_of, "label": label, "summary": summary, "dimensions": dims,
            "atr": by["volatilita"].get("atr"), "missing": [d["label"] for d in dims if not d["available"]],
            "method": __doc__.split("\n\n")[1].strip(), "note": NOTE}


def change(new: dict | None, old: dict | None) -> list[str]:
    """Dimensions whose state changed between two regimes (trend, volatility, risk, dollar) — for the AI triggers."""
    if not new or not old:
        return []
    o = {d["key"]: d for d in old.get("dimensions", [])}
    out = []
    for d in new.get("dimensions", []):
        prev = o.get(d["key"])
        if d["key"] in ("trend", "volatilita", "riziko", "dolar") and prev and d["available"] and prev.get("available") \
                and d["state"] != prev["state"]:
            out.append(f"{d['label']}: {prev['word'].lower()} → {d['word'].lower()}")
    return out
