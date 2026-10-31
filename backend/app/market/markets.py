"""Market overview: one card + detail per instrument (Market Intelligence style).

For each instrument: fundamental score −10 … +10 with bias, what supports the direction,
what speaks against it, what to watch next (calendar), retail positioning (CFTC small
traders, contrarian), COT, seasonality and trend. Gold keeps the full Funded Mind score
(±25, scaled to ±10 here) and its trading plan.
"""

from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

from app.market import fx_model, oil_model

PRAGUE = ZoneInfo("Europe/Prague")

INSTRUMENTS = [
    {"code": "XAUUSD", "name": "XAU/USD", "subtitle": "Zlato / americký dolar", "kind": "gold", "currencies": ["USD"], "digits": 2},
    {"code": "EURUSD", "name": "EUR/USD", "subtitle": "Euro / americký dolar", "kind": "fx", "base": "EUR", "quote": "USD",
     "currencies": ["EUR", "USD"], "digits": 5},
    {"code": "GBPUSD", "name": "GBP/USD", "subtitle": "Britská libra / americký dolar", "kind": "fx", "base": "GBP", "quote": "USD",
     "currencies": ["GBP", "USD"], "digits": 5},
    {"code": "USDJPY", "name": "USD/JPY", "subtitle": "Americký dolar / japonský jen", "kind": "fx", "base": "USD", "quote": "JPY",
     "currencies": ["USD", "JPY"], "digits": 3},
    {"code": "USOIL", "name": "USOIL", "subtitle": "Ropa WTI", "kind": "oil", "currencies": ["USD"], "digits": 2},
]
BY_CODE = {i["code"]: i for i in INSTRUMENTS}

# Which headlines belong to which instrument (title in English + Czech translation).
NEWS_TAGS = {
    "XAUUSD": r"\bgold\b|\bbullion\b|\bxau\b|\bzlat",
    "EURUSD": r"\beuro\b|\becb\b|\blagarde\b|\beurozone\b|\beuro area\b|\beur/usd\b|\beurusd\b|\bgerman|\bECB\b|\beurozón",
    "GBPUSD": r"\bpound\b|\bsterling\b|\bboe\b|\bbank of england\b|\bbailey\b|\bgbp\b|\bbritain\b|\buk\b|\blibr",
    "USDJPY": r"\byen\b|\bboj\b|\bbank of japan\b|\bueda\b|\bjapan|\bjpy\b|\bjaponsk",
    "USOIL": r"\boil\b|\bcrude\b|\bopec\b|\bwti\b|\bbrent\b|\bropa\b|\bropy\b",
}
USD_NEWS = r"\bfed\b|\bfomc\b|\bpowell\b|\bdollar\b|\btreasur|\binflation\b|\bpayrolls?\b|\bdolar"


def _num(v: float, digits: int = 1, signed: bool = False) -> str:
    return fx_model._num(v, digits, signed)


def _arguments(comps: list[dict], bias: str) -> tuple[list[dict], list[dict]]:
    """(supporting, against) — relative to the bias; for a neutral score positives vs. negatives."""
    pos = sorted((c for c in comps if (c["score"] or 0) > 0), key=lambda c: -c["score"])
    neg = sorted((c for c in comps if (c["score"] or 0) < 0), key=lambda c: c["score"])
    pick = (lambda c: {"label": c["label"], "text": c["text"], "score": c["score"]})
    if bias == "SHORT":
        return [pick(c) for c in neg], [pick(c) for c in pos]
    return [pick(c) for c in pos], [pick(c) for c in neg]


def _impact_text(e: dict) -> str:
    return {3: "Vysoký dopad", 2: "Střední dopad", 1: "Nízký dopad"}.get(e["impact"], "Dopad") + f" na {e['currency']}"


def _when(iso: str, timed: bool = True) -> str:
    t = dt.datetime.fromisoformat(iso).astimezone(PRAGUE)
    day = ["po", "út", "st", "čt", "pá", "so", "ne"][t.weekday()]
    return f"{day} {t.day}. {t.month}." + (f" {t:%H:%M}" if timed else "")


