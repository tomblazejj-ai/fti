"""The four news findings of 2026-11-07, each with the real cases that exposed it.

A  the AI gets every news time with its origin (publication / GDELT capture / FTI fetch)
B  an item with only FTI's fetch time (no publication time) never counts as fresh
C  the GDELT "gold" query keeps gold-market articles only — in any language
D  a machine translation that changes a number, currency, percentage or scale is never shown
"""

import datetime as dt

import httpx

from app.ai import facts, tasks
from app.connectors import gdelt
from app.ingestion import run_ingest
from app.market import headline_risk, markets, oil_model
from app.models import NewsItem
from app.news import grouping, relevance, timebasis, translate
from app.scoring import xauusd

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
REAL_TRANSLATE = translate.translate  # conftest replaces it with a stub; the tests of finding D need the real one


def _news(session, title, time_basis="published", hours_ago=1.0, factors=("geopolitics",), source="CNBC", **kw):
    n = NewsItem(source=source, dedup_hash=f"{title}{time_basis}{source}", title=title, url=f"https://x/{len(title)}{time_basis}",
                 published_at=NOW - dt.timedelta(hours=hours_ago), raw_snippet="", instrument_tags=kw.pop("tags", ["XAUUSD"]),
                 relevance_score=1.0, sentiment="bullish", sentiment_scores={f: 0.8 for f in factors}, factor_tags=list(factors),
                 time_basis=time_basis, language=kw.pop("language", "en"), title_cs=kw.pop("title_cs", None), **kw)
    session.add(n)
    session.commit()
    return n


def _headline(title, time_basis="published", minutes_ago=30, source="CNBC"):
    return {"title": title, "title_en": title, "source": source, "url": f"https://x/{title}",
            "published_at": (NOW - dt.timedelta(minutes=minutes_ago)).isoformat(), "time_basis": time_basis, "translated": False}


# --- A: the AI is told where each time comes from
def test_a_every_news_fact_carries_the_origin_of_its_time():
    p = facts.Packet()
    for basis in ("published", "gdelt_seen", "fetched", None):
        p.add_news("Titulek zprávy", {"title": f"t {basis}", "source": "s", "published_at": NOW.isoformat(), "time_basis": basis})
    origins = [f["puvod_casu"] for f in p.facts]
    assert origins[0] == "čas publikace uvedený zdrojem"
    assert "zachytil GDELT" in origins[1] and "čas publikace neuvádí" in origins[1]
    assert "stáhlo FTI" in origins[2] and "stáří je neznámé" in origins[2]
    assert "nepovažuj" in origins[3]  # an unknown origin is never presented as publication
    assert all(f["k"] == NOW.isoformat() for f in p.facts)  # the time itself is passed as it is, nothing invented


def test_a_the_ai_gets_the_original_headline_not_the_machine_translation():
    p = facts.Packet()
    p.add_news("Titulek zprávy", {"title": "Zlato za 3 dolary, 800 - 4 000", "title_en": "Gold at $3,800–4,000",
                                  "translated": True, "source": "s", "published_at": NOW.isoformat(), "time_basis": "gdelt_seen"})
    assert p.facts[0]["hodnota"] == "Gold at $3,800–4,000"
    assert "originál" in p.facts[0]["text"]


def test_a_news_task_facts_label_a_fetched_time(db_session):
    item = _news(db_session, "Gold outlook", time_basis="fetched", source="Investing.com technika")
    fs, _ = facts.news(db_session, item.id)
    title = next(f for f in fs if f["co"] == "Titulek (originál)")
    assert "stáhlo FTI" in title["puvod_casu"]
    assert "puvod_casu" in tasks.SYSTEM and "neuváděj jako čas publikace" in tasks.SYSTEM


