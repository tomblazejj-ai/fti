"""Groq Free — the main AI of FTI, through Groq's official OpenAI-compatible API.

Only the free plan: FTI never calls anything about billing, never asks for the paid processing
tiers (Batch, Flex) and only uses models from FREE_MODELS. The key comes from GROQ_API_KEY
(environment or backend/.env) and is never logged, returned or shown.

This module only talks to Groq. Limits, pauses after HTTP 429, the daily cap, caching and
cooldowns live in app/ai/guard.py — nothing here retries or loops.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

import httpx

from app.ai.redact import redact
from app.data import secrets

BASE_URL = "https://api.groq.com/openai/v1"
KEY_NAME = "GROQ_API_KEY"
# Production models (console.groq.com/docs/models, checked 2026-11-01). Preview models can be
# discontinued at short notice and are not used. strict = constrained JSON-schema decoding.
FREE_MODELS = {
    "openai/gpt-oss-120b": {"strict": True, "reasoning": True},
    "openai/gpt-oss-20b": {"strict": True, "reasoning": True},
    "llama-3.3-70b-versatile": {"strict": False, "reasoning": False},
}
TERMS_CHECKED = "2026-11-01"
TIMEOUT = httpx.Timeout(45.0, connect=5.0)
_transport: httpx.BaseTransport | None = None  # tests inject an httpx.MockTransport


class GroqError(RuntimeError):
    """kind: no_key | auth | billing | rate_limit | unavailable | bad_request | too_large | model | invalid_output"""

    def __init__(self, kind: str, message: str, status: int | None = None, retry_after: float | None = None,
                 limits: dict | None = None):
        super().__init__(redact(message))
        self.kind = kind
        self.status = status
        self.retry_after = retry_after
        self.limits = limits or {}


@dataclass
class GroqReply:
    model: str
    content: dict | str
    seconds: float
    tokens_in: int = 0
    tokens_out: int = 0
    limits: dict = field(default_factory=dict)
    finish_reason: str | None = None


_DURATION = re.compile(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?$")


def seconds(value) -> float | None:
    """Groq's reset times look like '2m59.56s', '7.66s', '1h2m3s' or '120ms'; retry-after is plain seconds."""
    if value is None:
        return None
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    m = _DURATION.match(text)
    if not m or not any(m.groups()):
        return None
    h, mi, s, ms = (float(x) if x else 0.0 for x in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000


def parse_limits(headers) -> dict:
    """The organisation's real limits as Groq reports them in every answer (requests are per day, tokens per minute)."""
    def num(name: str) -> int | None:
        try:
            return int(float(headers[name])) if headers.get(name) is not None else None
        except ValueError:
            return None

    out = {"requests_per_day": num("x-ratelimit-limit-requests"), "requests_left_today": num("x-ratelimit-remaining-requests"),
           "requests_reset_s": seconds(headers.get("x-ratelimit-reset-requests")),
           "tokens_per_minute": num("x-ratelimit-limit-tokens"), "tokens_left_minute": num("x-ratelimit-remaining-tokens"),
           "tokens_reset_s": seconds(headers.get("x-ratelimit-reset-tokens"))}
    return {k: v for k, v in out.items() if v is not None}


def _key() -> str:
    key = secrets.get(KEY_NAME)
    if not key:
        raise GroqError("no_key", "Klíč GROQ_API_KEY není nastavený.")
    return key


def _error(r: httpx.Response, limits: dict) -> GroqError:
    try:
        detail = ((r.json() or {}).get("error") or {}).get("message") or ""
    except ValueError:
        detail = ""
    s = r.status_code
    if s in (401, 403):
        return GroqError("auth", "Groq odmítl klíč (je neplatný nebo zablokovaný).", s, limits=limits)
    if s == 402:
        return GroqError("billing", "Groq hlásí platbu — AI se zastavuje, FTI nic placeného nepoužije.", s, limits=limits)
    if s == 429:
        return GroqError("rate_limit", "Bezplatný limit Groq je teď vyčerpaný.", s, retry_after=seconds(r.headers.get("retry-after")),
                         limits=limits)
    if s == 413:
        return GroqError("too_large", "Dotaz je pro Groq moc velký.", s, limits=limits)
    if s == 404:
        return GroqError("model", "Model u Groq není dostupný.", s, limits=limits)
    if s in (400, 422) and ("failed_generation" in detail or "does not match the expected schema" in detail):
        # strict JSON decoding: the model's answer broke the schema (often cut off) — an invalid answer, not a bad request
        return GroqError("invalid_output", "Odpověď modelu neodpovídala schématu (pravděpodobně byla useknutá).", s, limits=limits)
    if s in (400, 422):
        return GroqError("bad_request", f"Groq dotaz odmítl: {detail[:200]}", s, limits=limits)
    return GroqError("unavailable", f"Groq teď nefunguje (chyba {s}).", s, limits=limits)


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=TIMEOUT, transport=_transport, follow_redirects=False,
                        headers={"User-Agent": "FTI/1.0 (personal analysis)"})


