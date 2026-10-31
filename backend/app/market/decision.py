"""„Co rozhodne o směru“ — what has to happen for gold to go up vs. down.

Pure rules over data the cycle already has (no new numbers are invented):
  - cena: nearest daily support/resistance in USD, 200-day average, H4 swing
  - fundament: the strongest pillars of the model, in plain words
  - fondy (COT): are managed-money funds adding or cutting
  - trend: the swing trend blend
  - události: the next important releases with what result helps which side
Every condition carries `active` = it is what the data say right now.
"""

from __future__ import annotations

import datetime as dt

from app.verdict import PILLAR_WORDS

PILLAR_TITLES = {
    "real_yields": "Reálné výnosy", "fed": "Fed a sazby", "usd": "Americký dolar", "inflation": "Inflace",
    "economy": "Ekonomika USA", "geopolitics": "Geopolitika", "central_banks": "Centrální banky", "positioning": "Pozice fondů",
}


def _usd(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ") + " $"


def _price_items(technical: dict | None, mtf: dict | None) -> tuple[list[dict], list[dict], dict]:
    bull, bear, levels = [], [], {}
    if not technical:
        return bull, bear, levels
    last = technical.get("last_price")
    res = (technical.get("resistances") or [None])[0]
    sup = (technical.get("supports") or [None])[0]
    if res:
        where = _usd(res["price"]) if res.get("price") else f"{res['pct']:+.1f} %".replace(".", ",")
        bull.append({"kind": "price", "title": f"Průraz nad {where}", "detail": f"nejbližší odpor ({res['label'].lower()})", "active": False})
        levels["up"] = {"price": res.get("price"), "pct": res["pct"], "label": res["label"]}
    if sup:
        where = _usd(sup["price"]) if sup.get("price") else f"{sup['pct']:+.1f} %".replace(".", ",")
        bear.append({"kind": "price", "title": f"Pád pod {where}", "detail": f"nejbližší podpora ({sup['label'].lower()})", "active": False})
        levels["down"] = {"price": sup.get("price"), "pct": sup["pct"], "label": sup["label"]}
    p200 = technical.get("sma200_pct")
    if last and p200 is not None:
        ma = last * (1 + p200 / 100)
        if p200 > 0:
            bull.append({"kind": "price", "title": f"Návrat nad 200denní průměr ({_usd(ma)})",
                         "detail": "dlouhodobý trend by se otočil nahoru", "active": False})
        else:
            bear.append({"kind": "price", "title": f"Pád pod 200denní průměr ({_usd(ma)})",
                         "detail": "dlouhodobý trend by se otočil dolů", "active": False})
    h4 = next((t for t in (mtf or {}).get("timeframes", []) if t["tf"] == "H4"), None)
    if h4 and h4.get("swing_high") and h4.get("swing_low"):
        bull.append({"kind": "price", "title": f"H4 nad swing maximem {_usd(h4['swing_high'])}", "detail": "intradenní signál obratu nahoru",
                     "active": h4["close"] > h4["swing_high"]})
        bear.append({"kind": "price", "title": f"H4 pod swing minimem {_usd(h4['swing_low'])}", "detail": "intradenní pokračování dolů",
                     "active": h4["close"] < h4["swing_low"]})
    return bull, bear, levels


def build(verdict: dict, technical: dict | None, mtf: dict | None, calendar: dict | None, cot: dict | None,
          pillar_breakdown: dict | None, now: dt.datetime, dollar: dict | None = None) -> dict:
    bull, bear, levels = _price_items(technical, mtf)

    if dollar and dollar.get("trends", {}).get("swing"):
        corr = ((dollar.get("correlation") or {}).get("d60") or {}).get("value")
        if corr is not None and corr <= -0.15:  # only when gold actually moves against the dollar
            lean = dollar["trends"]["swing"]["lean"]
            lv = dollar.get("levels") or {}
            low = f" pod {lv['swing_low']:.2f}".replace(".", ",") if lv.get("swing_low") else ""
            high = f" nad {lv['swing_high']:.2f}".replace(".", ",") if lv.get("swing_high") else ""
            bull.append({"kind": "dxy", "title": f"Dolar (DXY) oslabí{low}", "detail": f"korelace se zlatem {corr:+.2f}".replace(".", ",").replace("-", "−"),
                         "active": lean == "down"})
            bear.append({"kind": "dxy", "title": f"Dolar (DXY) dál posiluje{high}", "detail": f"korelace se zlatem {corr:+.2f}".replace(".", ",").replace("-", "−"),
                         "active": lean == "up"})

    movers = sorted(
        ((n, p) for n, p in (pillar_breakdown or {}).items() if n in PILLAR_WORDS and p.get("data_quality") != "unavailable"),
        key=lambda x: -abs(x[1].get("points", 0.0)),
    )[:3]
    for name, p in movers:
        pts = p.get("points", 0.0)
        bear_w, bull_w = PILLAR_WORDS[name]
        title = PILLAR_TITLES.get(name, name)
        bull.append({"kind": "fund", "title": f"{title}: {bull_w}", "detail": f"váha v modelu {p.get('weight', 0):.0f} %",
                     "active": pts > 0.05})
        bear.append({"kind": "fund", "title": f"{title}: {bear_w}", "detail": f"váha v modelu {p.get('weight', 0):.0f} %",
                     "active": pts < -0.05})

    if cot:
        ch4 = cot.get("change_4w", 0)
        bull.append({"kind": "cot", "title": "Fondy začnou přikupovat zlato", "detail": "COT: managed money, týdenní report CFTC",
                     "active": ch4 > 0})
        bear.append({"kind": "cot", "title": "Fondy dál prodávají", "detail": "COT: managed money, týdenní report CFTC",
                     "active": ch4 < 0})

    swing = (mtf or {}).get("swing")
    if swing:
        bull.append({"kind": "trend", "title": "Swingový trend (H4, D1, W1) nahoru", "detail": f"teď: {swing['word'].lower()}",
                     "active": swing["lean"] == "up"})
        bear.append({"kind": "trend", "title": "Swingový trend (H4, D1, W1) dolů", "detail": f"teď: {swing['word'].lower()}",
                     "active": swing["lean"] == "down"})

    events = [
        {"name": e["name"], "date": e["date"], "time": e["time"], "importance": e["importance"],
         "up_if": e.get("up_if", ""), "down_if": e.get("down_if", "")}
        for e in (calendar or {}).get("events", []) if not e["past"] and e["importance"] >= 2
    ][:5]

    n_bull = sum(i["active"] for i in bull)
    n_bear = sum(i["active"] for i in bear)
    side = "pro pokles" if n_bear > n_bull else "pro růst" if n_bull > n_bear else "vyrovnaně"
    head = f"Teď platí {n_bear} podmínek pro pokles a {n_bull} pro růst ({side})."
    if events:
        e = events[0]
        head += f" Nejbližší rozhodující událost: {e['name']} ({_cz_date(e['date'])})."
    return {"headline": head, "bull": bull, "bear": bear, "events": events, "levels": levels,
            "active_bull": n_bull, "active_bear": n_bear}


def _cz_date(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.day}. {d.month}."