# --- B: unknown age is never fresh
def test_b_headline_risk_ignores_a_headline_whose_age_is_unknown():
    war = "Missile strikes hit oil terminal"
    fresh = headline_risk.build([_headline(war, "published")], [], {"open": False}, NOW)
    assert fresh["level"] == 1 and fresh["unknown_age"] == 0
    unknown = headline_risk.build([_headline(war, "fetched")], [], {"open": False}, NOW)
    assert unknown["level"] == 0 and unknown["items"] == [] and unknown["unknown_age"] == 1
    assert "bez času publikace" in unknown["note"]
    # three fetched headlines from two sources within minutes are no "developing story"
    many = [_headline(f"{war} {i}", "fetched", 10, src) for i, src in enumerate(("A", "B", "C"))]
    assert headline_risk.build(many, [], {"open": False}, NOW)["cluster"] is False
    # fetched before the 12 h window: published even earlier — surely old, not "unknown"
    assert headline_risk.build([_headline(war, "fetched", 13 * 60)], [], {"open": False}, NOW)["unknown_age"] == 0


def test_b_gdelt_capture_time_still_counts_as_an_approximate_time():
    got = headline_risk.build([_headline("Sanctions on Iran tighten", "gdelt_seen")], [], {"open": False}, NOW)
    assert got["level"] == 1 and got["items"][0]["time_basis"] == "gdelt_seen"


def test_b_news_mood_and_key_news_leave_unknown_age_out(db_session):
    _news(db_session, "Fed signals pause", "published", 2, ("fed_tone",))
    _news(db_session, "Gold outlook from a feed without dates", "fetched", 0.1, ("fed_tone",))
    mood = run_ingest.news_mood(db_session, NOW)
    assert mood["count"] == 1 and mood["unknown_age"] == 1
    assert [n["title"] for n in mood["top"]] == ["Fed signals pause"]
    assert [n["title"] for n in mood["key"]] == ["Fed signals pause"]


def test_b_score_input_leaves_unknown_age_out_and_says_so(db_session, monkeypatch):
    monkeypatch.setattr(run_ingest.dt, "datetime", _FrozenDatetime)
    _news(db_session, "War escalates", "published", 2)
    _news(db_session, "Undated war story", "fetched", 0.1)
    sig = run_ingest._news_signal(db_session, "geopolitics")
    assert [p.description.split("“")[0] for p in sig.points] == ["„War escalates"] and sig.unknown_age == 1
    _, reasons, ids, _ = xauusd._weighted_news(sig, NOW, "1-3d")
    assert "1 zpráva bez času publikace" in reasons[-1] and len(ids) == 1
    only_unknown = xauusd.NewsSignal("geopolitics", [], unknown_age=2)
    value, reasons, _, quality = xauusd._weighted_news(only_unknown, NOW, "1-3d")
    assert value == 0.0 and quality == "partial" and "2 zprávy" in reasons[0]


def test_b_gdelt_time_is_labelled_as_capture_in_score_reasons(db_session, monkeypatch):
    monkeypatch.setattr(run_ingest.dt, "datetime", _FrozenDatetime)
    _news(db_session, "Ceasefire talks collapse", "gdelt_seen", 2, source="gdelt:reuters.com")
    sig = run_ingest._news_signal(db_session, "geopolitics")
    assert "zachyceno GDELT" in sig.points[0].description


def test_b_oil_supply_risk_and_feed_freshness_ignore_fetch_times(monkeypatch):
    attacks = [_headline("Drone attack on Saudi refinery", "fetched"), _headline("Houthi missile strike on tanker", "fetched")]
    assert oil_model.supply_risk_component(attacks, NOW)["score"] == 0
    assert oil_model.supply_risk_component([{**h, "time_basis": "published"} for h in attacks], NOW)["score"] == 1

    from app.connectors import portals
    from app.data import probes

    entries = [portals.PortalEntry("X", "old", "u1", NOW - dt.timedelta(days=3), "", "en", time_basis="published"),
               portals.PortalEntry("X", "undated", "u2", NOW, "", "en", time_basis="fetched")]
    monkeypatch.setattr(portals, "fetch_all", lambda client=None: (entries, []))
    assert probes._p_rss()[1] == (NOW - dt.timedelta(days=3)).isoformat()  # not "now" from the undated one


