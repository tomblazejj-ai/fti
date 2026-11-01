"""COT (Commitments of Traders) read for a swing trader — pure functions.

What the numbers mean, in the order the UI shows them:
  * spec_net  — large speculators' (funds) net long contracts on COMEX gold
  * COT index — where today's spec_net sits between its 3-year min (0) and
                max (100). ≥ 80 = funds are crowded long (little fuel left,
                prone to liquidation); ≤ 20 = funds are light (room to buy).
  * 1w / 4w change — are funds adding or cutting right now (flow).

Signal for the verdict (−1…+1) = flow (60 %) + contrarian extreme (40 %).
Report is as of Tuesday and published Friday — always ~3–10 days old.
"""

from __future__ import annotations

import datetime as dt
import statistics
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")

GROUPS = [  # key in history rows, Czech label, who they are
    ("spec_net", "Hedgeové fondy (managed money)", "Spekulují na směr — jejich nákupy a prodeje hýbou cenou nejvíc."),
    ("swap_net", "Banky a swap dealeři", "Zajišťují obchody klientů; bývají short, když fondy nakupují."),
    ("prod_net", "Producenti a zpracovatelé", "Těžaři a rafinérie zajišťují budoucí prodej — strukturálně short."),
    ("other_net", "Ostatní velcí obchodníci", "Velké firmy a family offices mimo předchozí skupiny."),
    ("small_net", "Malí obchodníci", "Pozice pod hranicí hlášení — retail."),
]


def schedule(as_of: str, now: dt.datetime) -> dict:
    """CFTC publishes Tuesday's positions on Friday 15:30 New York time
    (holidays shift it by a day or two — hence "obvykle")."""
    tue = dt.date.fromisoformat(as_of)
    def release(d: dt.date) -> dt.datetime:
        return dt.datetime(d.year, d.month, d.day, 15, 30, tzinfo=NEW_YORK).astimezone(dt.timezone.utc)
    published = release(tue + dt.timedelta(days=3))
    nxt = release(tue + dt.timedelta(days=10))
    late = now > nxt + dt.timedelta(days=2)
    return {
        "published": published.isoformat(),
        "next_release": nxt.isoformat(),
        "next_data_date": (tue + dt.timedelta(days=7)).isoformat(),
        "late": late,
    }


def _fmt(n: float) -> str:
    s = f"{abs(n):,.0f}".replace(",", " ")
    return ("−" if n < 0 else "+") + s


def cot_index(values: list[float]) -> float | None:
    lo, hi = min(values), max(values)
    if hi == lo:
        return None
    return (values[-1] - lo) / (hi - lo) * 100.0


