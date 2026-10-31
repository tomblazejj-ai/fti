"""Fundamental score of crude oil (WTI), −10 … +10.

    category             range   from
    Zásoby ropy (EIA)     ±3     4-week change of US crude stocks + stocks vs. their 5-year average for the week
    COT – fondy           ±2     managed money in NYMEX WTI: crowding (3-year index) + 4-week flow
    Sezónnost             ±2     same calendar days in the last 10 years (daily WTI, FRED)
    Dolar                 ±1     swing trend of the dollar index — a stronger dollar weighs on oil
    Poptávka (USA)        ±1     Chicago Fed activity index, 3-month average
    Riziko nabídky        ±1     war / sanctions / attack headlines about producers in the last 48 h

Positive = supportive for oil prices. Fixed thresholds, nothing estimated.
"""

from __future__ import annotations

import datetime as dt
import re
import statistics

from app.market.fx_model import _clip, _num, finish

RANGES = {"stocks": 3, "cot": 2, "season": 2, "usd": 1, "demand": 1, "supply_risk": 1}
LABELS = {"stocks": "Zásoby ropy (EIA)", "cot": "COT – fondy", "season": "Sezónnost", "usd": "Dolar",
          "demand": "Poptávka (USA)", "supply_risk": "Riziko nabídky"}
SUPPLY_RX = re.compile(
    r"\b(iran|iraq|saudi|opec|russia|venezuela|libya|hormuz|red sea|houthi|middle east|pipeline|refinery|oil field|tanker)\w*\b.*"
    r"\b(attack|strike|war|sanction|missile|drone|blockade|seiz|outage|halt|shut)\w*|"
    r"\b(attack|strike|war|sanction|missile|drone|blockade|seiz|outage|halt|shut)\w*\b.*"
    r"\b(iran|iraq|saudi|opec|russia|venezuela|libya|hormuz|red sea|houthi|pipeline|refinery|oil field|tanker)\w*", re.IGNORECASE)


def _c(key: str, score: int | None, text: str) -> dict:
    return {"key": key, "label": LABELS[key], "score": score, "max": RANGES[key], "text": text, "details": []}


def stocks_component(stocks: dict[str, float] | None) -> dict:
    if not stocks or len(stocks) < 300:
        return _c("stocks", None, "Týdenní zásoby EIA nejsou k dispozici.")
    days = sorted(stocks)
    last_day, last = days[-1], stocks[days[-1]]
    four = stocks[days[-5]]
    ch = (last - four) / 1000  # million barrels
    pts = 2 if ch <= -8 else 1 if ch <= -3 else -2 if ch >= 8 else -1 if ch >= 3 else 0
    # the same week in the previous 5 years (±4 days)
    d = dt.date.fromisoformat(last_day)
    past = []
    for k in range(1, 6):
        target = d.replace(year=d.year - k)
        near = [x for x in days if abs((dt.date.fromisoformat(x) - target).days) <= 4]
        if near:
            past.append(stocks[near[0]])
    vs = None
    if len(past) >= 4:
        avg = statistics.mean(past)
        vs = (last / avg - 1) * 100
        pts += 1 if vs <= -5 else -1 if vs >= 5 else 0
    word = "ubývají" if ch < 0 else "přibývají"
    text = (f"Zásoby ropy v USA {_num(last / 1000, 1)} mil. barelů ({d.day}. {d.month}.), za 4 týdny {word} o "
            f"{_num(abs(ch), 1)} mil." + (f" Proti průměru 5 let {_num(vs, 1, True)} %." if vs is not None else "")
            + (" Úbytek zásob = podpora ceny." if pts > 0 else " Přebytek zásob tlačí cenu dolů." if pts < 0 else ""))
    return _c("stocks", _clip(pts, 3), text)


