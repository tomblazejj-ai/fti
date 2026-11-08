"""The complex AI analysis of XAU/USD end to end with a mock Groq: the common context (every fact with source,
time and area), the AI Router (only free + approved + implemented providers with a key; paid never), three
roles (makro → technika → synteza) on the right models, every answer checked against FTI's facts, a specialist
that invents a number is left out, the result stored with each role's provider/model/tokens, triggers on real
changes only, and "unavailable" — never a pretended analysis — when no model is left."""

import copy
import datetime as dt
import json

import httpx
import pytest

from app.ai import context, groq, guard, pipeline, router, tasks, triggers
from app.data import prices, secrets, settings_store, store
from app.models import AnalysisRecord, AnalysisSnapshot, Instrument

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
KEY = "gsk_" + "Tr4d" * 10


def _tf(tf, word, close, swing_high, swing_low):
    return {"tf": tf, "tf_label": tf, "direction": "up" if word == "Nahoru" else "down", "word": word, "score": 0.6, "strength": "silný",
            "adx": 29.9, "close": close, "ema20": 4049.16, "ema50": 4028.88, "atr": 35.99, "change_pct": 0.5, "change_bars": 20,
            "swing_high": swing_high, "swing_low": swing_low, "text": "Cena nad EMA50.", "as_of": "2026-11-06T20:00:00+00:00"}


GOLD_CARD = {"code": "XAUUSD", "name": "XAU/USD", "subtitle": "Zlato / americký dolar", "kind": "gold", "digits": 2, "score10": -3,
             "word": "Mírně negativní", "bias": "SHORT", "raw": -8, "possible": 25, "missing": [], "for": [], "against": [],
             "components": [{"key": "rates", "label": "Úrokové sazby", "score": 0, "max": 2,
                             "text": "2letý výnos 4,46 % vs. sazba Fedu 3,88 %.", "details": ["2letý výnos USA: 4,46 % (data k 2026-11-05)"]}],
             "retail": {"long_pct": 69.0, "change_4w": -6.6, "as_of": "2026-11-03", "head": "Retail není v extrému."},
             "watch": [], "news": [], "technical": [], "trend": "Dolů"}
