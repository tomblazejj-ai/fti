"""The common analytical context of one instrument — everything FTI knows about it, for the AI analysis.

Built only from what FTI has already fetched and computed (the latest engine payload of the ingestion cycle
and the central price layer); nothing is fetched here and nothing is invented. Every fact carries its
source, its time ("k") and, where it matters, its quality — so the AI can say what is stale or missing.
Facts are grouped by area ("oblast"):

  trh         price, market state, quality of the price data
  technika    trends M15 / H1 / H4 / D1 (EMA, ADX, ATR, swing high/low), what daily technique is missing
  fundament   FTI's fundamental model (FRED macro data with their dates), its score and BIAS
  engine      FTI's rule-based verdict and the active bull/bear conditions — the AI may disagree and must say so
  dolar       DXY: trends, correlation with gold, support/resistance
  mezitrh     VIX, 10y Treasury yield, 10y real yield, WTI, S&P 500 (last, change, correlation) + the other markets
  intermarket Intermarket Intelligence: synchronised correlations of gold with each market (D1, H1), stability,
              breakdown, quality — the authoritative correlations whenever they exist
  intermarket_souhrn  does the intermarket confirm or contradict gold's latest move (D1 week, H1 day)
  pozice      COT (funds, commercials) and retail
  volatilita  GVZ (CBOE gold volatility)
  kalendar    the next important events with previous / forecast
  zpravy      news mood of 72 h, the key headlines, headline risk
  sezonnost   the next 30 days in the last 10 years
  kvalita     sources that are stale, closed or missing

XAU/USD is the first instrument; others follow with the same structure.
"""

from __future__ import annotations

from app.ai import facts as facts_mod
from app.ai.facts import NotReady, Packet

SUPPORTED = ("XAUUSD",)
TECH_TFS = ("M15", "H1", "H4", "D1")


def _n(v, digits: int = 2):
    return None if v is None else round(float(v), digits)


