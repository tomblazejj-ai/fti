"""Groq client (app/ai/groq.py): no real key and no network — a mock Groq server answers.
Covers the key handling (env, .env, never shown), the request FTI sends, parsing of answers and
rate-limit headers, and every error kind the guard reacts to."""

import importlib.util
import json
import logging
from pathlib import Path

import httpx
import pytest

from app.ai import groq, redact
from app.data import secrets

FAKE_KEY = "gsk_" + "T3st" * 10


@pytest.fixture()
def key(monkeypatch):
    monkeypatch.setattr(secrets, "get", lambda name: FAKE_KEY if name == "GROQ_API_KEY" else "")


def _serve(monkeypatch, handler):
    seen = []

    def wrapped(request: httpx.Request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(groq, "_transport", httpx.MockTransport(wrapped))
    return seen


def _ok(content, headers=None, model="openai/gpt-oss-20b"):
    body = {"model": model, "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 40}}
    return httpx.Response(200, json=body, headers=headers or {})


def _fresh_secrets(tmp_path: Path):
    """A separate copy of app/data/secrets.py (the shared one is stubbed by conftest), pointed at a temp .env."""
    spec = importlib.util.spec_from_file_location("secrets_copy", Path(secrets.__file__))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ENV_FILE = tmp_path / ".env"
    return mod


def test_key_comes_from_environment_first_then_env_file(tmp_path, monkeypatch):
    s = _fresh_secrets(tmp_path)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert s.get("GROQ_API_KEY") == ""
    s.set_key("GROQ_API_KEY", FAKE_KEY)
    assert s.get("GROQ_API_KEY") == FAKE_KEY and f"GROQ_API_KEY={FAKE_KEY}" in s.ENV_FILE.read_text(encoding="utf-8")
    other = "gsk_" + "Env0" * 10
    monkeypatch.setenv("GROQ_API_KEY", other)
    assert s.get("GROQ_API_KEY") == other


def test_key_is_never_shown_not_even_its_end(tmp_path):
    s = _fresh_secrets(tmp_path)
    s.set_key("GROQ_API_KEY", FAKE_KEY)
    row = next(r for r in s.status() if r["name"] == "GROQ_API_KEY")
    assert row["set"] is True and row["hint"] is None
    assert FAKE_KEY not in json.dumps(s.status()) and FAKE_KEY[-4:] not in json.dumps(row)


def test_a_wrong_paste_is_refused_and_empty_value_removes_the_key(tmp_path):
    s = _fresh_secrets(tmp_path)
    for bad in ("sk-proj-abcdefghijklmnopqrstuvwxyz", "gsk_short", "gsk_" + "a" * 30 + " x"):
        with pytest.raises(ValueError):
            s.set_key("GROQ_API_KEY", bad)
    s.set_key("GROQ_API_KEY", FAKE_KEY)
    s.set_key("GROQ_API_KEY", "")
    assert s.get("GROQ_API_KEY") == ""


def test_request_goes_only_to_groq_with_a_free_model_and_capped_tokens(monkeypatch, key):
    seen = _serve(monkeypatch, lambda r: _ok(json.dumps({"a": 1})))
    reply = groq.chat([{"role": "user", "content": "x"}], "openai/gpt-oss-20b", 300, schema={"type": "object"})
    req = seen[0]
    body = json.loads(req.content)
    assert str(req.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {FAKE_KEY}"
    assert body["model"] == "openai/gpt-oss-20b" and body["max_completion_tokens"] == 300 and body["stream"] is False
    assert body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["strict"] is True
    assert body["reasoning_effort"] == "low"
    assert "service_tier" not in body  # never the paid Flex / Batch tiers
    assert reply.content == {"a": 1} and reply.tokens_in == 120 and reply.tokens_out == 40


def test_model_outside_the_free_list_is_refused_without_any_request(monkeypatch, key):
    seen = _serve(monkeypatch, lambda r: _ok("{}"))
    with pytest.raises(ValueError):
        groq.chat([{"role": "user", "content": "x"}], "some-paid-model", 100)
    assert seen == []


def test_no_key_means_no_request(monkeypatch):
    seen = _serve(monkeypatch, lambda r: _ok("{}"))
    with pytest.raises(groq.GroqError) as e:
        groq.chat([{"role": "user", "content": "x"}], "openai/gpt-oss-20b", 100)
    assert e.value.kind == "no_key" and seen == []


def test_rate_limit_headers_are_read():
    lim = groq.parse_limits({"x-ratelimit-limit-requests": "1000", "x-ratelimit-remaining-requests": "998",
                             "x-ratelimit-reset-requests": "2m59.56s", "x-ratelimit-limit-tokens": "8000",
                             "x-ratelimit-remaining-tokens": "7400", "x-ratelimit-reset-tokens": "7.66s"})
    assert lim == {"requests_per_day": 1000, "requests_left_today": 998, "requests_reset_s": pytest.approx(179.56),
                   "tokens_per_minute": 8000, "tokens_left_minute": 7400, "tokens_reset_s": pytest.approx(7.66)}
    assert groq.seconds("1h2m3s") == 3723 and groq.seconds("120ms") == pytest.approx(0.12) and groq.seconds("bad") is None


@pytest.mark.parametrize("status,kind", [(401, "auth"), (403, "auth"), (402, "billing"), (413, "too_large"), (404, "model"),
                                         (400, "bad_request"), (500, "unavailable"), (503, "unavailable"), (498, "unavailable")])
def test_every_error_status_maps_to_a_kind(monkeypatch, key, status, kind):
    _serve(monkeypatch, lambda r: httpx.Response(status, json={"error": {"message": "x", "type": "invalid_request_error"}}))
    with pytest.raises(groq.GroqError) as e:
        groq.chat([{"role": "user", "content": "x"}], "openai/gpt-oss-20b", 100)
    assert e.value.kind == kind and e.value.status == status


def test_429_carries_retry_after_and_the_limits(monkeypatch, key):
    _serve(monkeypatch, lambda r: httpx.Response(429, json={"error": {"message": "Rate limit reached"}},
                                                 headers={"retry-after": "37", "x-ratelimit-remaining-requests": "0"}))
    with pytest.raises(groq.GroqError) as e:
        groq.chat([{"role": "user", "content": "x"}], "openai/gpt-oss-20b", 100)
    assert e.value.kind == "rate_limit" and e.value.retry_after == 37 and e.value.limits["requests_left_today"] == 0


def test_timeout_and_network_errors_are_unavailable(monkeypatch, key):
    def boom(r):
        raise httpx.ReadTimeout("slow", request=r)

    _serve(monkeypatch, boom)
    with pytest.raises(groq.GroqError) as e:
        groq.chat([{"role": "user", "content": "x"}], "openai/gpt-oss-20b", 100)
    assert e.value.kind == "unavailable"


def test_broken_or_non_json_answer_is_invalid_output(monkeypatch, key):
    _serve(monkeypatch, lambda r: _ok("tohle není JSON"))
    with pytest.raises(groq.GroqError) as e:
        groq.chat([{"role": "user", "content": "x"}], "openai/gpt-oss-20b", 100, schema={"type": "object"})
    assert e.value.kind == "invalid_output"


def test_llama_fallback_uses_json_object_mode(monkeypatch, key):
    seen = _serve(monkeypatch, lambda r: _ok('{"b": 2}', model="llama-3.3-70b-versatile"))
    groq.chat([{"role": "user", "content": "x"}], "llama-3.3-70b-versatile", 100, schema={"type": "object"})
    body = json.loads(seen[0].content)
    assert body["response_format"] == {"type": "json_object"} and "reasoning_effort" not in body


def test_connection_test_lists_models_without_tokens(monkeypatch, key):
    seen = _serve(monkeypatch, lambda r: httpx.Response(200, json={"data": [{"id": "openai/gpt-oss-120b"}]}))
    assert groq.list_models() == ["openai/gpt-oss-120b"]
    assert seen[0].method == "GET" and str(seen[0].url).endswith("/openai/v1/models")


def test_key_never_appears_in_errors_or_logs(caplog):
    redact.install_log_filter()
    err = groq.GroqError("bad_request", f"Groq dotaz odmítl: invalid key {FAKE_KEY}")
    assert FAKE_KEY not in str(err)
    with caplog.at_level(logging.INFO):
        logging.getLogger("fti.test").info("Authorization: Bearer %s", FAKE_KEY)
    assert FAKE_KEY not in caplog.text and "[skryto]" in caplog.text


def test_no_groq_key_is_tracked_by_git_and_env_is_ignored():
    import re
    import subprocess

    root = Path(__file__).resolve().parents[2]
    assert "backend/.env" in (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    try:
        files = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git není k dispozici")
    assert "backend/.env" not in files
    rx = re.compile(r"gsk_[A-Za-z0-9]{20,}")
    leaks = [f for f in files if (root / f).is_file() and (root / f).stat().st_size < 2_000_000
             and rx.search((root / f).read_text(encoding="utf-8", errors="ignore"))]
    assert leaks == []


def test_only_groqs_free_api_and_production_models_are_known():
    assert groq.BASE_URL == "https://api.groq.com/openai/v1"
    assert set(groq.FREE_MODELS) == {"openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"}
    src = "\n".join(p.read_text(encoding="utf-8") for p in Path(groq.__file__).parent.glob("*.py"))
    for paid in ('"service_tier"', "/batches", "/billing", "/files"):  # no paid tier, batch job or billing call anywhere
        assert paid not in src
