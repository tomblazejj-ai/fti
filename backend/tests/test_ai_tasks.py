"""AI tasks end to end (app/ai/tasks.py) with a mock Groq server: facts come only from the engine,
identical inputs never cause a second request, cooldowns hold, a 429 moves to the next free model,
an outage pauses AI, invented numbers are caught, and with AI off nothing is sent at all."""

import copy
import datetime as dt
import json

import httpx
import pytest

from app.ai import groq, guard, tasks
from app.data import prices, secrets, settings_store, store
from app.models import AiUsage, AnalysisRecord, AnalysisSnapshot, Instrument, NewsItem

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
KEY = "gsk_" + "T4sk" * 10

GOLD = {
    "code": "XAUUSD", "name": "XAU/USD", "subtitle": "Zlato / americký dolar", "kind": "gold", "digits": 2,
    "score10": -3, "word": "Mírně negativní fundamentální výhled", "bias": "SHORT", "raw": -8, "possible": 23,
    "components": [
        {"key": "rates", "label": "Úrokové sazby", "score": -2, "max": 2,
         "text": "2letý výnos 4,61 % vs. sazba Fedu 3,88 % → trh čeká ZVYŠOVÁNÍ sazeb.", "details": ["data k 2026-10-30"]},
        {"key": "cot", "label": "COT bias", "score": -1, "max": 3, "text": "COT index 39/100.", "details": []},
    ],
    "missing": ["Trend"], "for": [{"label": "Úrokové sazby", "text": "x", "score": -2}], "against": [],
    "price": None, "trend": None,
    "retail": {"long_pct": 71.4, "change_4w": -3.4, "as_of": "2026-10-27", "head": "Sentiment podporuje SHORT bias."},
    "watch": [{"title": "ISM PMI průmysl", "datetime": "2026-11-02T15:00:00+00:00", "currency": "USD",
               "impact_text": "Střední dopad na USD", "forecast": "54.7", "previous": "54.5"}],
    "news": [{"title": "Zlato pod 3 886 dolarů", "source": "FXStreet", "published_at": "2026-10-30T20:09:21+00:00",
              "translated": True}],
    "technical": [],
}
GOOD = {"shrnuti": "Skóre −3 a BIAS SHORT: sazby (výnos 4,61 % proti 3,88 %) táhnou zlato dolů.",
        "bias": "SHORT vychází hlavně ze sazeb.", "pro": [{"text": "Sazby −2.", "fakta": ["F5"]}], "proti": [],
        "sledovat": [{"text": "ISM PMI, očekávání 54.7.", "fakta": ["F9"]}], "chybi": ["Trend"], "jistota": "střední"}


@pytest.fixture()
def env(db_session, monkeypatch):
    cfg = {"provider": "groq", "daily_request_cap": 80, "daily_token_cap": 100000, "per_minute_cap": 6}
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
    state = {"inst": inst, "cfg": cfg, "replies": [], "seen": []}

    def handler(request):
        state["seen"].append(request)
        return state["replies"].pop(0)

    monkeypatch.setattr(groq, "_transport", httpx.MockTransport(handler))
    yield state
    guard.reset_memory()


def _snapshot(session, inst, card, at):
    payload = {"markets": {"computed_at": at.isoformat(), "markets": [card], "next_events": [], "highlights": []}}
    session.add(AnalysisSnapshot(instrument_id=inst.id, computed_at=at, payload=payload))
    session.commit()


def _ok(content, model="openai/gpt-oss-120b"):
    return httpx.Response(200, json={"model": model, "usage": {"prompt_tokens": 900, "completion_tokens": 300},
                                     "choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)},
                                                  "finish_reason": "stop"}]})


def test_not_ready_tasks_say_why_and_send_nothing(db_session, env):
    for t in ("event", "zones"):
        r = tasks.run(db_session, t, "XAUUSD", now=NOW)
        assert r["status"] == "not_ready" and r["text"]
    assert env["seen"] == []


def test_without_an_engine_overview_there_is_nothing_to_interpret(db_session, env):
    r = tasks.run(db_session, "market", "XAUUSD", now=NOW)
    assert r["status"] == "not_ready" and env["seen"] == []