def watch_list(events: list[dict], currencies: list[str], now: dt.datetime, days: int = 8, extra: str | None = None) -> list[dict]:
    out = []
    end = now + dt.timedelta(days=days)
    seen = set()
    for e in sorted(events, key=lambda x: x["datetime"]):
        t = dt.datetime.fromisoformat(e["datetime"])
        if not (now - dt.timedelta(hours=1) <= t <= end) or e["impact"] < 2 or e["currency"] not in currencies:
            continue
        if extra and e["currency"] == "USD" and not (e["impact"] == 3 or re.search(extra, e["title_en"], re.IGNORECASE)):
            continue
        key = (e["currency"], (e.get("title_cs") or e["title_en"])[:24], t.date())
        if key in seen:
            continue
        seen.add(key)
        out.append({"when": _when(e["datetime"], e.get("timed", True)), "datetime": e["datetime"], "currency": e["currency"],
                    "title": e.get("title_cs") or e["title_en"], "impact": e["impact"], "impact_text": _impact_text(e),
                    "forecast": e.get("forecast"), "previous": e.get("previous")})
    return out[:6]


def _change_text(watch: list[dict], code: str) -> str:
    reds = [w for w in watch if w["impact"] == 3][:3] or watch[:3]
    if not reds:
        return "V příštích dnech není v kalendáři žádná zásadní událost — výhled se mění hlavně s novými daty a zprávami."
    names = ", ".join(f"{w['title']} ({w['when']})" for w in reds)
    return f"{names} — tyhle události mohou výhled pro {BY_CODE[code]['name']} změnit."


def retail_view(long_pct: float | None, change_4w: float | None, as_of: str | None, bias: str, invert: bool = False) -> dict | None:
    if long_pct is None:
        return None
    lp = 100 - long_pct if invert else long_pct
    sp = 100 - lp
    if lp >= 60 and bias == "SHORT":
        head, text = "Sentiment podporuje SHORT bias.", (f"Zatímco {_num(lp, 0)} % malých obchodníků je long, fundamentální skóre ukazuje "
                                                         "na pokles. Tento kontrast může medvědí scénář dále podpořit.")
        tone = "support"
    elif sp >= 60 and bias == "LONG":
        head, text = "Sentiment podporuje LONG bias.", (f"Zatímco {_num(sp, 0)} % malých obchodníků je short, fundamentální skóre ukazuje "
                                                        "na růst. Tento kontrast může býčí scénář dále podpořit.")
        tone = "support"
    elif (lp >= 60 and bias == "LONG") or (sp >= 60 and bias == "SHORT"):
        head, text = "Pozor — retail je na stejné straně.", ("Většina malých obchodníků sází stejným směrem jako fundament. Kontrariánsky "
                                                              "to výhled spíš oslabuje.")
        tone = "warn"
    else:
        head, text = "Retail není výrazně na jedné straně.", "Sentiment malých obchodníků teď výhled nepotvrzuje ani nevyvrací."
        tone = "neutral"
    return {"long_pct": round(lp, 1), "short_pct": round(sp, 1), "change_4w": change_4w, "as_of": as_of, "head": head, "text": text,
            "tone": tone, "source": "Malí obchodníci (non-reportable) z CFTC COT — brokerská data o retailu zdarma bez registrace nejsou."}


def small_traders(rows: list[dict] | None, long_key: str = "small_long", short_key: str = "small_short") -> tuple[float | None, float | None, str | None]:
    if not rows:
        return None, None, None
    pct = [r[long_key] / (r[long_key] + r[short_key]) * 100 for r in rows if (r.get(long_key) or 0) + (r.get(short_key) or 0)]
    if len(pct) < 5:
        return None, None, None
    return pct[-1], round(pct[-1] - pct[-5], 1), rows[-1]["date"]


def instrument_news(headlines: list[dict], code: str, limit: int = 5) -> list[dict]:
    rx = re.compile(NEWS_TAGS[code] + ("|" + USD_NEWS if code != "USOIL" else ""), re.IGNORECASE)
    own = re.compile(NEWS_TAGS[code], re.IGNORECASE)
    hits = []
    for h in headlines:
        text = f"{h.get('title_en') or ''} {h.get('title') or ''}"
        if rx.search(text):
            hits.append((0 if own.search(text) else 1, h))
    ordered = [h for _, h in sorted(hits, key=lambda x: (x[0], -dt.datetime.fromisoformat(x[1]["published_at"]).timestamp()))]
    return [{k: h.get(k) for k in ("title", "source", "url", "published_at", "translated")} for h in ordered[:limit]]