def _cap(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


IM_TFS = ("D1", "H1")
IM_TOP = {"D1": 8, "H1": 5}
IM_BARS = {"D1": "dní", "H1": "hodin", "H4": "svíček H4", "M30": "svíček M30", "M15": "svíček M15"}
# Intermarket market -> the series id FTI's independent check knows (app/ai/check.py ALIASES)
IM_RADA = {"VIX": "VIXCLS", "US10Y": "DGS10", "US10YR": "DFII10", "US02Y": "DGS2", "USOIL": "DCOILWTICO", "UKOIL": "DCOILBRENTEU",
           "US500": "SP500", "DXY": "DXY", "EURUSD": "EURUSD", "USDJPY": "USDJPY", "USTBOND": "USTBOND"}


def _win(rel: dict, window: int) -> dict | None:
    return next((w for w in rel["windows"] if w["window"] == window), None)


def _direction(v) -> str:
    return "beze změny" if not v else "roste" if v > 0 else "klesá"


def _sign(v) -> str:
    return "" if v is None else f"{v:+g}"


def trade(session, code: str = "XAUUSD", quote_fn=None) -> tuple[list[dict], dict]:
    """(facts, meta) of the complex analysis. Raises NotReady when the engine has not computed the inputs."""
    from app.data import prices

    code = (code or "XAUUSD").upper()
    if code not in SUPPORTED:
        raise NotReady(f"Komplexní AI analýza je zatím jen pro XAU/USD — {code} přijde se stejnou architekturou.")
    payload, computed_at = facts_mod.latest_overview(session)
    p = Packet()
    missing: list[str] = []

    def section(name: str, fn) -> None:
        try:
            fn()
        except (KeyError, TypeError, ValueError, AttributeError, IndexError, StopIteration):
            missing.append(name)

    card = facts_mod.market_card(payload, code)
    p.add("Instrument", f"{card['code']} — {card['name']} ({card['subtitle']})", section="trh")
    p.add("Čas výpočtu FTI, ze kterého analýza vychází", computed_at, as_of=computed_at, section="kvalita")

    # --- market and price
    def market():
        facts_mod._quote_facts(p, code, quote_fn or prices.quote, section="trh")
        m = payload.get("market") or {}
        p.add("Stav spotového trhu", "otevřený" if m.get("open") else "zavřený", section="trh",
              text=f"{m.get('reason') or ''}{' Otevře ' + m['next_open'] if m.get('next_open') else ''}".strip() or None)
        from app.live import engine as live_engine, runner as live_runner

        lr = live_runner.get()
        lq = live_engine.quote_for_ai(lr.engine if lr else None, code)
        if lq is not None:  # the LIVE engine runs: its state decides whether the price may be called live at all
            p.add("Živá cena " + code, lq["status"], source=lq.get("product") or lq.get("provider"), as_of=lq.get("quote_time"),
                  section="trh", text=(f"Stav {lq['status']} ({lq['status_cs']}). "
                                       + (f"Bid {lq['bid']}, ask {lq['ask']}, spread {lq['spread']}, kotace stará {lq['age_s']} s. "
                                          if lq.get("bid") is not None else "")
                                       + ("Jen při stavu LIVE je to aktuální cena; jinak je to poslední známá cena a obchodní "
                                          "signál se z ní nevydává. " if lq["status"] != "LIVE" else "")
                                       + " ".join(lq.get("notes") or [])).strip())
        h4 = (payload.get("gold_data") or {}).get("H4") or {}
        if h4:
            q = h4.get("quality") or {}
            p.add("Zdroj svíček XAUUSD", h4.get("source"), source=h4.get("source"), as_of=q.get("as_of"), section="trh",
                  text=f"{h4.get('kind_cs') or ''}. Stav: {q.get('label')}. {q.get('text') or ''}".strip())
    section("cena a stav trhu", market)

    # --- technique
    def technique():
        mtf = payload["mtf"]
        for key in ("intraday", "swing", "overall"):
            t = mtf[key]
            p.add(t["label"], t["word"], section="technika", as_of=mtf.get("price_time"),
                  text=f"Skóre {t['score']:+.2f} (−1 až +1), rámce {', '.join(t['timeframes'])}, souhlasí: {', '.join(t['agree']) or 'žádný'}.")
        if mtf.get("advice"):
            p.add("Doporučení techniky FTI pro typ obchodu", mtf["advice"], section="technika")
        gold_data = payload.get("gold_data") or {}
        for t in mtf["timeframes"]:
            if t["tf"] not in TECH_TFS:
                continue
            p.add(f"Technika {t['tf']} ({t['tf_label']})", t["word"], source=(gold_data.get(t["tf"]) or {}).get("source") or "výpočet FTI",
                  as_of=t.get("as_of"), section="technika",
                  text=(f"Závěr {_n(t['close'])}, EMA20 {_n(t['ema20'])}, EMA50 {_n(t['ema50'])}, ADX {_n(t['adx'], 1)} ({t['strength']}), "
                        f"ATR {_n(t['atr'])}, swing high {_n(t['swing_high'])}, swing low {_n(t['swing_low'])}, "
                        f"změna {_n(t['change_pct'])} % za {t['change_bars']} svíček." + (f" {t['text']}" if t["tf"] in ("H4", "D1") else "")))
        tech = payload.get("technical")
        if tech:  # the daily technique (SMA50/200, RSI, levels) — it feeds the verdict, so the AI must see it too
            d1_src = (gold_data.get("D1") or {}).get("source") or "výpočet FTI"
            last = (tech.get("history") or [{}])[-1]

            def rel(pct):
                return f"{abs(pct):.2f} % {'pod' if pct < 0 else 'nad'} cenou"

            div = {"bullish": "býčí", "bearish": "medvědí"}.get(tech.get("divergence"), "žádná")
            p.add("Denní technika XAUUSD (SMA50/200, RSI, MACD)", tech["trend_label"], source=d1_src, as_of=tech["as_of"],
                  section="technika",
                  text=(f"Denní závěr {_n(tech['last_price'])}, SMA50 {_n(last.get('sma50'))} ({rel(tech['sma50_pct'])}), "
                        f"SMA200 {_n(last.get('sma200'))} ({rel(tech['sma200_pct'])}), RSI14 {_n(tech['rsi14'], 1)} "
                        f"({tech['rsi_state']}), MACD {'nad' if tech.get('macd_bullish') else 'pod'} signální linií, "
                        f"divergence RSI {div}, skóre denní techniky {_sign(tech['tech_score'])} (−100 až +100). "
                        f"{tech.get('trend_age_text') or ''}").strip())
            for key, word in (("supports", "podpory"), ("resistances", "rezistence")):
                levels = [lv for lv in tech.get(key) or [] if lv.get("price") is not None]
                if levels:
                    p.add(f"Denní {word} XAUUSD", ", ".join(f"{_n(lv['price'])}" for lv in levels), source=d1_src,
                          as_of=tech["as_of"], section="technika",
                          text="; ".join(f"{lv['label']} {_n(lv['price'])} ({_sign(lv['pct'])} % od ceny"
                                         f"{', dotyků ' + str(lv['touches']) if lv.get('touches', 1) > 1 else ''})" for lv in levels))
        else:
            bars = ((gold_data.get("D1") or {}).get("bars"))
            p.add("Denní technika (SMA 50/200, klíčové úrovně, RSI)", "nespočítána", section="technika",
                  text=f"FTI má jen {bars} denních svíček XAUUSD, výpočet potřebuje 210 — klíčové denní úrovně proto chybí.")
            missing.append("denní technika SMA200 a klíčové úrovně (málo denní historie)")
    section("technika", technique)

    # --- market regime (Ú2): what kind of market it is — context for the kind of trade, not a vote in the verdict
    def regime_facts():
        rg = payload.get("regime")
        if not rg:
            missing.append("režim trhu (výpočet FTI ho ještě nemá)")
            return
        p.add("Režim trhu XAUUSD", rg["label"], as_of=rg.get("as_of"), section="rezim", text=f"{rg['summary']} {rg['note']}")
        for d in rg["dimensions"]:
            if not d["available"]:
                missing.append(f"režim trhu — {d['label'].lower()}: {d['detail']}")
                continue
            srcs = sorted({i["source"] for i in d["inputs"] if i.get("source")})
            as_of = max((str(i["as_of"]) for i in d["inputs"] if i.get("as_of")), default=None)
            p.add(f"Režim trhu — {d['label']}", d["word"], source=", ".join(srcs) or None, as_of=as_of, section="rezim",
                  text=d["detail"] + (f" {d['implication']}" if d.get("implication") else ""))
    section("režim trhu", regime_facts)

    # --- fundamental model (FRED data inside the components)
    def fundamental():
        p.add("Fundamentální skóre FTI", card["score10"], as_of=computed_at, section="fundament",
              text=f"Rozsah −10 až +10, součet kategorií {card.get('raw')} z ±{card.get('possible')}. {card.get('word') or ''}")
        p.add("Fundamentální BIAS FTI", card["bias"], as_of=computed_at, section="fundament")
        for c in card.get("components") or []:
            p.add(f"Složka: {c['label']}", c.get("score"), source="výpočet FTI z FRED, CFTC a dalších", section="fundament",
                  text=_cap(f"±{c.get('max')}. {c.get('text') or ''} " + "; ".join(c.get("details") or []), 260))
        if card.get("missing"):
            p.add("Chybějící složky fundamentálního modelu", ", ".join(card["missing"]), section="fundament")
    section("fundamentální model", fundamental)

    # --- FTI's own rule-based verdict
    def engine():
        v = payload["verdict"]
        p.add("Pravidlový verdikt FTI", v.get("action_text"), as_of=computed_at, section="engine",
              text=f"{v.get('direction_text')}. Kombinované skóre {_n(v.get('combined'), 3)}, jistota {v.get('confidence')}. "
                   + " ".join(v.get("reasons") or []))
        d = payload.get("decision") or {}
        if d.get("headline"):
            p.add("Podmínky pro růst a pokles (FTI)", d["headline"], section="engine",
                  text="Platí pro růst: " + ("; ".join(c["title"] for c in d.get("bull", []) if c.get("active")) or "žádná")
                       + ". Platí pro pokles: " + ("; ".join(c["title"] for c in d.get("bear", []) if c.get("active")) or "žádná") + ".")
    section("pravidlový verdikt FTI", engine)

    # --- Intermarket Intelligence: synchronised correlations (the authoritative ones whenever they exist)
    im_codes: set[str] = set()

    def intermarket_intel():
        from app.market import intermarket_intel as imi

        for tf in IM_TFS:
            res = imi.get(session, tf)
            if res.get("error") or not res.get("relations"):
                missing.append(f"Intermarket {tf}: {res.get('error') or 'žádné synchronizované vztahy'}")
                continue
            main = res["main_window"]
            rels = [r for r in res["relations"] if (_win(r, main) or {}).get("r") is not None]
            conf = [r for r in rels if (r.get("move") or {}).get("verdict") == "potvrzuje"]
            contra = [r for r in rels if (r.get("move") or {}).get("verdict") == "odporuje"]
            verdict = ("odporuje" if len(contra) > len(conf) else "potvrzuje" if len(conf) > len(contra) else
                       "smíšené" if conf else "nelze posoudit")
            mv = next((r["move"] for r in rels if r.get("move")), None)
            span = f"za posledních {mv['bars']} {IM_BARS[tf]} ({mv.get('from', '')[:16]} → {mv['until'][:16]} UTC)" if mv else ""
            p.add(f"Mezitrh {tf}: potvrzení pohybu zlata", verdict, source="Intermarket Intelligence FTI",
                  as_of=mv["until"] if mv else res["computed_at"], section="intermarket_souhrn",
                  text=(f"Zlato {span} {_sign(mv['gold_pct'])} %. " if mv else "")
                       + f"Potvrzují: {', '.join(r['label'] for r in conf) or 'žádný trh'}. "
                       + f"Odporují: {', '.join(r['label'] for r in contra) or 'žádný trh'}. "
                       + "Posuzují se jen pevné vztahy (|r| ≥ 0,3, p < 0,01) změřené PŘED tímto pohybem.")
            p.facts[-1]["mezitrh"] = {"tf": tf, "verdict": verdict, "gold_pct": mv["gold_pct"] if mv else None}
            for r in rels[:IM_TOP[tf]]:
                w, lw = _win(r, main), _win(r, imi.LONG[tf])
                ch, st, bd, m = r.get("change") or {}, r.get("stability") or {}, r.get("breakdown") or {}, r.get("move") or {}
                q = r["quality"]
                p.add(f"Korelace zlata s {r['label']} ({tf})", w["r"], source=" + ".join(dict.fromkeys(r["sources"])),
                      as_of=r["last_common"], section="intermarket",
                      text=_cap(f"Synchronizované výnosy, okno {main} {IM_BARS[tf]}: r {_sign(w['r'])} (n {w['n']}, efektivně "
                                f"{_n(w['n_eff'], 0)}, p {w['p']}, q {r.get('q_main')}). "
                                + (f"Okno {lw['window']}: r {_sign(lw['r'])} (n {lw['n']}). " if lw and lw.get("r") is not None else "")
                                + (f"Předchozí okno {main}: r {_sign(ch['r_prev'])}, změna {_sign(ch['delta'])} "
                                   f"({'významná' if ch.get('significant') else 'nevýznamná'}). " if ch else "")
                                + (f"Stabilita: {st['verdict']}. " if st else "") + (f"Rozpad: {bd['state']}. " if bd else "")
                                + (f"Za posledních {m['bars']} {IM_BARS[tf]}: {_sign(m['other'])} {m['other_unit']} → {m['verdict']}. "
                                   if m else "")
                                + f"Kvalita {q['label']}" + (f" ({'; '.join(q['issues'])})" if q["issues"] else "") + ". "
                                + (f"Příbuzné konstrukcí: {r['related']}. " if r.get("related") else "")
                                + "Souběh, ne příčina.", 520))
                rada = IM_RADA.get(r["b_code"].replace(".CFD", "").replace("*", ""))
                p.facts[-1].update({"rada": rada or r["b_code"],
                                    "korelace": [x["r"] for x in r["windows"] if x.get("r") is not None]})
                im_codes.add(rada or r["b_code"])
    section("Intermarket Intelligence", intermarket_intel)

    # --- the dollar
    def dollar():
        d = payload["dxy"]
        tr = d["trends"]
        corr = d.get("correlation") or {}
        p.add("Dolarový index DXY", _n(d["price"], 3), source="přepočet ICE z Krakenu a ECB", as_of=tr.get("price_time"),
              section="dolar", text=f"Trend intradenní {tr['intraday']['word']}, swing {tr['swing']['word']}, celkově {tr['overall']['word']}.")
        if "DXY" not in im_codes:  # with Intermarket's synchronised correlation the older estimate would only contradict it
            p.add("Korelace zlata s DXY", _n((corr.get("d60") or {}).get("value")), section="dolar",
                  text=f"60 dní {_n((corr.get('d60') or {}).get('value'))} ({(corr.get('d60') or {}).get('label')}), "
                       f"20 dní {_n((corr.get('d20') or {}).get('value'))}, hodinová {_n((corr.get('h1') or {}).get('value'))}. "
                       "Souběh pohybů, ne příčina.")
            p.facts[-1].update({"rada": "DXY", "korelace": [v for v in ((corr.get(k) or {}).get("value") for k in ("d60", "d20", "h1"))
                                                            if v is not None]})
        kl = d.get("key_levels") or {}
        if kl.get("text"):
            p.add("Úrovně DXY", kl["text"], section="dolar", text=kl.get("filter"))
    section("dolar", dollar)

    # --- intermarket
    def intermarket():
        im = payload.get("intermarket")
        if not im:
            missing.append("mezitržní řady VIX, výnosy, ropa, S&P 500 (výpočet je ještě nepřepočítal)")
        else:
            for it in im["items"]:
                unit = "p. b." if it["unit"] == "%" else it["change_unit"]  # a yield moves in percentage points
                synced = it["id"] in im_codes  # Intermarket has the synchronised correlation of this series
                p.add(it["label"], it["last"], source=it["source"], as_of=it["as_of"], section="mezitrh",
                      text=(f"{it['unit']}; za 5 obchodních dní {_direction(it['change_5'])} ({_sign(it['change_5'])} {unit}), "
                            f"za 20 dní {_direction(it['change_20'])} ({_sign(it['change_20'])} {unit})"
                            + ("; korelaci se zlatem uvádí Intermarket (synchronizované výnosy)" if synced else
                               f"; korelace denních změn TÉTO řady se zlatem {it['corr_gold']} ({it['corr_word']}, {it['corr_days']} dní)")
                            + ("; ZASTARALÉ" if it["stale"] else "")))
                # machine-readable for FTI's independent check (app/ai/check.py) — the AI sees it too
                p.facts[-1].update({"rada": it["id"], "smer": {"5d": _direction(it["change_5"]), "20d": _direction(it["change_20"])},
                                    "korelace": [it["corr_gold"]] if it["corr_gold"] is not None and not synced else []})
            if im.get("missing"):
                missing.extend(im["missing"])
        for m in (payload.get("markets") or {}).get("markets", []):
            if m["code"] != code:
                p.add(f"Trh {m['code']}", m["bias"], section="mezitrh",
                      text=f"Fundamentální skóre FTI {m['score10']} (−10 až +10), trend {m.get('trend') or '—'}.")
    section("mezitrh", intermarket)

    # --- positioning
    def positioning():
        c = payload["cot"]
        p.add("COT — fondy (non-commercial) net", c.get("spec_net"), source="CFTC COT", as_of=c.get("as_of"), section="pozice",
              text=f"změna za týden {_sign(c.get('change_1w'))}, za 4 týdny {_sign(c.get('change_4w'))} kontraktů; COT index 1 rok "
                   f"{c.get('cot_index_1y')}/100, 3 roky {c.get('cot_index_3y')}/100; extrém: {c.get('extreme')}. "
                   + " ".join(c.get("texts") or []))
        r = card.get("retail") or {}
        if r.get("long_pct") is not None:
            p.add("Malí obchodníci long (CFTC non-reportable)", r["long_pct"], source="CFTC", as_of=r.get("as_of"), section="pozice",
                  text=f"Změna za 4 týdny {r.get('change_4w')} p. b. {r.get('head') or ''}")
    section("pozice (COT)", positioning)

    def volatility():
        g = payload["gold_vol"]
        p.add("Volatilita zlata GVZ (CBOE)", g["last"], source="FRED GVZCLS", as_of=g["as_of"], section="volatilita",
              text=f"medián roku {g['median']}, 75. percentil {g['p75']} — {'zvýšená' if g['elevated'] else 'běžná'}.")
    section("volatilita GVZ", volatility)

    # --- calendar
    def calendar():
        cal = payload["calendar"]
        upcoming = [e for e in cal.get("events", []) if not e.get("past") and (e.get("importance") or 0) >= 2][:5]
        for e in upcoming:
            p.add(f"Událost: {e['name']}", e.get("datetime"), source=e.get("source") or "kalendář FTI", as_of=e.get("datetime"),
                  section="kalendar", text=f"Důležitost {e.get('importance')}/3. Minule: {e.get('previous') or '—'}. Očekávání: "
                                           f"{e.get('forecast') or 'neuvedeno'}. Zlato spíš nahoru, když {e.get('up_if') or '—'}; "
                                           f"dolů, když {e.get('down_if') or '—'}.")
        if not upcoming:
            p.add("Nadcházející důležité události", "žádné v kalendáři FTI", section="kalendar")
    section("kalendář", calendar)

    # --- news
    def news():
        n = payload["news"]
        p.add("Nálada zpráv o zlatě", n.get("score"), source="klasifikace zpráv FTI", section="zpravy",
              text=f"Za {n.get('hours')} h {n.get('count')} zpráv: {n.get('bullish')} pro růst, {n.get('bearish')} pro pokles (−1 až +1)."
                   + (f" Bez času publikace nezapočteno: {n['unknown_age']}." if n.get("unknown_age") else ""))
        for item in (n.get("key") or [])[:4]:
            p.add_news("Klíčová zpráva", item, section="zpravy")
        h = payload.get("headline_risk") or {}
        if h:
            p.add("Riziko neplánovaných titulků", h.get("word"), section="zpravy",
                  text=f"Úroveň {h.get('level')}/2 za {h.get('hours')} h, souběh více zdrojů: {'ano' if h.get('cluster') else 'ne'}; "
                       + "; ".join(f"{i['topic']}: {_cap(i['title'], 90)}" for i in (h.get("items") or [])[:2]))
    section("zprávy", news)

    def season():
        g = ((payload.get("season_daily") or {}).get("gold") or {}).get("next30") or {}
        if g:
            p.add("Sezónnost zlata na příštích 30 dní", g.get("avg"), source="referenční řada NBP 2016–2025", section="sezonnost",
                  text=f"průměrná změna {g.get('avg')} %, růst v {g.get('up')} z {g.get('n')} let ({g.get('from_text')}–{g.get('to_text')}).")
    section("sezónnost", season)

    # --- data quality
    def quality():
        bad = [s for s in payload.get("sources_status") or [] if s.get("status") not in ("ok",)]
        for s in bad:
            p.add(f"Stav zdroje: {s['label']}", s["status"], source=s.get("provider"), as_of=s.get("as_of"), section="kvalita",
                  text=s.get("note"))
    section("kvalita dat", quality)

    for m in missing:
        p.add("Chybí", m, section="kvalita")
    return p.facts, {"engine_computed_at": computed_at, "instrument": code, "missing": missing}