def test_market_analysis_uses_only_engine_facts_and_is_stored(db_session, env):
    _snapshot(db_session, env["inst"], GOLD, NOW - dt.timedelta(minutes=20))
    env["replies"].append(_ok(GOOD))
    r = tasks.run(db_session, "market", "XAUUSD", now=NOW)
    assert r["status"] == "ok", r
    body = json.loads(env["seen"][0].content)
    sent = json.loads(body["messages"][1]["content"])
    names = [f["co"] for f in sent["fakta"]]
    assert "Fundamentální skóre" in names and "Složka skóre: Úrokové sazby" in names and "Aktuální cena" in names
    assert next(f for f in sent["fakta"] if f["co"] == "Aktuální cena")["hodnota"] == "nedostupná"
    assert KEY not in env["seen"][0].content.decode("utf-8")
    rec = db_session.query(AnalysisRecord).one()
    assert rec.kind == "ai_market" and rec.code == "XAUUSD" and rec.preferred is None  # AI never decides LONG/SHORT
    assert rec.payload["validation"]["ok"] is True and db_session.query(AiUsage).count() == 1


def test_same_inputs_are_never_sent_twice(db_session, env):
    _snapshot(db_session, env["inst"], GOLD, NOW - dt.timedelta(minutes=20))
    env["replies"].append(_ok(GOOD))
    tasks.run(db_session, "market", "XAUUSD", now=NOW)
    for i in range(10):
        r = tasks.run(db_session, "market", "XAUUSD", now=NOW + dt.timedelta(hours=3, minutes=i))
        assert r["status"] == "cached"
    assert len(env["seen"]) == 1 and db_session.query(AiUsage).count() == 1


def test_cooldown_holds_unless_the_event_is_important(db_session, env):
    _snapshot(db_session, env["inst"], GOLD, NOW - dt.timedelta(minutes=20))
    env["replies"].append(_ok(GOOD))
    tasks.run(db_session, "market", "XAUUSD", now=NOW)
    changed = copy.deepcopy(GOLD)
    changed["score10"] = -6
    _snapshot(db_session, env["inst"], changed, NOW + dt.timedelta(minutes=5))
    r = tasks.run(db_session, "market", "XAUUSD", now=NOW + dt.timedelta(minutes=10))
    assert r["status"] == "cooldown" and len(env["seen"]) == 1 and r["analysis"]
    env["replies"].append(_ok({**GOOD, "shrnuti": "Skóre −6."}))
    r = tasks.run(db_session, "market", "XAUUSD", priority="high", now=NOW + dt.timedelta(minutes=11))
    assert r["status"] == "ok" and len(env["seen"]) == 2


def test_invented_number_is_flagged_not_shown_as_verified(db_session, env):
    _snapshot(db_session, env["inst"], GOLD, NOW - dt.timedelta(minutes=20))
    env["replies"].append(_ok({**GOOD, "shrnuti": "Cíl je 3 950 dolarů."}))
    r = tasks.run(db_session, "market", "XAUUSD", now=NOW)
    assert r["status"] == "invalid" and r["analysis"]["validation"]["unknown_numbers"] == ["3 950"]
    assert len(env["seen"]) == 1  # no second request because of it


def test_429_moves_to_the_next_free_model_once(db_session, env):
    _snapshot(db_session, env["inst"], GOLD, NOW - dt.timedelta(minutes=20))
    env["replies"] += [httpx.Response(429, headers={"retry-after": "30"}, json={"error": {"message": "limit"}}),
                       _ok(GOOD, model="openai/gpt-oss-20b")]
    r = tasks.run(db_session, "market", "XAUUSD", now=NOW)
    models = [json.loads(s.content)["model"] for s in env["seen"]]
    assert r["status"] == "ok" and models == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    assert r["analysis"]["model"] == "openai/gpt-oss-20b"


def test_when_every_free_model_is_limited_ai_pauses(db_session, env):
    _snapshot(db_session, env["inst"], GOLD, NOW - dt.timedelta(minutes=20))
    env["replies"] += [httpx.Response(429, headers={"retry-after": "60"}, json={})] * 3
    r = tasks.run(db_session, "market", "XAUUSD", now=NOW)
    assert r["status"] == "unavailable" and len(env["seen"]) == 3
    r = tasks.run(db_session, "market", "XAUUSD", now=NOW + dt.timedelta(seconds=10))
    assert r["status"] == "unavailable" and r["code"] == "model_paused" and len(env["seen"]) == 3  # nothing sent


def test_groq_outage_pauses_and_the_next_run_sends_nothing(db_session, env):
    _snapshot(db_session, env["inst"], GOLD, NOW - dt.timedelta(minutes=20))
    env["replies"].append(httpx.Response(503, json={"error": {"message": "down"}}))
    r = tasks.run(db_session, "market", "XAUUSD", now=NOW)
    assert r["status"] == "unavailable" and len(env["seen"]) == 1
    r = tasks.run(db_session, "market", "XAUUSD", now=NOW + dt.timedelta(seconds=30))
    assert r["status"] == "unavailable" and r["code"] == "paused" and len(env["seen"]) == 1