def card(inst: dict, result: dict, price: dict | None, trend: str | None, extra: dict | None = None) -> dict:
    for_args, against = _arguments(result["components"], result["bias"])
    return {
        "code": inst["code"], "name": inst["name"], "subtitle": inst["subtitle"], "kind": inst["kind"], "digits": inst["digits"],
        "score10": result["score10"], "word": result["word"], "bias": result["bias"], "raw": result["raw"], "possible": result["possible"],
        "components": result["components"], "missing": result["missing"], "for": for_args, "against": against,
        "price": price, "trend": trend, **(extra or {}),
    }


def gold_result(tra: dict | None) -> dict | None:
    """The Funded Mind score (±25) in the same shape as the FX/oil results, scaled to ±10."""
    xau = (tra or {}).get("xau")
    if not xau:
        return None
    comps = [{"key": c["key"], "label": c["label"], "score": c["score"], "max": c["max"], "text": c["reason"], "details": []}
             for c in xau["components"]]
    have = [c for c in comps if c["score"] is not None]
    possible = sum(c["max"] for c in have)
    score10 = round(xau["total"] / possible * 10) if possible else 0
    return {"components": comps, "raw": xau["total"], "possible": possible, "score10": max(-10, min(10, score10)),
            "missing": xau["missing"], **fx_model.verdict(score10)}


def build(ctx: dict, now: dt.datetime) -> dict:
    """ctx: currencies {code: CurrencyData}, tff {code: rows}, crude_cot, gold_cot, seasons {code: daily view}, tra,
    stocks, cfnai, dxy_swing, headlines, events, prices {code: {...}}, trends {code: word}, gold_extra."""
    cards = []
    for inst in INSTRUMENTS:
        code = inst["code"]
        try:
            if inst["kind"] == "fx":
                base, quote = ctx["currencies"].get(inst["base"]), ctx["currencies"].get(inst["quote"])
                if not base or not quote:
                    continue
                fut = inst["base"] if inst["base"] != "USD" else inst["quote"]
                invert = inst["base"] == "USD"  # USD/JPY: the yen future is the other way round
                cot_label = {"EUR": "euru", "GBP": "libře", "JPY": "jenu"}[fut]
                res = fx_model.score_pair(base, quote, ctx["tff"].get(fut), invert, cot_label, ctx["seasons"].get(code), now)
                lp, ch, as_of = small_traders(ctx["tff"].get(fut))
                retail = retail_view(lp, (-ch if invert and ch is not None else ch), as_of, res["bias"], invert)
            elif inst["kind"] == "oil":
                res = oil_model.score(ctx.get("stocks"), ctx.get("crude_cot"), ctx["seasons"].get(code), ctx.get("dxy_swing"),
                                      ctx.get("cfnai"), ctx.get("headlines") or [], now)
                lp, ch, as_of = small_traders(ctx.get("crude_cot"))
                retail = retail_view(lp, ch, as_of, res["bias"])
            else:
                res = gold_result(ctx.get("tra"))
                if not res:
                    continue
                lp, ch, as_of = small_traders(ctx.get("gold_cot"))
                retail = retail_view(lp, ch, as_of, res["bias"])
        except Exception as exc:  # noqa: BLE001 — one market must never take the others down
            ctx.setdefault("errors", []).append(f"{code}: {exc}")
            continue
        watch = watch_list(ctx.get("events") or [], inst["currencies"], now, days=10,
                           extra=r"crude|oil|inventor" if inst["kind"] == "oil" else None)
        extra = {"retail": retail, "watch": watch, "change_text": _change_text(watch, code),
                 "news": instrument_news(ctx.get("headlines") or [], code)}
        if code == "XAUUSD" and ctx.get("gold_extra"):
            extra["gold"] = ctx["gold_extra"]
        cards.append(card(inst, res, (ctx.get("prices") or {}).get(code), (ctx.get("trends") or {}).get(code), extra))
    return {"computed_at": now.isoformat(), "markets": cards, "errors": ctx.get("errors", []),
            "method": ("Skóre −10 až +10 skládají pevná pravidla z oficiálních dat zdarma (ECB, ONS, FRED, MOF, EIA, CFTC). "
                       "Zlato používá skóre metodiky Funded Mind (±25) přepočtené na ±10. Není to investiční doporučení.")}