def analyze(history: list[dict], now: dt.datetime | None = None, source: str = "legacy") -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    net = [r["spec_net"] for r in history]
    last = history[-1]
    ch1 = net[-1] - net[-2] if len(net) >= 2 else 0.0
    ch4 = net[-1] - net[-5] if len(net) >= 5 else ch1
    idx3 = cot_index(net[-156:])
    idx1 = cot_index(net[-52:])

    four_week_moves = [net[i] - net[i - 4] for i in range(4, len(net))]
    typical = statistics.pstdev(four_week_moves) if len(four_week_moves) > 5 else abs(ch4) or 1.0
    flow = max(-1.0, min(1.0, ch4 / (typical or 1.0)))

    if idx3 is None:
        extreme, contrarian = "neutral", 0.0
    elif idx3 >= 80:
        extreme, contrarian = "crowded_long", -1.0
    elif idx3 <= 20:
        extreme, contrarian = "light", 1.0
    else:
        extreme, contrarian = "neutral", 0.0
    signal = max(-1.0, min(1.0, 0.6 * flow + 0.4 * contrarian))

    flow_text = (
        f"Fondy za poslední 4 týdny {'přikupují' if ch4 > 0 else 'prodávají'} "
        f"({_fmt(ch4)} kontraktů, za týden {_fmt(ch1)})."
    ) if ch4 != 0 else "Fondy za poslední 4 týdny pozice téměř nemění."
    if extreme == "crowded_long":
        extreme_text = (f"COT index {idx3:.0f}/100: fondy jsou blízko 3letého maxima long pozic — trh je „přeplněný“, "
                        "při špatné zprávě hrozí rychlé vybírání zisků.")
    elif extreme == "light":
        extreme_text = (f"COT index {idx3:.0f}/100: fondy mají nejméně long pozic za 3 roky — je z čeho nakupovat, "
                        "často to bývá blízko dna.")
    else:
        extreme_text = f"COT index {idx3:.0f}/100: pozice fondů nejsou extrémní." if idx3 is not None else "COT index nelze spočítat."

    if signal > 0.2:
        verdict_text = "Pozice fondů mluví spíše pro růst zlata."
    elif signal < -0.2:
        verdict_text = "Pozice fondů mluví spíše pro pokles zlata."
    else:
        verdict_text = "Pozice fondů teď jasný směr neukazují."

    commercials = _commercials(history)
    open_interest = _open_interest(history)

    groups = []
    for key, label, who in GROUPS:
        if key not in last:
            continue
        series = [r[key] for r in history if key in r]
        prefix = "spec" if key == "spec_net" else key[:-4]
        groups.append({
            "key": key, "label": label, "who": who, "net": last[key],
            "long": last.get(f"{prefix}_long"), "short": last.get(f"{prefix}_short"),
            "change_1w": series[-1] - series[-2] if len(series) >= 2 else 0.0,
            "change_4w": series[-1] - series[-5] if len(series) >= 5 else 0.0,
            "index_3y": round(i, 1) if (i := cot_index(series[-156:])) is not None else None,
        })

    return {
        "source": source,
        "source_label": ("CFTC podrobný report (Disaggregated) — skupina „managed money“ = hedgeové fondy"
                         if source == "disaggregated" else "CFTC základní report (Legacy) — „non-commercial“ = velcí spekulanti"),
        "schedule": schedule(last["date"], now),
        "groups": groups,
        "spec_short_share": round(last["spec_short"] / last["open_interest"] * 100, 1) if last["open_interest"] else None,
        "long_short_ratio": round(last["spec_long"] / last["spec_short"], 1) if last["spec_short"] else None,
        "as_of": last["date"],
        "spec_net": last["spec_net"],
        "spec_long": last["spec_long"],
        "spec_short": last["spec_short"],
        "comm_net": last["comm_net"],
        "open_interest": last["open_interest"],
        "spec_long_share": round(last["spec_long"] / last["open_interest"] * 100, 1) if last["open_interest"] else None,
        "change_1w": ch1,
        "change_4w": ch4,
        "cot_index_3y": round(idx3, 1) if idx3 is not None else None,
        "cot_index_1y": round(idx1, 1) if idx1 is not None else None,
        "extreme": extreme,
        "signal": round(signal, 3),
        "texts": [verdict_text, flow_text, extreme_text],
        "history": [{"date": r["date"], "spec_net": r["spec_net"], "comm_net": r["comm_net"],
                     "spec_long": r["spec_long"], "spec_short": r["spec_short"], "open_interest": r["open_interest"]}
                    for r in history[-156:]],
        "commercials": commercials,
        "open_interest_view": open_interest,
    }


# Gold COT: the commercials (firms that use and hedge the metal) and the open interest.
COMM_EXTREME = 90.0
OI_MOVE_PCT = 3.0


def _cz1(v: float, signed: bool = False) -> str:
    s = f"{v:+.1f}" if signed else f"{v:.1f}"
    return s.replace(".", ",").replace("-", "−")