def test_b_lists_show_items_without_publication_time_after_dated_ones():
    hs = [_headline("Gold steady", "fetched", 1), _headline("Gold falls", "published", 300)]
    assert [n["title"] for n in markets.instrument_news(hs, "XAUUSD")] == ["Gold falls", "Gold steady"]


# --- C: GDELT gold = gold as a market
REAL_TITLES = [  # (title, GDELT language, keep?) — all from GDELT's answer of 2026-11-07
    ("Žilinský miešaný zbor zažiaril v Grécku . Domov si priniesol zlato aj striebro", "Slovak", False),
    ("Λασίθι : Σορός άνδρα εντοπίστηκε σε θαλάσσια περιοχή ανοικτά της Χρυσής", "Greek", False),
    ("Ο Σταύρος Ξαρχάκος τιμήθηκε με Χρυσό Αλέξανδρο", "Greek", False),
    ("Ecuador consiguió dos medallas de oro , tres de plata y dos de bronce", "Spanish", False),
    ("Elderly Woman Found Strangled , Gold Teeth Allegedly Stolen !", "English", False),
    ("Dominic Valavuori voitti SM - kultaa poikkeuksellisella tavalla", "Finnish", False),
    ("Gold Coast Suns facing internal crisis", "English", False),
    ("Diwali shopping surges despite price rise , markets packed with shoppers", "English", False),
    ("Gold at $3 , 800 – 4 , 000 : Could an AI spending crash trigger the next bullion rally ? Jefferies explains", "English", True),
    ("Bullion Cues : Supports fuel a rebound - The HinduBusinessLine", "English", True),
    ("ارتفاع سعر جرام الذهب في السعودية اليوم السبت 7 - 11 - 2026", "Arabic", True),
    ("许安丰 ： 11 . 7黄金本周完美验证 ， 下周行情策略分析 _ 名家点金 _ 黄金网 _ 中金在线", "Chinese", True),
    ("Altın alacaklar dikkat ! Uzman isim 7 bin TL seviyesini işaret etti", "Turkish", True),
    ("Una mina de plata y oro en Sonora ya cuesta unos 37 millones de dólares más de lo previsto", "Spanish", True),
    ("Gold bricht zu Wochenbeginn ein : Wie dramatisch wird jetzt es für Goldminenaktien ?", "German", True),
    ("क्या अब सोना में निवेश का सबसे सुरक्षित विकल्प नहीं रह गया है ?", "Hindi", True),
    ("Cena zlata vystoupala na rekord", "Czech", True),
]


def test_c_title_check_on_real_gdelt_titles_in_many_languages():
    for title, lang, keep in REAL_TITLES:
        assert relevance.gold_market(title, lang)[0] is keep, (title, lang)


def test_c_a_language_without_vocabulary_is_not_dropped_for_its_language():
    keep, why = relevance.gold_market("金価格が最高値を更新", "Japanese")  # Japanese: no vocabulary in FTI
    assert keep and "dotaz GDELT" in why


def test_c_gold_query_asks_for_market_context_and_fti_filters_and_counts(monkeypatch):
    assert '"central bank"' in gdelt.QUERIES["gold"] and "ounce" in gdelt.QUERIES["gold"]
    arts = [{"url": f"u{i}", "title": t, "seendate": "20261107T110000Z", "domain": "d", "language": lang}
            for i, (t, lang, _) in enumerate(REAL_TITLES)]
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"articles": arts})))
    got = gdelt.fetch_query("gold", gdelt.QUERIES["gold"], client=client)
    assert len(got) == sum(1 for *_, k in REAL_TITLES if k)
    assert gdelt.last_filtered["gold"] == {"received": len(REAL_TITLES), "kept": len(got)}
    assert {e.source_language for e in got} >= {"Arabic", "Chinese", "Turkish"}  # not English only
    # other queries are not filtered by the gold check
    assert len(gdelt.fetch_query("geopolitics", "war", client=client)) == len(REAL_TITLES)