PAYLOAD = {
    "markets": {"computed_at": "x", "markets": [GOLD_CARD, {**GOLD_CARD, "code": "EURUSD", "bias": "NEUTRÁLNÍ", "score10": 0}],
                "next_events": [], "highlights": []},
    "market": {"open": False, "reason": "víkend", "next_open": "2026-11-08T23:00:00+00:00"},
    "gold_data": {"H4": {"source": "Dukascopy", "kind_cs": "kotace Dukascopy", "quality": {"label": "historická data", "as_of": "2026-11-06T21:59:59+00:00"}},
                  "D1": {"source": "Dukascopy", "bars": 87}},
    "mtf": {"intraday": {"label": "Intradenní trend", "word": "Nahoru", "direction": "up", "score": 0.62, "timeframes": ["M15", "H1", "H4"], "agree": ["H4"]},
            "swing": {"label": "Swingový trend", "word": "Spíše dolů", "direction": "sideways", "score": -0.34, "timeframes": ["H4", "D1"], "agree": []},
            "overall": {"label": "Celkový trend", "word": "Do strany", "direction": "sideways", "score": 0.1, "timeframes": ["H4", "D1"], "agree": []},
            "advice": "Vhodnější je intradenní obchod.", "price_time": "2026-11-06T21:45:00+00:00",
            "timeframes": [_tf("H4", "Nahoru", 4069.55, 4146.78, 3895.2), _tf("D1", "Dolů", 4069.55, 4081.96, 3869.05)]},
    "technical": None,
    "verdict": {"action_text": "Vyčkat — žádná strana nemá výhodu.", "direction_text": "BEZ JASNÉHO SMĚRU", "combined": 0.085,
                "confidence": "nízká", "reasons": ["Fondy prodávají."]},
    "decision": {"headline": "Platí 4 podmínky pro pokles a 2 pro růst.", "bull": [{"title": "Reálné výnosy klesají", "active": True}],
                 "bear": [{"title": "Dolar posiluje nad 101,62", "active": True}]},
    "dxy": {"price": 102.317, "trends": {"intraday": {"word": "Nahoru"}, "swing": {"word": "Nahoru"}, "overall": {"word": "Nahoru"},
                                         "price_time": "2026-11-06T21:45:00+00:00"},
            "correlation": {"d60": {"value": -0.46, "label": "střední opačná"}, "d20": {"value": -0.18}, "h1": {"value": -0.14}},
            "key_levels": {"text": "DXY: nejbližší support 101,63, rezistence 102,56.", "filter": "Pro zlato spíš shorty."}},
    "intermarket": {"items": [{"id": "VIXCLS", "label": "VIX", "unit": "body", "last": 17.2, "as_of": "2026-11-06", "change_5": -1.1,
                               "change_20": 2.3, "change_unit": "body", "corr_gold": 0.12, "corr_days": 60, "corr_word": "téměř žádná",
                               "stale": False, "source": "FRED VIXCLS"}], "missing": []},
    "cot": {"spec_net": 103614.0, "change_1w": -1948.0, "change_4w": -7373.0, "cot_index_1y": 25.2, "cot_index_3y": 37.6,
            "extreme": "neutral", "texts": [], "as_of": "2026-11-03"},
    "gold_vol": {"last": 25.83, "median": 26.62, "p75": 30.06, "elevated": False, "as_of": "2026-11-06"},
    "calendar": {"events": [{"name": "Inflace CPI (USA)", "datetime": "2026-11-10T13:30:00+00:00", "importance": 3, "past": False,
                             "previous": "2,6 % r/r", "forecast": None, "up_if": "inflace zpomalí", "down_if": "inflace bude vyšší",
                             "source": "FRED"}]},
    "news": {"hours": 72, "count": 15, "bullish": 12, "bearish": 3, "score": 0.48, "unknown_age": 0,
             "key": [{"title": "Goldman snižuje prognózu", "title_en": "Goldman lowers year-end gold forecast", "translated": True,
                      "source": "Investing.com", "published_at": "2026-11-06T07:44:23+00:00", "time_basis": "published"}]},
    "headline_risk": {"level": 1, "word": "zvýšené", "hours": 12, "cluster": False, "items": []},
    "season_daily": {"gold": {"next30": {"avg": -0.07, "up": 4, "n": 10, "from_text": "8. 11.", "to_text": "8. 12."}}},
    "sources_status": [{"key": "price", "label": "Cena XAUUSD", "provider": "Dukascopy", "status": "closed", "note": "Trh zavřen.",
                        "as_of": "2026-11-06T21:45:00+00:00"}],
}
SPEC = {"zaver": "Obraz je smíšený.", "smer": "nejasný", "jistota": "nízká",  # F2 (time of FTI's computation) is in every role's facts
        "pro_rust": [{"text": "Data jsou z posledního výpočtu.", "fakta": ["F2"]}], "pro_pokles": [], "sledovat": [], "chybi": []}


def _final(**kw):
    out = {"shrnuti": "Bez výhody — NO TRADE do CPI.", "doporuceni": "NO TRADE", "bias": "neutrální", "horizont": "swing (dny)",
           "jistota": "nízká", "technika": [], "fundament": [], "zpravy_sentiment": [], "intermarket": [], "pro": [], "proti": [],
           "scenare": [{"typ": "LONG", "popis": "Návrat nad swing high.", "potvrzeni": [{"text": "Závěr nad 4146.78.", "fakta": ["F1"]}],
                        "invalidace": [{"text": "Pád pod 3895.2.", "fakta": ["F1"]}]}],
           "rizika": [], "vztah_k_enginu": {"shoda": "souhlasí", "text": "Engine také čeká.", "fakta": []}, "chybejici_data": []}
    out.update(kw)
    return out