def _commercials(history: list[dict]) -> dict | None:
    comm = [r["comm_net"] for r in history if r.get("comm_net") is not None]
    if len(comm) < 30:
        return None
    idx = cot_index(comm[-156:])
    extreme = None if idx is None else "bullish" if idx >= COMM_EXTREME else "bearish" if idx <= 100 - COMM_EXTREME else None
    head = f"Commercials (producenti a banky, které zlato zajišťují) mají COT index {round(idx or 0)}/100."
    if extreme == "bullish":
        text = head + " Jsou nejméně short za 3 roky — v historii často signál pro růst zlata."
    elif extreme == "bearish":
        text = head + " Jsou nejvíc short za 3 roky — v historii často signál pro pokles zlata."
    else:
        text = head + " Bez extrému."
    return {"net": comm[-1], "change_4w": comm[-1] - comm[-5] if len(comm) >= 5 else None,
            "index_3y": round(idx, 1) if idx is not None else None, "extreme": extreme, "text": text}


def _open_interest(history: list[dict]) -> dict | None:
    oi = [r["open_interest"] for r in history if r.get("open_interest")]
    if len(oi) < 5:
        return None
    ch = (oi[-1] / oi[-5] - 1) * 100
    if ch >= OI_MOVE_PCT:
        state, text = "rising", f"Open interest za 4 týdny {_cz1(ch, True)} %: do trhu přitékají nové kontrakty — pohyb má palivo."
    elif ch <= -OI_MOVE_PCT:
        state, text = "falling", (f"Open interest za 4 týdny {_cz1(ch, True)} %: spíš se zavírají staré pozice — "
                                  "signál fondů je proto slabší.")
    else:
        state, text = "flat", f"Open interest za 4 týdny {_cz1(ch, True)} % — beze změny."
    return {"last": oi[-1], "change_4w_pct": round(ch, 1), "state": state, "text": text}


# --- Long / short split: how big a share of a group's positions
# is long vs. short, sudden changes within one report, extremes and divergence with price.
SHARP_CHANGE_PP = 8.0  # long share moved this much within ONE weekly report
EXTREME_INDEX = 90.0  # long share in the top / bottom 10 % of its 3-year range
DIVERGENCE_PP = 5.0  # 4-week change of the long share against the price move
DIVERGENCE_PRICE_PCT = {"gold": 2.0, "usd": 1.0}


def _cz(v: float, digits: int = 1, signed: bool = False) -> str:
    s = f"{v:+.{digits}f}" if signed else f"{v:.{digits}f}"
    return s.replace(".", ",").replace("-", "−")


def _price_on(prices: list[tuple[str, float]], day: str) -> float | None:
    best = None
    for d, v in prices:
        if d <= day:
            best = v
        else:
            break
    return best


def long_short_view(history: list[dict], long_key: str, short_key: str, prices: list[tuple[str, float]] | None = None,
                    asset: str = "gold", who: str = "Fondy") -> dict | None:
    """`prices`: (date, close) oldest first, used for the divergence check."""
    rows = [r for r in history if (r.get(long_key) or 0) + (r.get(short_key) or 0) > 0]
    if len(rows) < 10:
        return None
    pct = [r[long_key] / (r[long_key] + r[short_key]) * 100 for r in rows]
    last, ch1, ch4 = pct[-1], pct[-1] - pct[-2], pct[-1] - pct[-5]
    idx = cot_index(pct[-156:])
    flags = []
    if abs(ch1) >= SHARP_CHANGE_PP:
        flags.append({"kind": "sharp", "level": "warn",
                      "text": f"Prudká změna: {who.lower()} za jediný týden {'přidali' if ch1 > 0 else 'ubrali'} long podíl o "
                              f"{_cz(abs(ch1))} p.b. — velká změna v jednom reportu často stojí na začátku nového pohybu."})
    if idx is not None and idx >= EXTREME_INDEX:
        flags.append({"kind": "extreme_long", "level": "warn",
                      "text": f"Extrém: long podíl {last:.0f} % je u maxima za 3 roky — trh je přeplněný, roste riziko obratu dolů."})
    elif idx is not None and idx <= 100 - EXTREME_INDEX:
        flags.append({"kind": "extreme_short", "level": "warn",
                      "text": f"Extrém: long podíl {last:.0f} % je u minima za 3 roky — prodejci jsou vyčerpaní, roste riziko obratu nahoru."})
    if prices:
        p_now, p_then = _price_on(prices, rows[-1]["date"]), _price_on(prices, rows[-5]["date"])
        lim = DIVERGENCE_PRICE_PCT.get(asset, 2.0)
        if p_now and p_then:
            move = (p_now / p_then - 1) * 100
            if move >= lim and ch4 <= -DIVERGENCE_PP:
                flags.append({"kind": "divergence", "level": "warn",
                              "text": f"Divergence: cena za 4 týdny {_cz(move, 1, True)} %, ale {who.lower()} long podíl snížili o {_cz(abs(ch4))} p.b. "
                                      "— růst nemá oporu v pozicích, varování."})
            elif move <= -lim and ch4 >= DIVERGENCE_PP:
                flags.append({"kind": "divergence", "level": "warn",
                              "text": f"Divergence: cena za 4 týdny {_cz(move, 1, True)} %, ale {who.lower()} long podíl zvýšili o {_cz(ch4)} p.b. "
                                      "— pokles nemá oporu v pozicích, varování."})
    return {
        "long_pct": round(last, 1),
        "short_pct": round(100 - last, 1),
        "change_1w": round(ch1, 1),
        "change_4w": round(ch4, 1),
        "index_3y": round(idx, 1) if idx is not None else None,
        "as_of": rows[-1]["date"],
        "flags": flags,
        "history": [{"date": r["date"], "long_pct": round(p, 1)} for r, p in zip(rows[-156:], pct[-156:])],
    }