def test_c_a_query_gdelt_does_not_accept_is_reported_without_pausing_the_others():
    asked = []

    def handler(request):
        asked.append(request.url.params["query"])
        if request.url.params["query"] == gdelt.QUERIES["gold"]:
            return httpx.Response(200, text="Your query contained a syntax error: parentheses must be balanced")
        return httpx.Response(200, json={"articles": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gdelt._memory.update({"next": list(gdelt.QUERIES).index("gold")})
    _, errors = gdelt.fetch_all_queries(client=client, sleep_fn=lambda s: None, now=NOW)
    assert len(asked) == 2 and asked[0] == gdelt.QUERIES["gold"]  # not retried; the next query was still asked
    assert "nepřijal" in errors[0] and gdelt._memory["paused_until"] is None


def test_c_gold_coast_and_medals_are_not_gold_news_on_the_markets_page():
    hs = [_headline("Gold Coast Suns facing internal crisis"), _headline("Gold medal for Kenya"), _headline("Gold steadies")]
    assert [n["title"] for n in markets.instrument_news(hs, "XAUUSD")] == ["Gold steadies"]


# --- D: a translation that changes a number is not shown
CORRUPTED = [  # (original, what the translation made of it) — real cases from FTI's database
    ("Gold at $3 , 800 – 4 , 000 : Could an AI spending crash trigger the next bullion rally ?", "Zlato za 3 dolary, 800 - 4 000: Může …"),
    ("Silver just hit a fresh 3-month low after the CPI.", "Stříbro právě po spotřebitelských cenách kleslo o 8 %."),
    ("Tether global investments fund buys $1.28m in Gold.com stock", "Tether globální investiční fond kupuje 1.28 dollarsm v Gold.com akciích"),
    ("Gold slides in October, spot prices dip under $4k", "Zlato padá v říjnu, spot ceny klesnout pod 4 dollarsk"),
    ("U.S. Dollar Rallies As Non Farm Payrolls Jump To 165,000", "Americký dolar stoupá, pracovní místa rostou na 165,000"),
    ("Brazil Stocks Plunge 13 . 9 % as Fed Week Begins", "Brazílie Zásoby Plunge 13. 9 % jako federální rezervní týden začíná"),
    ("Trade deficit hits $105.6 billion", "Obchodní deficit dosahuje 105,6 bilionu dolarů"),  # billion ≠ bilion
]
CORRECT = [
    ("Trade deficit hits $105.6 billion, widest since", "Obchodní deficit dosahuje 105,6 miliardy dolarů, nejširší od"),
    ("Gold at $3 , 800 – 4 , 000 : Could an AI spending crash", "Zlato za 3800–4000 dolarů: Může havárie výdajů AI"),
    ("Saudi Arabia's economy contracts 3.8% as war disrupts oil", "Saúdská ekonomika se smršťuje o 3,8 %, válka narušuje ropu"),
    ("NatWest Q3 2026 slides: 21.6% ROTE leads UK banks", "NatWest Q3 2026 padá: 21.6 % ROTE vede britské banky"),
    ("Can the New Zealand Dollar hold 0.5600 this time?", "Může novozélandský dolar udržet 0,5600 tentokrát?"),
    ("Fed cuts rates by 25bp to 3.50%-3.75%", "Snížení sazeb Fedu o 25 bazických bodů na 3,50–3,75 %"),
    ("Central banks bought 20t of gold in September", "Centrální banky nakoupily v září 20 tun zlata"),
    ("October 2026 euro area bank lending survey", "října 2026 Průzkum bankovních úvěrů eurozóny"),
    ("Gold dives below $4,100 as NFP underpins Fed hike odds", "Zlato se potápí pod 4 100 dolarů"),
]


def test_d_number_check_rejects_every_real_corrupted_translation():
    for original, cs in CORRUPTED:
        assert not translate.numbers_consistent(original, cs), (original, cs)


def test_d_number_check_accepts_correct_translations():
    for original, cs in CORRECT:
        assert translate.numbers_consistent(original, cs), (original, cs)


def test_d_preparation_keeps_numbers_whole_before_translating():
    assert translate.prepare("Gold at $3 , 800 – 4 , 000 :").startswith("Gold at 3800–4000 dollars")
    assert "4000 dollars" in translate.prepare("spot prices dip under $4k")
    assert "1.28 million dollars" in translate.prepare("fund buys $1.28m in stock")
    assert "165000" in translate.prepare("Payrolls Jump To 165,000")
    assert "13.9%" in translate.prepare("Stocks Plunge 13 . 9 % as")


class _FakeModel:
    def __init__(self, answer):
        self.answer = answer

    def translate(self, text):
        return self.answer


def test_d_translate_returns_rejected_when_the_model_changes_a_number(monkeypatch):
    monkeypatch.setattr(translate, "_load", lambda: _FakeModel("Stříbro kleslo o 8 %."))
    assert REAL_TRANSLATE("Silver just hit a fresh 3-month low") == translate.REJECTED == ""
    monkeypatch.setattr(translate, "_load", lambda: _FakeModel("Zlato se potápí pod 4100 dolarů"))
    assert REAL_TRANSLATE("Gold dives below $4,100") == "Zlato se potápí pod 4100 dolarů"
    monkeypatch.setattr(translate, "_load", lambda: None)
    assert REAL_TRANSLATE("Gold dives below $4,100") is None  # no translator: nothing stored, tried again later


def test_d_original_is_shown_and_labelled_when_the_translation_is_unreliable(db_session):
    bad = _news(db_session, "Silver just hit a fresh 3-month low", title_cs="Stříbro kleslo o 8 %.")  # stored before the check
    rejected = _news(db_session, "Gold at $3 , 800 – 4 , 000", title_cs="")
    good = _news(db_session, "Gold dives below $4,100", title_cs="Zlato se potápí pod 4100 dolarů")
    assert run_ingest._titles(bad) == {"title": "Silver just hit a fresh 3-month low", "title_en": bad.title,
                                       "translated": False, "translation_failed": True}
    assert run_ingest._titles(rejected)["title"] == "Gold at $3 , 800 – 4 , 000"
    assert run_ingest._titles(rejected)["translation_failed"] is True
    assert run_ingest._titles(good) == {"title": "Zlato se potápí pod 4100 dolarů", "title_en": good.title,
                                        "translated": True, "translation_failed": False}
    report = grouping._report(bad)
    assert report["title"] == bad.title and report["translation_failed"] is True and report["title_original"] == bad.title
    assert bad.title == "Silver just hit a fresh 3-month low"  # the original itself is never changed


def test_d_ingestion_stores_a_rejection_and_retranslates_an_old_bad_translation(db_session, monkeypatch):
    monkeypatch.setattr(run_ingest.dt, "datetime", _FrozenDatetime)
    old_bad = _news(db_session, "Gold slides, spot prices dip under $4k", title_cs="Zlato padá pod 4 dollarsk")
    fresh = _news(db_session, "Silver just hit a fresh 3-month low", factors=("fed_tone",))
    answers = {old_bad.title: "Zlato padá, spotové ceny klesají pod 4000 dolarů", fresh.title: "Stříbro kleslo o 8 %."}
    monkeypatch.setattr(translate, "translate", lambda text: REAL_TRANSLATE(text))
    monkeypatch.setattr(translate, "_load", lambda: _Answers(answers))
    assert run_ingest.translate_pending_headlines(db_session) == 2
    db_session.refresh(old_bad)
    db_session.refresh(fresh)
    assert old_bad.title_cs == "Zlato padá, spotové ceny klesají pod 4000 dolarů"  # made again, numbers checked
    assert fresh.title_cs == ""  # rejected — not tried again in the next cycle
    assert run_ingest.translate_pending_headlines(db_session) == 0


class _Answers:
    def __init__(self, answers):
        self.answers = answers

    def translate(self, text):
        return next(v for k, v in self.answers.items() if translate.prepare(k) == text)


class _FrozenDatetime(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


def test_unknown_age_note_wording():
    assert timebasis.unknown_age_note(0) == ""
    assert timebasis.unknown_age_note(1).startswith("1 zpráva ")
    assert timebasis.unknown_age_note(3).startswith("3 zprávy ")
    assert timebasis.unknown_age_note(7).startswith("7 zpráv ")