@pytest.fixture()
def env(db_session, monkeypatch):
    cfg = {"provider": "groq", "daily_request_cap": 80, "daily_token_cap": 100000, "per_minute_cap": 6, "auto_analyses": True}
    saved: dict = {}
    monkeypatch.setattr(settings_store, "get", lambda path, default=None: cfg if path == "ai" else default)
    monkeypatch.setattr(secrets, "get", lambda name: KEY if name == "GROQ_API_KEY" else "")
    monkeypatch.setattr(store, "cache_get", lambda key, session=None: (saved.get(key), None))
    monkeypatch.setattr(store, "cache_put", lambda key, payload, source="", session=None: saved.__setitem__(key, payload))
    monkeypatch.setattr(prices, "quote", lambda code, now=None: {"available": False})
    guard.reset_memory()
    inst = Instrument(code="XAUUSD", name="Gold", pillar_config={})
    db_session.add(inst)
    db_session.commit()
    state = {"inst": inst, "replies": [], "seen": [], "cfg": cfg}

    def handler(request):
        state["seen"].append(json.loads(request.content))
        return state["replies"].pop(0)

    monkeypatch.setattr(groq, "_transport", httpx.MockTransport(handler))
    yield state
    guard.reset_memory()


def _snap(session, inst, payload, at):
    session.add(AnalysisSnapshot(instrument_id=inst.id, computed_at=at, payload=payload))
    session.commit()