def cot_component(rows: list[dict] | None) -> dict:
    if not rows or len(rows) < 30:
        return _c("cot", None, "COT ropy chybí.")
    net = [r["spec_net"] for r in rows]
    lo, hi = min(net[-156:]), max(net[-156:])
    idx = (net[-1] - lo) / (hi - lo) * 100 if hi > lo else 50.0
    moves = [net[i] - net[i - 4] for i in range(4, len(net))]
    sd = statistics.pstdev(moves) or 1.0
    z = (net[-1] - net[-5]) / sd
    level = -1 if idx >= 90 else 1 if idx <= 10 else 0
    flow = 1 if z >= 0.5 else -1 if z <= -0.5 else 0
    word = "přikupují" if flow > 0 else "prodávají" if flow < 0 else "pozice nemění"
    text = f"Fondy v ropě: COT index {_num(idx, 0)}/100, za 4 týdny {word}" + (
        " (extrém — riziko obratu)." if level else ".")
    return _c("cot", _clip(level + flow, 2), text)


def season_component(view: dict | None) -> dict:
    if not view or not view.get("next30"):
        return _c("season", None, "Málo historie pro sezónnost.")
    n = view["next30"]
    lean = view.get("lean", 0)
    strong = n["avg"] >= 2 and n["win"] >= 70 or n["avg"] <= -2 and n["win"] <= 30
    s = lean * (2 if strong else 1)
    text = f"Příštích 30 dní: ropa rostla v {n['up']} z {n['n']} let, průměr {_num(n['avg'], 1, True)} %."
    if view.get("texts"):
        text += " " + view["texts"][0]
    return _c("season", s, text)


def usd_component(dxy_swing: dict | None) -> dict:
    if not dxy_swing:
        return _c("usd", None, "Trend dolaru není k dispozici.")
    lean = dxy_swing.get("lean")
    s = -1 if lean == "up" else 1 if lean == "down" else 0
    word = {"up": "posiluje — ropa v dolarech zdražuje pro zbytek světa, tlak dolů",
            "down": "slábne — podpora pro ropu"}.get(lean, "nemá jasný směr")
    return _c("usd", s, f"Dolar (DXY) swingově {word}.")


def demand_component(cfnai: dict[str, float] | None) -> dict:
    if not cfnai or len(cfnai) < 3:
        return _c("demand", None, "Index aktivity USA chybí.")
    vals = [cfnai[d] for d in sorted(cfnai)][-3:]
    m = statistics.mean(vals)
    s = 1 if m >= 0.2 else -1 if m <= -0.35 else 0
    word = "nad trendem" if s > 0 else "pod trendem" if s < 0 else "kolem trendu"
    return _c("demand", s, f"Ekonomická aktivita USA (Chicago Fed, 3 měsíce) {_num(m, 2, True)} — {word}.")


def supply_risk_component(headlines: list[dict], now: dt.datetime) -> dict:
    cutoff = now - dt.timedelta(hours=48)
    hits = []
    for h in headlines:
        try:
            if dt.datetime.fromisoformat(h["published_at"]) < cutoff:
                continue
        except (KeyError, ValueError):
            continue
        if SUPPLY_RX.search(f"{h.get('title_en') or ''} {h.get('title') or ''}"):
            hits.append(h)
    s = 1 if len(hits) >= 2 else 0
    n = len(hits)
    word = "zprávy" if 2 <= n <= 4 else "zpráv"
    text = (f"Za 48 h {n} {word} o útocích, sankcích nebo výpadcích u producentů — riziko nabídky drží cenu nahoře."
            if s else "Žádné výrazné zprávy o ohrožení nabídky za 48 h.")
    return _c("supply_risk", s, text)


def score(stocks, cot_rows, season_view, dxy_swing, cfnai, headlines, now) -> dict:
    return finish([stocks_component(stocks), cot_component(cot_rows), season_component(season_view),
                   usd_component(dxy_swing), demand_component(cfnai), supply_risk_component(headlines, now)])