def chat(messages: list[dict], model: str, max_tokens: int, schema: dict | None = None, schema_name: str = "fti_odpoved",
         temperature: float = 0.2) -> GroqReply:
    """One request — no retry here. Raises GroqError (the guard decides what happens next)."""
    if model not in FREE_MODELS:
        raise ValueError(f"Model {model} není na seznamu bezplatných modelů FTI.")
    key = _key()
    spec = FREE_MODELS[model]
    body: dict = {"model": model, "messages": messages, "temperature": temperature, "max_completion_tokens": int(max_tokens),
                  "stream": False}
    if spec["reasoning"]:
        body["reasoning_effort"] = "low"  # gpt-oss: fewer reasoning tokens = less of the free daily budget
    if schema is not None:
        body["response_format"] = ({"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}}
                                   if spec["strict"] else {"type": "json_object"})
    t0 = time.monotonic()
    try:
        with _client() as c:
            r = c.post("/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"})
    except httpx.TimeoutException:
        raise GroqError("unavailable", "Groq neodpověděl včas.") from None
    except httpx.HTTPError as exc:
        raise GroqError("unavailable", f"Groq není dostupný ({type(exc).__name__}).") from None
    limits = parse_limits(r.headers)
    if r.status_code != 200:
        raise _error(r, limits)
    try:
        data = r.json()
        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
        usage = data.get("usage") or {}
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise GroqError("invalid_output", "Groq vrátil odpověď v neočekávaném tvaru.", limits=limits) from None
    content: dict | str = text
    if schema is not None:
        try:
            content = json.loads(text)
        except ValueError:
            raise GroqError("invalid_output", "Odpověď AI není platný JSON.", limits=limits) from None
        if not isinstance(content, dict):
            raise GroqError("invalid_output", "Odpověď AI není objekt JSON.", limits=limits)
    return GroqReply(str(data.get("model") or model), content, time.monotonic() - t0, int(usage.get("prompt_tokens") or 0),
                     int(usage.get("completion_tokens") or 0), limits, choice.get("finish_reason"))


def list_models() -> list[str]:
    """Checks the key without using any tokens (the connection test)."""
    key = _key()
    try:
        with _client() as c:
            r = c.get("/models", headers={"Authorization": f"Bearer {key}"})
    except httpx.TimeoutException:
        raise GroqError("unavailable", "Groq neodpověděl včas.") from None
    except httpx.HTTPError as exc:
        raise GroqError("unavailable", f"Groq není dostupný ({type(exc).__name__}).") from None
    if r.status_code != 200:
        raise _error(r, parse_limits(r.headers))
    try:
        return [m["id"] for m in r.json().get("data", [])]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise GroqError("invalid_output", "Groq vrátil seznam modelů v neočekávaném tvaru.") from None