def test_broken_json_counts_as_one_failed_request_without_retry(db_session, env):
    _snapshot(db_session, env["inst"], GOLD, NOW - dt.timedelta(minutes=20))
    env["replies"].append(httpx.Response(200, json={"choices": [{"message": {"content": "nejde"}}]}))
    r = tasks.run(db_session, "market", "XAUUSD", now=NOW)
    assert r["status"] == "invalid" and len(env["seen"]) == 1
    assert db_session.query(AiUsage).filter(AiUsage.ok.is_(False)).count() == 1


def test_ai_off_sends_nothing_and_says_so(db_session, env):
    env["cfg"]["provider"] = "none"
    _snapshot(db_session, env["inst"], GOLD, NOW - dt.timedelta(minutes=20))
    r = tasks.run(db_session, "market", "XAUUSD", now=NOW)
    assert r["status"] == "unavailable" and r["code"] == "off" and env["seen"] == []


def test_news_analysis_sends_only_headline_snippet_and_classification(db_session, env):
    item = NewsItem(source="FXStreet", dedup_hash="h1", title="Gold breaks 3,886 floor", url="https://example.com/a",
                    published_at=NOW, raw_snippet="Gold fell to 3,886 as Fed hawks press on. " * 30,
                    instrument_tags=["XAUUSD"], factor_tags=["fed"], sentiment="bearish")
    db_session.add(item)
    db_session.commit()
    out = {"shrnuti_cs": "Zlato kleslo pod 3 886.", "fakta_zpravy": [{"text": "Zlato pod 3,886.", "fakta": ["F1"]}],
           "vyklad": "Jestřábí Fed tlačí zlato dolů.", "dulezitost": "střední",
           "dopady": [{"instrument": "XAUUSD", "smer": "dolů", "horizont": "dny", "fakta": ["F1", "F4"]}]}
    env["replies"].append(_ok(out, model="openai/gpt-oss-20b"))
    r = tasks.run(db_session, "news", item_id=item.id, now=NOW)
    assert r["status"] == "ok", r
    sent = json.loads(json.loads(env["seen"][0].content)["messages"][1]["content"])["fakta"]
    snippet = next(f for f in sent if f["co"] == "Úryvek z RSS")["hodnota"]
    assert len(snippet) <= 400  # never the whole article
    assert tasks.run(db_session, "news", item_id=item.id, now=NOW + dt.timedelta(hours=1))["status"] == "cached"
    assert len(env["seen"]) == 1


# --- event-driven runs after the ingestion cycle (app/ai/triggers.py) ---------------------------

def _flip(card, **kw):
    c = copy.deepcopy(card)
    c.update(kw)
    return c


def test_automatic_analyses_are_off_by_default(db_session, env):
    from app.ai import triggers

    _snapshot(db_session, env["inst"], GOLD, NOW - dt.timedelta(minutes=30))
    _snapshot(db_session, env["inst"], _flip(GOLD, score10=4, bias="LONG"), NOW)
    assert triggers.after_cycle(db_session, now=NOW) == [] and env["seen"] == []


def test_only_significant_changes_reach_ai(db_session, env, monkeypatch):
    from app.ai import triggers

    monkeypatch.setattr(triggers, "TRADE_PER_DAY", 0)  # the complex analysis has its own test (test_ai_trade.py)
    env["cfg"]["auto_analyses"] = True
    _snapshot(db_session, env["inst"], GOLD, NOW - dt.timedelta(minutes=30))
    _snapshot(db_session, env["inst"], _flip(GOLD, score10=-4), NOW)  # one point: not significant
    assert triggers.after_cycle(db_session, now=NOW) == [] and env["seen"] == []
    _snapshot(db_session, env["inst"], _flip(GOLD, score10=2, bias="NEUTRÁLNÍ"), NOW + dt.timedelta(minutes=30))
    change = {"co_se_zmenilo": "BIAS SHORT → NEUTRÁLNÍ, skóre −4 → 2.", "proc": [], "co_sledovat": []}
    env["replies"].append(_ok(change, model="openai/gpt-oss-20b"))
    out = triggers.after_cycle(db_session, now=NOW + dt.timedelta(minutes=31))
    assert out == [{"task": "change", "code": "XAUUSD", "status": "ok"}] and len(env["seen"]) == 1
    rec = db_session.query(AnalysisRecord).filter_by(kind="ai_change").one()
    assert rec.question.startswith("automaticky: BIAS SHORT")
    assert triggers.after_cycle(db_session, now=NOW + dt.timedelta(minutes=35)) == [{"task": "change", "code": "XAUUSD",
                                                                                     "status": "cached"}]
    assert len(env["seen"]) == 1  # the same change is never sent twice


