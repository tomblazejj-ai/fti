"""Gemini Free first, Groq Free as the backup (user's order 9. 11. 2026): the Gemini client (no billing, 429 = limit
exhausted, a schema the API rejects goes into the prompt), the router asks Gemini first and Groq after a 429, both
exhausted → NO TRADE "AI nedostupná" — never a paid provider —, one daily cap over every AI call, and the counter."""

import datetime as dt
import json

import httpx
import pytest

from app.ai import gemini, groq, guard, router
from app.data import secrets, settings_store

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
KEYS = {"GEMINI_API_KEY": "AIza" + "x" * 35, "GROQ_API_KEY": "gsk_" + "Tr4d" * 10}


@pytest.fixture()
def env(monkeypatch, db_session):
    cfg = {"provider": "gemini", "daily_request_cap": 80, "daily_token_cap": 100000, "per_minute_cap": 6}
    monkeypatch.setattr(settings_store, "get", lambda path, default=None: cfg if path == "ai" else default)
    monkeypatch.setattr(secrets, "get", lambda name: KEYS.get(name, ""))
    guard.reset_memory()
    state = {"gemini": [], "groq": [], "sent": []}

    def gem(request):
        state["sent"].append(("gemini", request.url.path, json.loads(request.content or b"{}")))
        return state["gemini"].pop(0)

    def grq(request):
        state["sent"].append(("groq", request.url.path, json.loads(request.content or b"{}")))
        return state["groq"].pop(0)

    monkeypatch.setattr(gemini, "_transport", httpx.MockTransport(gem))
    monkeypatch.setattr(groq, "_transport", httpx.MockTransport(grq))
    yield state, cfg
    guard.reset_memory()


