import httpx
import pytest

from app.ai import provider
from app.data import settings_store


def _settings(monkeypatch, ai: dict):
    monkeypatch.setattr(settings_store, "get", lambda path, default=None: ai if path == "ai" else default)


def test_without_a_free_model_the_ai_says_so_and_never_calls_anything(monkeypatch):
    _settings(monkeypatch, {"provider": "none"})
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("no request may be sent"))
    with pytest.raises(provider.AIUnavailable, match="rozbor sestavený z výpočtů"):
        provider.complete("s", "p")


def test_local_model_reply_is_validated_against_the_schema(monkeypatch):
    _settings(monkeypatch, {"provider": "ollama", "local_model": "qwen2.5:7b"})
    sent = {}

    class R:
        def __init__(self, content):
            self._c = content

        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": self._c}, "prompt_eval_count": 10, "eval_count": 5}

    def ok_post(url, json, timeout):
        sent.update(json)
        return R('{"preferred": "NO TRADE", "reasons": ["konflikt"]}')

    monkeypatch.setattr(httpx, "post", ok_post)
    schema = {"type": "object", "required": ["preferred", "reasons"]}
    res = provider.complete("s", "p", schema=schema)
    assert res.content["preferred"] == "NO TRADE" and res.provider == "ollama"
    assert sent["format"] == schema and sent["model"] == "qwen2.5:7b"
    assert sent["messages"][0]["role"] == "system"

    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: R('{"preferred": "LONG"}'))
    with pytest.raises(provider.AIUnavailable, match="chybí pole"):
        provider.complete("s", "p", schema=schema)


def test_only_free_providers_exist():
    import inspect

    src = inspect.getsource(provider)
    for paid in ("api.anthropic.com", "api.openai.com", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        assert paid not in src