def test_briefing_runs_once_per_slot(db_session, env):
    from app.ai import triggers

    env["cfg"]["auto_analyses"] = True
    at = dt.datetime(2026, 11, 2, 6, 5, tzinfo=UTC)
    _snapshot(db_session, env["inst"], GOLD, at - dt.timedelta(minutes=30))
    rep = {"titulek": "Ranní přehled", "shrnuti": "Zlato SHORT (−3).", "trhy": [], "udalosti": [], "rizika": []}
    env["replies"].append(_ok(rep))
    assert triggers.after_cycle(db_session, now=at) == [{"task": "report", "code": None, "status": "ok"}]
    assert triggers.after_cycle(db_session, now=at + dt.timedelta(minutes=30)) == []
    assert len(env["seen"]) == 1


def test_automatic_analyses_run_with_gemini_as_the_main_provider(db_session, env):
    """9. 11. 2026: the trigger asked for ai.provider == "groq", so with Gemini first (the user's setting) nothing ran
    automatically. Any free provider counts; switched off stays off."""
    from app.ai import triggers

    env["cfg"]["auto_analyses"] = True
    env["cfg"]["provider"] = "gemini"
    at = dt.datetime(2026, 11, 2, 6, 5, tzinfo=UTC)
    _snapshot(db_session, env["inst"], GOLD, at - dt.timedelta(minutes=30))
    rep = {"titulek": "Ranní přehled", "shrnuti": "Zlato SHORT (−3).", "trhy": [], "udalosti": [], "rizika": []}
    env["replies"].append(_ok(rep))
    assert triggers.after_cycle(db_session, now=at) == [{"task": "report", "code": None, "status": "ok"}]
    env["cfg"]["provider"] = "none"
    assert triggers.after_cycle(db_session, now=at + dt.timedelta(hours=6)) == []


# --- API for the app ----------------------------------------------------------------------------

@pytest.fixture()
def client(db_session, env):
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import app

    app.dependency_overrides[get_session] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_status_endpoint_shows_state_usage_and_task_readiness_never_the_key(client, env):
    r = client.get("/api/ai/status").json()
    assert r["groq"]["state"] == "ready" and r["groq"]["usage"]["cap"] == 80 and r["groq"]["key_set"] is True
    ready = {t["id"]: t["ready"] for t in r["tasks"]}
    assert ready["market"] is True and ready["zones"] is False and ready["trade"] is True
    used = {p["id"]: p["used"] for p in r["providers"]}
    assert used["groq"] is True and used["openai"] is False and used["anthropic"] is False  # paid: never used
    assert KEY not in json.dumps(r) and KEY[-4:] not in json.dumps(r)


def test_connection_test_checks_key_then_one_tiny_answer(client, env, db_session):
    env["replies"] += [httpx.Response(200, json={"data": [{"id": "openai/gpt-oss-20b"}, {"id": "openai/gpt-oss-120b"}]}),
                       httpx.Response(200, headers={"x-ratelimit-limit-requests": "1000", "x-ratelimit-limit-tokens": "8000"},
                                      json={"model": "openai/gpt-oss-20b", "usage": {"prompt_tokens": 12, "completion_tokens": 3},
                                            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]})]
    env["cfg"]["provider"] = "none"  # the test works before AI is switched on
    r = client.post("/api/ai/test").json()
    assert r["ok"] is True and r["limits"]["requests_per_day"] == 1000 and set(r["models"]) == {"openai/gpt-oss-20b",
                                                                                               "openai/gpt-oss-120b"}
    assert json.loads(env["seen"][1].content)["max_completion_tokens"] == 64
    assert db_session.query(AiUsage).count() == 1  # the model list costs nothing, the answer is 1 request


def test_models_the_account_does_not_have_are_never_tried(db_session, env):
    from app.ai import guard as g

    g.remember_available(["openai/gpt-oss-120b", "openai/gpt-oss-20b"])
    _snapshot(db_session, env["inst"], GOLD, NOW - dt.timedelta(minutes=20))
    env["replies"] += [httpx.Response(429, headers={"retry-after": "60"}, json={})] * 2
    r = tasks.run(db_session, "market", "XAUUSD", now=NOW)
    models = [json.loads(s.content)["model"] for s in env["seen"]]
    assert r["status"] == "unavailable" and models == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]  # no llama


def test_analyze_endpoint_goes_through_the_same_guard(client, env):
    assert client.post("/api/ai/analyze", json={"task": "zones", "code": "XAUUSD"}).json()["status"] == "not_ready"
    env["cfg"]["provider"] = "none"
    r = client.post("/api/ai/analyze", json={"task": "market", "code": "xauusd"}).json()
    assert r["status"] in ("unavailable", "not_ready") and env["seen"] == []
    assert client.get("/api/ai/analyses?code=XAUUSD").json() == {"analyses": []}
