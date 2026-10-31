"""One plain-language swing-trading read for gold. Pure function.

Five factors, each scored −1 (dolů) … +1 (nahoru), with one Czech sentence:
  fundament  makro model (Fed, výnosy, inflace, dolar, ekonomika)   35 %
  technika   trend + momentum (technical tech_score)               35 %
  cot        what the funds are doing (CFTC COT)                   10 %
  zpravy     tone of the last 72 h of news from all portals        10 %
  trhy       dollar, yields, stocks… moving with/against gold      10 %
Missing factors are dropped and the remaining weights renormalised.

  |celkem| < 0,20                        → BEZ JASNÉHO SMĚRU → vyčkat
  fundament a technika silně proti sobě  → vyčkat
  jinak                                  → SPÍŠE NAHORU / SPÍŠE DOLŮ

A rules-based summary of the data on screen, not a prediction and not
investment advice — the UI says so next to it.
"""

from __future__ import annotations

from app.scoring.base import cz, cz_date
from app.scoring.xauusd import PILLAR_DISPLAY

WEIGHTS = {"fundament": 0.35, "technika": 0.35, "cot": 0.10, "zpravy": 0.10, "trhy": 0.10}
LABELS = {"fundament": "Fundament (makro)", "technika": "Technická analýza", "cot": "Fondy (COT)",
          "zpravy": "Zprávy", "trhy": "Ostatní trhy"}
NO_EDGE = 0.20
CONFLICT = 0.20
FACTOR_DEAD = 0.15
MIN_NEWS = 3

PILLAR_WORDS = {  # what a negative/positive pillar means in plain words
    "real_yields": ("reálné výnosy rostou", "reálné výnosy klesají"),
    "fed": ("Fed je jestřábí (vyšší sazby)", "Fed je holubičí (nižší sazby)"),
    "usd": ("dolar posiluje", "dolar slábne"),
    "inflation": ("inflace zrychluje", "inflace zpomaluje"),
    "economy": ("ekonomika je silná", "ekonomika slábne"),
    "geopolitics": ("geopolitika se uklidňuje", "roste geopolitické napětí"),
    "central_banks": ("centrální banky zlato prodávají", "centrální banky zlato nakupují"),
    "positioning": ("fondy snižují pozice", "fondy přikupují"),
}


def _sign(x: float, dead: float = 0.0) -> int:
    return 1 if x > dead else -1 if x < -dead else 0


def _lvl(level: dict) -> str:
    """"4 235 $, +1,1 %" when the level has a USD price, else just the %."""
    price = level.get("price")
    if price:
        return f"{price:,.0f}".replace(",", " ") + f" $, {_pct(level['pct'])}"
    return _pct(level["pct"])


def _pct(v: float) -> str:
    return cz(v, "+.1f") + " %"


def _dir(score: float) -> str:
    return "up" if score > FACTOR_DEAD else "down" if score < -FACTOR_DEAD else "flat"