USD_GROUPS = [
    ("lev", "Hedgeové fondy (leveraged funds)", "Spekulují na směr dolaru — nejsledovanější skupina u měn."),
    ("am", "Správci aktiv (asset managers)", "Penzijní a investiční fondy — pomalejší, dlouhodobé pozice."),
    ("dealer", "Banky a dealeři", "Protistrana klientů; obvykle stojí proti fondům."),
    ("small", "Malí obchodníci", "Pozice pod hranicí hlášení — retail."),
]


def analyze_usd(history: list[dict], dxy_daily: list[tuple[str, float]] | None, now: dt.datetime) -> dict | None:
    """US Dollar Index futures (ICE), CFTC Traders in Financial Futures."""
    if len(history) < 10:
        return None
    last = history[-1]
    lev = long_short_view(history, "lev_long", "lev_short", dxy_daily, asset="usd", who="Fondy")
    groups = []
    for key, label, who in USD_GROUPS:
        net = [r[f"{key}_long"] - r[f"{key}_short"] for r in history]
        groups.append({"key": key, "label": label, "who": who, "long": last[f"{key}_long"], "short": last[f"{key}_short"],
                       "net": net[-1], "change_1w": net[-1] - net[-2], "change_4w": net[-1] - net[-5],
                       "index_3y": round(i, 1) if (i := cot_index(net[-156:])) is not None else None})
    if lev:
        p = lev["long_pct"]
        lean = ("fondy sázejí na silnější dolar" if p >= 60 else "fondy sázejí na slabší dolar" if p <= 40
                else "fondy nemají v dolaru výrazný směr")
        text = (f"Hedgeové fondy jsou v dolaru {_cz(p, 0)} % long a {_cz(100 - p, 0)} % short — {lean}. "
                f"Za 4 týdny {_cz(lev['change_4w'], 1, True)} p.b.")
        effect = ("Pro zlato to znamená tlak dolů (silný dolar)." if p >= 60 else "Pro zlato to znamená podporu (slabý dolar)." if p <= 40
                  else "Na zlato to teď výrazně netlačí.")
    else:
        text, effect = "Rozdělení pozic fondů nelze spočítat.", ""
    return {
        "source_label": "CFTC Traders in Financial Futures — US Dollar Index (ICE), skupina „leveraged funds“ = hedgeové fondy",
        "schedule": schedule(last["date"], now),
        "as_of": last["date"],
        "open_interest": last["open_interest"],
        "leveraged": lev,
        "groups": groups,
        "texts": [t for t in (text, effect) if t],
    }