def _ok(content, model):
    return httpx.Response(200, json={"model": model, "usage": {"prompt_tokens": 900, "completion_tokens": 300},
                                     "choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}, "finish_reason": "stop"}]})


def _fid(facts, name):
    return next(f["id"] for f in facts if f["co"].startswith(name))


def test_context_has_every_area_with_source_and_time(db_session, env):
    _snap(db_session, env["inst"], PAYLOAD, NOW)
    fs, meta = context.trade(db_session, "XAUUSD", quote_fn=lambda c: {"available": False})
    areas = {f.get("oblast") for f in fs}
    assert {"trh", "technika", "fundament", "engine", "dolar", "mezitrh", "pozice", "volatilita", "kalendar", "zpravy",
            "sezonnost", "kvalita"} <= areas
    vix = next(f for f in fs if f["co"] == "VIX")
    assert vix["zdroj"] == "FRED VIXCLS" and vix["k"] == "2026-11-06" and "korelace" in vix["text"]
    news = next(f for f in fs if f["co"] == "Klíčová zpráva")
    assert news["hodnota"] == "Goldman lowers year-end gold forecast" and news["puvod_casu"] == "čas publikace uvedený zdrojem"
    assert "denní technika SMA200 a klíčové úrovně (málo denní historie)" in meta["missing"]  # said, not hidden
    with pytest.raises(context.NotReady):
        context.trade(db_session, "EURUSD")


def test_router_uses_only_free_approved_implemented_providers_with_a_key(env, monkeypatch):
    assert [(c.provider, c.model) for c in router.candidates("synteza")] == [("groq", "openai/gpt-oss-120b"), ("groq", "openai/gpt-oss-20b")]
    assert [c.model for c in router.candidates("technika")] == ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
    rows = {r["id"]: r for r in router.catalog()}
    assert rows["openai"]["used"] is False and rows["openai"]["free"] is False and "Placené" in rows["openai"]["why_not"]
    assert rows["anthropic"]["used"] is False and rows["gemini"]["used"] is False
    monkeypatch.setattr(secrets, "get", lambda name: "")
    assert router.candidates("synteza") == []  # no key: nothing, never a paid fallback


def test_three_roles_on_their_models_checked_and_stored(db_session, env):
    _snap(db_session, env["inst"], PAYLOAD, NOW - dt.timedelta(minutes=10))
    env["replies"] += [_ok(SPEC, "openai/gpt-oss-120b"), _ok(SPEC, "openai/gpt-oss-20b"), _ok(_final(), "openai/gpt-oss-120b")]
    r = tasks.run(db_session, "trade", "XAUUSD", now=NOW)
    assert r["status"] == "ok", r
    assert [s["model"] for s in env["seen"]] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "openai/gpt-oss-120b"]
    first = json.loads(env["seen"][0]["messages"][1]["content"])["fakta"]
    assert {f.get("oblast") for f in first} <= {"fundament", "mezitrh", "pozice", "kalendar", "zpravy", "sezonnost", "kvalita"}
    last = json.loads(env["seen"][2]["messages"][1]["content"])["fakta"]
    assert sum(1 for f in last if f["co"].startswith("Závěr specialisty")) == 2  # both specialists reached the synthesis
    a = r["analysis"]
    assert [s["role"] for s in a["stages"]] == ["makro", "technika", "synteza"] and a["providers"] == ["groq"]
    assert a["output"]["doporuceni"] == "NO TRADE" and a["validation"]["ok"] is True and a["tokens"] == {"in": 2700, "out": 900}
    rec = db_session.query(AnalysisRecord).one()
    assert rec.kind == "ai_trade" and rec.preferred is None  # an AI scenario, never an engine signal or an order
    assert KEY not in json.dumps(env["seen"])
    # the same data again: no new request
    assert tasks.run(db_session, "trade", "XAUUSD", now=NOW + dt.timedelta(hours=2))["status"] == "cached"
    assert len(env["seen"]) == 3


def test_a_specialist_that_invents_a_number_is_left_out(db_session, env):
    _snap(db_session, env["inst"], PAYLOAD, NOW - dt.timedelta(minutes=10))
    bad = {**SPEC, "zaver": "Zlato míří na 4 444."}
    env["replies"] += [_ok(bad, "openai/gpt-oss-120b"), _ok(SPEC, "openai/gpt-oss-20b"), _ok(_final(), "openai/gpt-oss-120b")]
    r = tasks.run(db_session, "trade", "XAUUSD", now=NOW)
    last = json.loads(env["seen"][2]["messages"][1]["content"])["fakta"]
    assert [f["co"] for f in last if f["co"].startswith("Závěr specialisty")] == ["Závěr specialisty: technika"]
    assert r["analysis"]["stages"][0]["validation"]["ok"] is False


def test_long_without_invalidation_is_not_verified(db_session, env):
    _snap(db_session, env["inst"], PAYLOAD, NOW - dt.timedelta(minutes=10))
    final = _final(doporuceni="LONG", scenare=[{"typ": "LONG", "popis": "x", "potvrzeni": [{"text": "x", "fakta": ["F1"]}], "invalidace": []}])
    env["replies"] += [_ok(SPEC, "openai/gpt-oss-120b"), _ok(SPEC, "openai/gpt-oss-20b"), _ok(final, "openai/gpt-oss-120b")]
    r = tasks.run(db_session, "trade", "XAUUSD", now=NOW)
    assert r["status"] == "invalid" and "invalidace" in r["analysis"]["validation"]["rules"][0]


def test_no_model_left_means_unavailable_not_a_pretended_analysis(db_session, env):
    _snap(db_session, env["inst"], PAYLOAD, NOW - dt.timedelta(minutes=10))
    limited = httpx.Response(429, headers={"retry-after": "600"}, json={"error": {"message": "rate"}})
    env["replies"] += [limited, limited]
    r = tasks.run(db_session, "trade", "XAUUSD", now=NOW)
    assert r["status"] == "unavailable" and "makro" in r["text"] and db_session.query(AnalysisRecord).count() == 0


def test_router_waits_for_the_minute_window_once(db_session, env, monkeypatch):
    waits = []
    blocked = {"n": 0}
    real = guard.check

    def check(session, model, est, priority="normal", now=None, require_enabled=True):
        if blocked["n"] == 0:
            blocked["n"] += 1
            raise guard.Blocked("minute", (now or NOW) + dt.timedelta(seconds=40))
        return real(session, model, est, priority, now, require_enabled)

    monkeypatch.setattr(guard, "check", check)
    env["replies"].append(_ok(SPEC, "openai/gpt-oss-120b"))
    r = router.run_role(db_session, "makro", [{"role": "user", "content": "x"}], 100, 200, pipeline.SPEC_SCHEMA, "trade",
                        now=NOW, sleep=waits.append)
    assert r.model == "openai/gpt-oss-120b" and waits == [40.0]


def test_triggers_only_on_real_changes(db_session, env):
    old = copy.deepcopy(PAYLOAD)
    new = copy.deepcopy(PAYLOAD)
    assert triggers.trade_reason(new, old, NOW, NOW - dt.timedelta(minutes=30)) is None
    new["mtf"]["intraday"] = {**new["mtf"]["intraday"], "direction": "down", "word": "Dolů"}
    assert "intradenní trend" in triggers.trade_reason(new, old, NOW, NOW - dt.timedelta(minutes=30))[1]
    released = copy.deepcopy(PAYLOAD)
    assert "Inflace CPI" in triggers.trade_reason(released, old, dt.datetime(2026, 11, 10, 14, 0, tzinfo=UTC),
                                                  dt.datetime(2026, 11, 10, 13, 0, tzinfo=UTC))[1]
    _snap(db_session, env["inst"], old, NOW - dt.timedelta(minutes=30))
    _snap(db_session, env["inst"], new, NOW)
    jobs = triggers.jobs(db_session, NOW)
    assert jobs[0]["task"] == "trade" and jobs[0]["code"] == "XAUUSD"


def test_intermarket_correlation_direction_and_staleness():
    from app.market import intermarket

    days = [(dt.date(2026, 7, 1) + dt.timedelta(days=i)).isoformat() for i in range(80)]
    gold = {d: 4000 + (i % 7) * 10 + i for i, d in enumerate(days)}
    vix = {d: 30 - (gold[d] - 4000) / 10 for d in days}  # moves exactly against gold
    old = {d: v for d, v in list(vix.items())[:20]}
    out = intermarket.build({"VIXCLS": vix, "DGS10": old}, gold, dt.datetime(2026, 9, 19, tzinfo=UTC))
    v = next(i for i in out["items"] if i["id"] == "VIXCLS")
    assert v["corr_gold"] == -1.0 and v["corr_word"] == "silná opačná" and v["stale"] is False
    y = next(i for i in out["items"] if i["id"] == "DGS10")
    assert y["stale"] is True and y["corr_gold"] is None and y["change_unit"] == "p. b."  # too few common days: no number invented
    assert any("SP500" in m for m in out["missing"])


SERIES_FACTS = [  # as context.trade writes them (8. 11. 2026 values)
    {"id": "F33", "co": "VIX — volatilita akcií S&P 500 (CBOE)", "hodnota": 28.18, "zdroj": "FRED VIXCLS",
     "text": "body; za 5 obchodních dní roste (+10.98 body), za 20 dní roste (+12.77 body); korelace denních změn TÉTO řady se zlatem -0.27",
     "rada": "VIXCLS", "smer": {"5d": "roste", "20d": "roste"}, "korelace": [-0.27]},
    {"id": "F34", "co": "Výnos 10letých amerických dluhopisů (Treasury)", "hodnota": 4.84, "zdroj": "FRED DGS10",
     "text": "%; za 5 obchodních dní klesá (-0.14 p. b.), za 20 dní klesá (-0.44 p. b.); korelace denních změn TÉTO řady se zlatem -0.26",
     "rada": "DGS10", "smer": {"5d": "klesá", "20d": "klesá"}, "korelace": [-0.26]},
    {"id": "F35", "co": "Reálný výnos 10 let (TIPS)", "hodnota": 2.6, "zdroj": "FRED DFII10",
     "text": "%; za 5 obchodních dní klesá (-0.03 p. b.), za 20 dní klesá (-0.32 p. b.); korelace denních změn TÉTO řady se zlatem -0.22",
     "rada": "DFII10", "smer": {"5d": "klesá", "20d": "klesá"}, "korelace": [-0.22]},
    {"id": "F37", "co": "Akciový index S&P 500", "hodnota": 7353.73, "zdroj": "FRED SP500",
     "text": "body; za 5 obchodních dní klesá (-4.75 %), za 20 dní klesá (-5.3 %); korelace denních změn TÉTO řady se zlatem 0.37",
     "rada": "SP500", "smer": {"5d": "klesá", "20d": "klesá"}, "korelace": [0.37]},
]


def test_independent_check_catches_the_real_errors_of_8_november():
    from app.ai import check

    out = {"pro_pokles": [{"text": "Stoupající výnosy 10‑letých dluhopisů (4,84 %) a reálný výnos (2,6 %) zvyšují atraktivitu "
                                   "alternativ k zlatu.", "fakta": ["F34", "F35"]}],
           "pro_rust": [{"text": "Negativní korelace VIX (‑0,27) a akcií S&P 500 (‑0,26) s cenou zlata naznačuje, že při poklesu "
                                 "akcií může zlato růst.", "fakta": ["F33", "F34", "F37"]},
                        {"text": "Reálný výnos klesá (−0,32 p. b. za 20 dní).", "fakta": ["F35"]},
                        {"text": "VIX za 20 dní vzrostl o 12,77 bodu.", "fakta": ["F37"]}]}
    problems = check.attribution(out, SERIES_FACTS)
    by_path = {}
    for p in problems:
        by_path.setdefault(p["path"], []).append(p["problem"])
    assert any("Výnos 10letých" in x and "klesá" in x for x in by_path["$.pro_pokles[0]"])  # rising yields: data say falling
    assert any("Reálný výnos" in x for x in by_path["$.pro_pokles[0]"])
    assert any("-0,26" in x and "Výnos 10letých" in x and "S&P 500" in x for x in by_path["$.pro_rust[0]"])  # misattributed
    assert "$.pro_rust[1]" not in by_path  # a true statement passes
    assert any("12,77" in x for x in by_path["$.pro_rust[2]"])  # the number is VIX's, but the point cites the S&P 500 fact
    cleaned, removed, stuck = check.drop(out, problems)
    assert cleaned["pro_pokles"] == [] and [p["text"] for p in cleaned["pro_rust"]] == ["Reálný výnos klesá (−0,32 p. b. za 20 dní)."]
    assert len(removed) == 3 and stuck == []  # three points removed (one had two problems)


def test_a_conditional_is_not_a_claim_about_the_data():
    from app.ai import check

    out = {"sledovat": [{"text": "Pokud výnosy 10letých dluhopisů porostou, zlato oslabí.", "fakta": ["F34"]}],
           "shrnuti": "Výnosy 10letých dluhopisů stoupají."}
    problems = check.attribution(out, SERIES_FACTS)
    assert [p["path"] for p in problems] == ["$.shrnuti"]  # the summary is wrong; the condition is fine
    cleaned, removed, stuck = check.drop(out, problems)
    assert removed == [] and len(stuck) == 1  # a wrong summary cannot be cut out: the answer stays unverified


def test_wrong_specialist_points_never_reach_the_synthesis(db_session, env):
    payload = copy.deepcopy(PAYLOAD)
    payload["intermarket"]["items"].append({"id": "DGS10", "label": "Výnos 10letých amerických dluhopisů (Treasury)", "unit": "%",
                                            "last": 4.84, "as_of": "2026-11-05", "change_5": -0.14, "change_20": -0.44,
                                            "change_unit": "p. b.", "corr_gold": -0.26, "corr_days": 60, "corr_word": "slabá opačná",
                                            "stale": False, "source": "FRED DGS10"})
    _snap(db_session, env["inst"], payload, NOW - dt.timedelta(minutes=10))
    fs, _ = context.trade(db_session, "XAUUSD", quote_fn=lambda c: {"available": False})
    y = next(f for f in fs if f.get("rada") == "DGS10")
    assert y["smer"] == {"5d": "klesá", "20d": "klesá"} and y["korelace"] == [-0.26]
    wrong = {**SPEC, "pro_pokles": [{"text": "Výnosy 10letých dluhopisů stoupají.", "fakta": [y["id"]]}]}
    env["replies"] += [_ok(wrong, "openai/gpt-oss-120b"), _ok(SPEC, "openai/gpt-oss-20b"), _ok(_final(), "openai/gpt-oss-120b")]
    r = tasks.run(db_session, "trade", "XAUUSD", now=NOW)
    assert r["status"] == "ok"
    makro = r["analysis"]["stages"][0]
    assert makro["validation"]["removed"][0]["text"] == "Výnosy 10letých dluhopisů stoupají." and makro["output"]["pro_pokles"] == []
    sent = json.loads(env["seen"][2]["messages"][1]["content"])["fakta"]
    assert "stoupají" not in next(f for f in sent if f["co"] == "Závěr specialisty: makro")["text"]


def test_open_market_gets_a_fresh_analysis_every_6_hours_at_most(db_session, env):
    open_ = copy.deepcopy(PAYLOAD)
    open_["market"] = {"open": True}
    _snap(db_session, env["inst"], open_, NOW - dt.timedelta(minutes=30))
    _snap(db_session, env["inst"], open_, NOW)
    assert triggers.jobs(db_session, NOW)[0]["reason"] == "automaticky: pravidelná aktualizace (trh otevřený)"
    db_session.add(AnalysisRecord(kind="ai_trade", code="XAUUSD", created_at=NOW - dt.timedelta(hours=2), payload={}))
    db_session.commit()
    assert not any(j["task"] == "trade" for j in triggers.jobs(db_session, NOW))  # 2 h old and nothing changed: no request


def test_cloud_upload_sends_the_exported_files_and_fails_loudly(tmp_path, monkeypatch):
    from app.cloud import run, sync

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "markets.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "data" / "ai.json").write_text('{"analyses": []}', encoding="utf-8")
    sent = {}

    def push(names=None, now=None, snapshot=None):
        files, _ = snapshot(None)
        sent.update(files)
        return {"ok": True, "text": "Odesláno 2 změněných souborů", "uploaded": list(files), "unchanged": 0, "bytes": 30}

    monkeypatch.setattr(sync, "push", push)
    summary, ok = run.upload(tmp_path)
    assert ok and summary["uploaded"] == 2 and set(sent) == {"markets.json", "ai.json"}
    monkeypatch.setattr(sync, "push", lambda names=None, now=None, snapshot=None: {"ok": False, "text": "Cloud odmítl token"})
    assert run.main([str(tmp_path), "--upload"]) == 1  # GitHub marks the run as failed
    assert run.main([str(tmp_path)]) == 2  # no mode given: usage, nothing runs


def test_a_value_next_to_an_indicator_must_be_that_indicator():
    from app.ai import check

    facts = [{"id": "F12", "co": "Technika H4 (4 hodiny)", "hodnota": "Nahoru",
              "text": "Závěr 4069.55, EMA20 4049.16, EMA50 4028.88, ADX 29.9 (silný), ATR 35.99, swing high 4146.78, swing low 3895.2"}]
    out = {"potvrzeni": [{"text": "Průraz nad EMA20 (4069.55) na H4.", "fakta": ["F12"]},
                         {"text": "Udržení nad EMA50 4028,88 a swing high 4146.78.", "fakta": ["F12"]},
                         {"text": "Trh otevře a získá se čerstvá cena.", "fakta": []}]}
    problems = {p["path"]: p["problem"] for p in check.attribution(out, facts)}
    assert problems["$.potvrzeni[0]"] == "EMA20 je v citovaných údajích 4049.16, ne 4069.55"  # the close, not EMA20
    assert "$.potvrzeni[1]" not in problems
    assert problems["$.potvrzeni[2]"] == "bod se neopírá o žádný údaj FTI"
