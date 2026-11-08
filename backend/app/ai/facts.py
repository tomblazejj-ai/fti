"""The facts packet — the only thing the AI ever sees.

Every fact has an id (F1, F2 …), a value, its source and its date, all taken from what FTI's
deterministic engine has already computed (the latest overview of the ingestion cycle) or from the
central price layer. The AI gets nothing else, so it has nothing to invent from. Facts marked
volatile (the live price) are left out of the dedup hash, so a ticking price does not trigger a
new AI request.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.news import timebasis

ENGINE = "výpočet FTI"
NEWS_SNIPPET = 400  # characters of the RSS snippet, never the full article (copyright)


class NotReady(RuntimeError):
    """The engine has not produced the inputs this task needs (yet)."""


class Packet:
    def __init__(self):
        self.facts: list[dict] = []

    def add(self, what: str, value, source: str = ENGINE, as_of=None, text: str | None = None, volatile: bool = False,
            section: str | None = None) -> str:
        fid = f"F{len(self.facts) + 1}"
        fact = {"id": fid, "co": what, "hodnota": value, "zdroj": source or ENGINE}
        if section:
            fact["oblast"] = section
        if as_of:
            fact["k"] = as_of.isoformat() if isinstance(as_of, dt.datetime) else str(as_of)
        if text:
            fact["text"] = text
        if volatile:
            fact["volatile"] = True
        self.facts.append(fact)
        return fid

    def add_news(self, what: str, item: dict, source: str | None = None, section: str | None = None) -> str:
        """A headline with its time and where that time comes from: the source's publication time, GDELT's
        capture time or FTI's fetch time — the AI must never take the last two for a publication time. A
        machine-translated headline goes in as its original (the translation may lose a number)."""
        translated = bool(item.get("translated") and item.get("title_en"))
        fid = self.add(what, item["title_en"] if translated else item["title"], source=source or item.get("source"),
                       as_of=item.get("published_at"), text="originál titulku (FTI ho zobrazuje ve strojovém překladu)" if translated else None,
                       section=section)
        self.facts[-1]["puvod_casu"] = timebasis.origin_ai(item.get("time_basis"))
        return fid


def latest_overview(session) -> tuple[dict, str]:
    """The newest engine overview (what the Markets page shows) and when it was computed."""
    from app.models import AnalysisSnapshot, Instrument

    inst = session.scalar(select(Instrument).where(Instrument.code == "XAUUSD"))
    row = session.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.instrument_id == inst.id)
                         .order_by(AnalysisSnapshot.computed_at.desc())) if inst else None
    if row is None or not (row.payload or {}).get("markets"):
        raise NotReady("Přehled trhů se ještě počítá — AI nemá z čeho vycházet.")
    return row.payload, row.computed_at.isoformat()


def market_card(overview: dict, code: str) -> dict:
    card = next((m for m in overview["markets"].get("markets", []) if m["code"] == code.upper()), None)
    if card is None:
        raise NotReady(f"{code} v přehledu trhů není — engine pro něj skóre nepočítá.")
    return card


def _quote_facts(p: Packet, code: str, quote_fn, section: str | None = None) -> None:
    try:
        q = quote_fn(code)
    except Exception:  # noqa: BLE001 — the price is context, never a reason to fail
        q = None
    if not q or not q.get("available"):
        p.add("Aktuální cena", "nedostupná", source="centrální cenová vrstva FTI",
              text="Pro tento instrument teď není ověřená kotace — AI nesmí žádnou cenu uvádět.", volatile=True, section=section)
        return
    lq = q.get("last_quote") or {}
    label = (q.get("quality") or {}).get("label") or ""
    kind = ("referenční hodnota, ne cena trhu" if q.get("reference") else "proxy, ne samotný instrument" if q.get("proxy")
            else "orientační cena bez času kotace, ne živá kotace" if q.get("indicative") else "kotace")
    p.add("Poslední cena", q["price"], source=f"{q.get('source')} ({kind})", as_of=lq.get("time"),
          text=f"Stav: {label}. Čas kotace: {lq.get('time_cs')}.", volatile=True, section=section)


def market(session, code: str, quote_fn=None) -> tuple[list[dict], dict]:
    """Facts for one instrument: fundamental score and BIAS with every component, what speaks for and
    against, retail positioning, upcoming events, latest headlines and the live price."""
    from app.data import prices

    overview, computed_at = latest_overview(session)
    card = market_card(overview, code)
    p = Packet()
    p.add("Instrument", f"{card['code']} — {card['name']} ({card['subtitle']})")
    p.add("Fundamentální skóre", card["score10"], as_of=computed_at, text="Rozsah −10 až +10.")
    p.add("Fundamentální BIAS", card["bias"], as_of=computed_at, text=card.get("word"))
    if card.get("possible"):
        p.add("Součet kategorií modelu", card.get("raw"), as_of=computed_at, text=f"z možných ±{card['possible']}")
    for c in card.get("components") or []:
        p.add(f"Složka skóre: {c['label']}", c.get("score"), text=f"{c.get('text') or ''} (rozsah ±{c.get('max')}) "
              + "; ".join(c.get("details") or []))
    if card.get("missing"):
        p.add("Chybějící složky modelu", ", ".join(card["missing"]))
    if card.get("trend"):
        p.add("Trend", card["trend"])
    r = card.get("retail") or {}
    if r.get("long_pct") is not None:
        p.add("Malí obchodníci long (CFTC COT)", r["long_pct"], source="CFTC", as_of=r.get("as_of"),
              text=f"Změna za 4 týdny: {r.get('change_4w')} p. b. {r.get('head') or ''}")
    for e in (card.get("watch") or [])[:5]:
        p.add(f"Událost v kalendáři: {e['title']}", e.get("impact_text"), source="ekonomický kalendář", as_of=e.get("datetime"),
              text=f"Měna {e.get('currency')}, očekávání {e.get('forecast')}, minule {e.get('previous')}.")
    for n in (card.get("news") or [])[:4]:
        p.add_news("Titulek zprávy", n)
    for n in (card.get("technical") or [])[:2]:
        p.add_news("Technický výhled veřejného portálu (článek, ne výpočet FTI)", n)
    _quote_facts(p, card["code"], quote_fn or prices.quote)
    return p.facts, {"engine_computed_at": computed_at, "instrument": card["code"]}


def news(session, item_id: int) -> tuple[list[dict], dict]:
    """Facts for one news item: its headline, the start of the RSS snippet, source, time and what
    FTI's rule-based classifier already found (tags, sentiment, instruments)."""
    from app.models import NewsItem

    item = session.get(NewsItem, item_id)
    if item is None:
        raise NotReady("Zpráva v databázi není.")
    p = Packet()
    p.add_news("Titulek (originál)", {"title": item.title, "source": item.source, "published_at": item.published_at,
                                      "time_basis": item.time_basis})
    from app.news.translate import shown_title

    shown, translated, _ = shown_title(item.title, item.title_cs, item.language)
    if translated:  # only a translation whose numbers match the original
        p.add("Titulek česky (strojový překlad)", shown, source="překlad FTI")
    snippet = (item.raw_snippet or "").strip()
    if snippet:
        p.add("Úryvek z RSS", snippet[:NEWS_SNIPPET], source=item.source)
    p.add("Klasifikace FTI — témata", ", ".join(item.factor_tags or []) or "žádná", source="pravidla FTI")
    p.add("Klasifikace FTI — nálada", item.sentiment, source="pravidla FTI")
    p.add("Klasifikace FTI — instrumenty", ", ".join(item.instrument_tags or []) or "žádné", source="pravidla FTI")
    return p.facts, {"item_id": item.id, "instrument": (item.instrument_tags or [None])[0]}