def build_verdict(
    fundamental: dict,
    technical: dict | None,
    correlations: list[dict] | None,
    gold_vol: dict | None,
    next_fomc: str | None,
    cot: dict | None = None,
    news: dict | None = None,
) -> dict:
    factors: list[dict] = []
    pillars = fundamental.get("pillar_breakdown", {})

    # 1) fundament
    score = fundamental["score"]
    f_val = (score - 50.0) / 50.0
    movers = sorted(
        ((n, p) for n, p in pillars.items() if p["data_quality"] != "unavailable" and abs(p["points"]) >= 0.5),
        key=lambda item: -abs(item[1]["points"]),
    )[:2]
    why = " a ".join(PILLAR_WORDS[n][0 if p["points"] < 0 else 1] for n, p in movers if n in PILLAR_WORDS)
    f_dir = _dir(f_val)
    f_sentence = {
        "down": f"Makro mluví pro pokles zlata — {why or 'bez výrazného důvodu'}.",
        "up": f"Makro mluví pro růst zlata — {why or 'bez výrazného důvodu'}.",
        "flat": "Makro data jsou vyrovnaná, jasný směr nedávají" + (f" ({why})." if why else "."),
    }[f_dir]
    factors.append({"key": "fundament", "score": f_val, "detail": f"skóre {cz(score)}/100", "sentence": f_sentence})

    # 2) technika
    if technical:
        t_val = technical.get("tech_score", technical["trend_score"]) / 100.0
        macd = "MACD pod signálem" if technical.get("macd_bullish") is False else "MACD nad signálem" if technical.get("macd_bullish") else None
        bits = [technical["trend_label"].lower(), macd, f"RSI {cz(technical['rsi14'] or 0, '.0f')} ({technical['rsi_state']})"]
        factors.append({"key": "technika", "score": t_val, "detail": f"skóre {cz(technical.get('tech_score', technical['trend_score']), '+.0f')}",
                        "sentence": cz_cap(", ".join(b for b in bits if b)) + "."})

    # 3) COT
    if cot:
        factors.append({"key": "cot", "score": cot["signal"],
                        "detail": f"COT index {cz(cot['cot_index_3y'], '.0f')}/100" if cot.get("cot_index_3y") is not None else "",
                        "sentence": cot["texts"][1] if len(cot["texts"]) > 1 else cot["texts"][0]})

    # 4) zprávy
    if news and news.get("score") is not None and news.get("count", 0) >= MIN_NEWS:
        factors.append({"key": "zpravy", "score": max(-1.0, min(1.0, news["score"])),
                        "detail": f"{news['count']} zpráv za {news['hours']} h",
                        "sentence": f"Za poslední {news['hours'] // 24} dny {news['bullish']} zpráv mluví pro růst a {news['bearish']} pro pokles zlata."})

    # 5) ostatní trhy
    strong = [c for c in (correlations or []) if c.get("available") and c.get("corr_now") is not None and abs(c["corr_now"]) >= 0.3]
    if strong:
        brakes = [c for c in strong if c["effect"] < 0]
        helps = [c for c in strong if c["effect"] > 0]
        m_val = sum(c["effect"] for c in strong) / len(strong)

        def short(items: list[dict]) -> str:
            return ", ".join(c["label"].split(" (")[0].lower() for c in items[:2])

        sentence = (f"Zlato brzdí: {short(brakes)}" if brakes else "Nic zlato výrazně nebrzdí")
        sentence += (f"; pomáhá: {short(helps)}." if helps else ".")
        factors.append({"key": "trhy", "score": m_val, "detail": f"{len(brakes)} brzdí, {len(helps)} pomáhá", "sentence": sentence})

    for f in factors:
        f["label"] = LABELS[f["key"]]
        f["direction"] = _dir(f["score"])
        f["weight"] = WEIGHTS[f["key"]]
        f["score"] = round(f["score"], 3)

    total_w = sum(f["weight"] for f in factors)
    combined = sum(f["weight"] * f["score"] for f in factors) / total_w
    by_key = {f["key"]: f for f in factors}
    tech_val = by_key["technika"]["score"] if "technika" in by_key else None
    conflict = tech_val is not None and abs(f_val) >= CONFLICT and abs(tech_val) >= CONFLICT and _sign(f_val) != _sign(tech_val)

    if conflict:
        action, direction = "wait", 0
        direction_text = "ZLATO: BEZ JASNÉHO SMĚRU"
        action_text = "Vyčkat — fundament a technika jdou proti sobě."
    elif abs(combined) < NO_EDGE:
        action, direction = "wait", 0
        direction_text = "ZLATO: BEZ JASNÉHO SMĚRU"
        action_text = "Vyčkat — žádná strana nemá výhodu."
    else:
        direction = _sign(combined)
        action = "long" if direction > 0 else "short"
        strength = "" if abs(combined) >= 0.5 else "SPÍŠE "
        direction_text = f"ZLATO: {strength}{'NAHORU' if direction > 0 else 'DOLŮ'}"
        action_text = "Swing: hledat nákup (long)." if direction > 0 else "Swing: hledat prodej (short)."

    n_up = sum(1 for f in factors if f["direction"] == "up")
    n_down = sum(1 for f in factors if f["direction"] == "down")
    summary = f"{n_down} z {len(factors)} faktorů ukazuje dolů, {n_up} nahoru."

    if direction == 0:
        confidence = "nízká"
    else:
        aligned = sum(1 for f in factors if _sign(f["score"], FACTOR_DEAD) == direction)
        opposed = sum(1 for f in factors if _sign(f["score"], FACTOR_DEAD) == -direction)
        confidence = "vysoká" if aligned >= len(factors) - 1 and opposed == 0 and abs(combined) >= 0.4 else "střední" if aligned > opposed else "nízká"

    # ---------- timing + levels ----------
    support = technical["supports"][0] if technical and technical["supports"] else None
    resistance = technical["resistances"][0] if technical and technical["resistances"] else None
    timing = None
    if technical and action == "long":
        if technical["rsi_state"] == "překoupeno":
            timing = "Trh je překoupený — nekupovat hned, počkat na pokles k podpoře" + (f" ({_lvl(support)})." if support else ".")
        elif support:
            timing = f"Nákup hledat při poklesu k podpoře ({_lvl(support)}), ne na maximech."
    elif technical and action == "short":
        if technical["rsi_state"] == "přeprodáno":
            timing = "Trh je přeprodaný — neprodávat do propadu, počkat na odraz k odporu" + (f" ({_lvl(resistance)})." if resistance else ".")
        elif resistance:
            timing = f"Prodej hledat při odrazu k odporu ({_lvl(resistance)}), ne na minimech."
    elif conflict:
        timing = "Krátkodobě vede technika, střednědobě fundament. Pokud obchodovat, tak jen krátce ve směru trendu a s menší pozicí."
    else:
        timing = "Bez výhody je nejlepší obchod žádný obchod — počkat na jasnější signál."

    # ---------- risks & what would change the view ----------
    risks: list[str] = []
    if next_fomc:
        risks.append(f"Rozhodnutí Fedu (FOMC) {cz_date(next_fomc)} může výhled rychle změnit.")
    if action == "short" and support and support["pct"] > -1.5:
        risks.append(f"Cena je jen {cz(abs(support['pct']))} % nad podporou — prodávat přímo na podpoře je riskantní.")
    if action == "long" and resistance and resistance["pct"] < 1.5:
        risks.append(f"Cena je jen {cz(resistance['pct'])} % pod odporem — nakupovat přímo pod odporem je riskantní.")
    if cot and cot.get("extreme") == "crowded_long" and action == "long":
        risks.append("Fondy už jsou silně long — pro další růst chybí noví kupci.")
    if cot and cot.get("extreme") == "light" and action == "short":
        risks.append("Fondy už mají velmi málo long pozic — prostor pro další výprodej je omezený.")
    if technical and technical.get("divergence") == "bullish" and action == "short":
        risks.append("Býčí divergence RSI — prodejní tlak slábne.")
    if technical and technical.get("divergence") == "bearish" and action == "long":
        risks.append("Medvědí divergence RSI — nákupní tlak slábne.")
    if gold_vol and gold_vol.get("elevated"):
        risks.append(f"Kolísavost zlata je zvýšená (GVZ {cz(gold_vol['last'])}) — širší stop-loss, menší pozice.")
    if conflict:
        risks.append("Fundament a technika si odporují — signál je méně spolehlivý.")

    change_view: list[str] = []
    if technical and technical.get("sma200_pct") is not None:
        p = technical["sma200_pct"]
        if action == "long" and p < 0:
            change_view.append(f"Pád ceny pod 200denní průměr ({_pct(p)}).")
        if action == "short" and p > 0:
            change_view.append(f"Návrat ceny nad 200denní průměr ({_pct(p)}).")
    if technical and technical.get("sma50_pct") is not None:
        p = technical["sma50_pct"]
        if action == "short" and p > 0:
            change_view.append(f"Uzavření dne nad 50denním průměrem ({_pct(p)}) by bylo první varování.")
        if action == "long" and p < 0:
            change_view.append(f"Uzavření dne pod 50denním průměrem ({_pct(p)}) by bylo první varování.")
    if movers:
        n, p = movers[0]
        change_view.append(f"Obrat v pilíři {PILLAR_DISPLAY[n]} (teď {cz(p['points'], '+.1f')} b.).")

    return {
        "action": action,
        "direction_text": direction_text,
        "action_text": action_text,
        "headline": f"{direction_text} — {action_text}",
        "summary": summary,
        "confidence": confidence,
        "combined": round(combined, 3),
        "factors": factors,
        "components": {f["key"]: f["score"] for f in factors},
        "weights": {f["key"]: f["weight"] for f in factors},
        "reasons": [f["sentence"] for f in factors],
        "timing": timing,
        "support": support,
        "resistance": resistance,
        "risks": risks,
        "change_view": change_view,
    }


def cz_cap(text: str) -> str:
    return text[:1].upper() + text[1:]
