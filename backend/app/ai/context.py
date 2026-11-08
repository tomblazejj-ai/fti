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
        if not payload.get("technical"):
            bars = ((gold_data.get("D1") or {}).get("bars"))
            p.add("Denní technika (SMA 50/200, klíčové úrovně, RSI)", "nespočítána", section="technika",
                  text=f"FTI má jen {bars} denních svíček XAUUSD, výpočet potřebuje 210 — klíčové denní úrovně proto chybí.")
            missing.append("denní technika SMA200 a klíčové úrovně (málo denní historie)")
    section("technika", technique)

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

    # --- the dollar
    def dollar():
        d = payload["dxy"]
        tr = d["trends"]
        corr = d.get("correlation") or {}
        p.add("Dolarový index DXY", _n(d["price"], 3), source="přepočet ICE z Krakenu a ECB", as_of=tr.get("price_time"),
              section="dolar", text=f"Trend intradenní {tr['intraday']['word']}, swing {tr['swing']['word']}, celkově {tr['overall']['word']}.")
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
                p.add(it["label"], it["last"], source=it["source"], as_of=it["as_of"], section="mezitrh",
                      text=(f"{it['unit']}; za 5 obchodních dní {_direction(it['change_5'])} ({_sign(it['change_5'])} {unit}), "
                            f"za 20 dní {_direction(it['change_20'])} ({_sign(it['change_20'])} {unit}); korelace denních změn "
                            f"TÉTO řady se zlatem {it['corr_gold']} ({it['corr_word']}, {it['corr_days']} dní)"
                            + ("; ZASTARALÉ" if it["stale"] else "")))
                # machine-readable for FTI's independent check (app/ai/check.py) — the AI sees it too
                p.facts[-1].update({"rada": it["id"], "smer": {"5d": _direction(it["change_5"]), "20d": _direction(it["change_20"])},
                                    "korelace": [it["corr_gold"]] if it["corr_gold"] is not None else []})
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