def report(session) -> tuple[list[dict], dict]:
    """Facts for a briefing across all instruments of the overview."""
    overview, computed_at = latest_overview(session)
    m = overview["markets"]
    p = Packet()
    for card in m.get("markets", []):
        p.add(f"{card['code']}: fundamentální skóre a BIAS", card["score10"], as_of=computed_at,
              text=f"{card['bias']} — {card.get('word')}")
        for a in (card.get("for") or [])[:2]:
            p.add(f"{card['code']}: podporuje BIAS — {a['label']}", a.get("score"), text=a.get("text"))
        for a in (card.get("against") or [])[:2]:
            p.add(f"{card['code']}: proti BIAS — {a['label']}", a.get("score"), text=a.get("text"))
    for e in (m.get("next_events") or [])[:5]:
        p.add(f"Důležitá událost: {e['title']}", e.get("when"), source="ekonomický kalendář", as_of=e.get("datetime"),
              text=f"Měna {e.get('currency')}, očekávání {e.get('forecast')}, minule {e.get('previous')}.")
    for h in (m.get("highlights") or [])[:5]:
        p.add_news(f"Zpráva ({h.get('market')})", h)
    return p.facts, {"engine_computed_at": computed_at}


def change(card_now: dict, card_before: dict, computed_at: str, before_at: str) -> tuple[list[dict], dict]:
    """Facts for a significant change between two engine overviews of one instrument."""
    p = Packet()
    p.add("Instrument", f"{card_now['code']} — {card_now['name']}")
    p.add("Fundamentální skóre dříve", card_before["score10"], as_of=before_at)
    p.add("Fundamentální skóre nyní", card_now["score10"], as_of=computed_at)
    p.add("BIAS dříve", card_before["bias"], as_of=before_at)
    p.add("BIAS nyní", card_now["bias"], as_of=computed_at, text=card_now.get("word"))
    before = {c["key"]: c for c in card_before.get("components") or []}
    for c in card_now.get("components") or []:
        old = before.get(c["key"])
        if old and old.get("score") != c.get("score"):
            p.add(f"Změna složky: {c['label']}", c.get("score"), as_of=computed_at,
                  text=f"dříve {old.get('score')}, nyní {c.get('score')} (rozsah ±{c.get('max')}). {c.get('text') or ''}")
    for e in (card_now.get("watch") or [])[:3]:
        p.add(f"Událost v kalendáři: {e['title']}", e.get("impact_text"), source="ekonomický kalendář", as_of=e.get("datetime"))
    return p.facts, {"engine_computed_at": computed_at, "instrument": card_now["code"]}