def _gem_ok(obj, model="gemini-2.5-flash"):
    return httpx.Response(200, json={"modelVersion": model, "usageMetadata": {"promptTokenCount": 900, "candidatesTokenCount": 200},
                                     "candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}, "finishReason": "STOP"}]})


def _gem_429():
    return httpx.Response(429, json={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded",
                                               "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}]}})


def _groq_ok(obj):
    return httpx.Response(200, json={"model": "openai/gpt-oss-20b", "usage": {"prompt_tokens": 900, "completion_tokens": 300},
                                     "choices": [{"message": {"content": json.dumps(obj)}, "finish_reason": "stop"}]})


SCHEMA = {"type": "object", "properties": {"zaver": {"type": "string"}}, "required": ["zaver"], "additionalProperties": False}
MSGS = [{"role": "system", "content": "Jsi analytik."}, {"role": "user", "content": "Fakta: …"}]


def test_gemini_client_sends_system_schema_and_reads_the_answer(env):
    state, _ = env
    state["gemini"].append(_gem_ok({"zaver": "OK"}))
    r = gemini.chat(MSGS, "gemini-flash-latest", 500, schema=SCHEMA)
    assert r.content == {"zaver": "OK"} and (r.tokens_in, r.tokens_out) == (900, 200)
    _, path, body = state["sent"][0]
    assert path.endswith("/models/gemini-flash-latest:generateContent")
    assert body["systemInstruction"]["parts"][0]["text"] == "Jsi analytik." and body["contents"][0]["role"] == "user"
    assert body["generationConfig"]["responseMimeType"] == "application/json" and body["generationConfig"]["responseJsonSchema"] == SCHEMA
    with pytest.raises(ValueError):
        gemini.chat(MSGS, "gemini-2.5-pro", 500)  # not on FTI's free list: never asked


def test_a_rejected_schema_goes_into_the_prompt(env):
    state, _ = env
    state["gemini"] += [httpx.Response(400, json={"error": {"message": "Invalid JSON schema: additionalProperties"}}),
                        _gem_ok({"zaver": "OK"})]
    assert gemini.chat(MSGS, "gemini-flash-latest", 500, schema=SCHEMA).content == {"zaver": "OK"}
    second = state["sent"][1][2]
    assert "responseJsonSchema" not in second["generationConfig"] and "JSON Schema" in second["systemInstruction"]["parts"][0]["text"]


def test_429_is_the_free_limit_with_its_wait(env):
    state, _ = env
    state["gemini"].append(_gem_429())
    with pytest.raises(groq.GroqError) as e:
        gemini.chat(MSGS, "gemini-flash-latest", 500)
    assert e.value.kind == "rate_limit" and e.value.retry_after == 37.0 and "Gemini" in str(e.value)


def test_router_asks_gemini_first_and_groq_after_its_429(env, db_session):
    state, _ = env
    assert [c.provider for c in router.candidates("synteza")][:2] == ["gemini", "gemini"]
    state["gemini"].append(_gem_ok({"zaver": "OK"}))
    r = router.run_role(db_session, "synteza", MSGS, 500, 1500, SCHEMA, "trade", now=NOW, sleep=lambda s: None)
    assert r.provider == "gemini"
    state["gemini"] += [_gem_429(), _gem_429()]  # both Gemini models out of free quota
    state["groq"].append(_groq_ok({"zaver": "OK"}))
    r = router.run_role(db_session, "synteza", MSGS, 500, 1500, SCHEMA, "trade", now=NOW, sleep=lambda s: None)
    assert r.provider == "groq" and [a["result"] for a in r.attempts][-1] == "ok"
    assert all(s[0] in ("gemini", "groq") for s in state["sent"])  # only the two free providers were ever called


def test_both_limits_gone_means_no_trade_never_a_paid_provider(env, db_session, monkeypatch):
    from app.ai import pipeline

    state, _ = env
    state["gemini"] += [_gem_429()] * 4
    state["groq"] += [httpx.Response(429, json={"error": {"message": "rate limit"}}, headers={"retry-after": "60"})] * 4
    with pytest.raises(router.RoleUnavailable):
        router.run_role(db_session, "synteza", MSGS, 500, 1500, SCHEMA, "trade", now=NOW, sleep=lambda s: None)
    assert not [p for p in router.PROVIDERS.values() if not p.free and router.usable(p)[0]]  # paid ones are never usable
    monkeypatch.setattr(pipeline.context, "trade", lambda *a, **k: ([{"id": "F1", "co": "x", "hodnota": 1}],
                                                                      {"instrument": "XAUUSD", "missing": []}))
    monkeypatch.setattr(pipeline.router, "run_role", lambda *a, **k: (_ for _ in ()).throw(router.RoleUnavailable("makro", "limit")))
    r = pipeline.run(db_session, "XAUUSD", now=NOW)
    assert r["status"] == "unavailable" and r["no_trade"] and r["text"].startswith("NO TRADE — AI nedostupná")


def test_one_daily_cap_over_every_ai_call_and_the_counter(env, db_session):
    state, cfg = env
    cfg["daily_request_cap"] = 5
    for _ in range(2):
        state["gemini"].append(_gem_ok({"zaver": "OK"}))
        router.run_role(db_session, "synteza", MSGS, 500, 1500, SCHEMA, "trade", priority="high", now=NOW, sleep=lambda s: None)
    state["gemini"] += [_gem_429(), _gem_429()]  # both Gemini models out of quota → Groq
    state["groq"].append(_groq_ok({"zaver": "OK"}))
    router.run_role(db_session, "synteza", MSGS, 500, 1500, SCHEMA, "trade", priority="high", now=NOW, sleep=lambda s: None)
    st = guard.status(db_session, NOW)
    assert st["calls_cap"] == 5 and st["calls_today"] == 5  # Gemini and Groq counted together (the failed 429s too)
    with pytest.raises(router.RoleUnavailable) as e:
        router.run_role(db_session, "synteza", MSGS, 500, 1500, SCHEMA, "trade", priority="high", now=NOW, sleep=lambda s: None)
    assert "limit" in str(e.value).lower() or "strop" in str(e.value).lower()
    assert st["order"] == ["gemini", "groq"] and "Gemini Free → Groq Free" in guard.status(db_session, NOW + dt.timedelta(days=1))["text"]
