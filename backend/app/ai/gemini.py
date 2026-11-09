"""Google Gemini API — FREE tier only (an AI Studio key WITHOUT a billing account; the user's rule: 0 Kč).

Without billing Google cannot charge anything: an exhausted free quota answers HTTP 429 (RESOURCE_EXHAUSTED) and FTI
then pauses the model and falls back to Groq Free — never to a paid provider. The reply has the same shape as Groq's
(groq.GroqReply / groq.GroqError), so the guard and the router treat both providers alike.

Terms checked 9. 11. 2026 (aistudio.google.com/docs/terms, effective 23. 3. 2026): "You may use only Paid Services when
making API Clients available to users in the European Economic Area, Switzerland, or the United Kingdom" — the user was
told; it is a question of the terms, not of money (no billing = no charge). For EEA users Google applies the paid-service
data terms to unpaid quota too (prompts are not used to improve Google's products).
"""

from __future__ import annotations

import json
import re
import time

import httpx

from app.ai.groq import GroqError, GroqReply
from app.data import secrets

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
KEY_NAME = "GEMINI_API_KEY"
# Flash models of the free tier: the "-latest" aliases follow Google's current Flash / Flash-Lite; the connection test
# lists the models the key really offers (list_models) and FTI asks only those
FREE_MODELS = {
    "gemini-flash-latest": {"tier": "strong"},
    "gemini-flash-lite-latest": {"tier": "fast"},
}
TIMEOUT = httpx.Timeout(60.0, connect=5.0)
_transport: httpx.BaseTransport | None = None  # tests inject a mock
_DELAY = re.compile(r"^(\d+(?:\.\d+)?)s$")


def _key() -> str:
    key = secrets.get(KEY_NAME)
    if not key:
        raise GroqError("no_key", "Klíč GEMINI_API_KEY není nastavený.")
    return key


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=TIMEOUT, transport=_transport, follow_redirects=False,
                        headers={"User-Agent": "FTI/1.0 (personal analysis)"})


def _retry_after(err: dict) -> float | None:
    for d in err.get("details") or []:
        m = _DELAY.match(str(d.get("retryDelay") or ""))
        if m:
            return float(m.group(1))
    return None


def _error(r: httpx.Response) -> GroqError:
    try:
        err = (r.json() or {}).get("error") or {}
    except ValueError:
        err = {}
    detail, status, s = str(err.get("message") or ""), str(err.get("status") or ""), r.status_code
    if s == 429 or status == "RESOURCE_EXHAUSTED":
        return GroqError("rate_limit", "Bezplatný limit Gemini je teď vyčerpaný.", s, retry_after=_retry_after(err))
    if s == 400 and ("API key" in detail or status == "INVALID_ARGUMENT" and "key" in detail.lower()):
        return GroqError("auth", "Gemini odmítl klíč (je neplatný).", s)
    if s in (401, 403):
        if "billing" in detail.lower():
            return GroqError("billing", "Gemini hlásí platbu — AI se zastavuje, FTI nic placeného nepoužije.", s)
        return GroqError("auth", "Gemini odmítl klíč nebo projekt nemá přístup.", s)
    if s == 404:
        return GroqError("model", "Model u Gemini není dostupný.", s)
    if s in (400, 422):
        return GroqError("bad_request", f"Gemini dotaz odmítl: {detail[:200]}", s)
    return GroqError("unavailable", f"Gemini teď nefunguje (chyba {s}).", s)


def _body(messages: list[dict], max_tokens: int, schema: dict | None, temperature: float, schema_in_prompt: bool) -> dict:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    if schema is not None and schema_in_prompt:
        system += "\n\nSchéma odpovědi (JSON Schema):\n" + json.dumps(schema, ensure_ascii=False)
    contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages if m["role"] != "system"]
    config: dict = {"temperature": temperature, "maxOutputTokens": int(max_tokens)}
    if schema is not None:
        config["responseMimeType"] = "application/json"
        if not schema_in_prompt:
            config["responseJsonSchema"] = schema
    body: dict = {"contents": contents, "generationConfig": config}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    return body


def chat(messages: list[dict], model: str, max_tokens: int, schema: dict | None = None, schema_name: str = "fti_odpoved",
         temperature: float = 0.2) -> GroqReply:
    """One request (a schema the API rejects is retried once inside the prompt). Raises GroqError."""
    if model not in FREE_MODELS:
        raise ValueError(f"Model {model} není na seznamu bezplatných modelů FTI.")
    key = _key()
    t0 = time.monotonic()
    r = None
    for schema_in_prompt in ((False, True) if schema is not None else (False,)):
        try:
            with _client() as c:
                r = c.post(f"/models/{model}:generateContent", headers={"x-goog-api-key": key},
                           json=_body(messages, max_tokens, schema, temperature, schema_in_prompt))
        except httpx.TimeoutException:
            raise GroqError("unavailable", "Gemini neodpověděl včas.") from None
        except httpx.HTTPError as exc:
            raise GroqError("unavailable", f"Gemini není dostupný ({type(exc).__name__}).") from None
        if r.status_code == 400 and not schema_in_prompt and schema is not None and "schema" in r.text.lower():
            continue  # the API did not accept this JSON Schema: the same schema inside the prompt
        break
    if r.status_code != 200:
        raise _error(r)
    try:
        data = r.json()
        cand = data["candidates"][0]
        text = "".join(p.get("text") or "" for p in (cand.get("content") or {}).get("parts") or [])
        usage = data.get("usageMetadata") or {}
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise GroqError("invalid_output", "Gemini vrátil odpověď v neočekávaném tvaru.") from None
    finish = cand.get("finishReason")
    content: dict | str = text
    if schema is not None:
        try:
            content = json.loads(text)
        except ValueError:
            raise GroqError("invalid_output", "Odpověď AI není platný JSON" + (" (useknutá)" if finish == "MAX_TOKENS" else "") + ".") from None
        if not isinstance(content, dict):
            raise GroqError("invalid_output", "Odpověď AI není objekt JSON.")
    out_tokens = int(usage.get("candidatesTokenCount") or 0) + int(usage.get("thoughtsTokenCount") or 0)
    return GroqReply(str(data.get("modelVersion") or model), content, time.monotonic() - t0, int(usage.get("promptTokenCount") or 0),
                     out_tokens, {}, finish)


def list_models() -> list[str]:
    """The models this key offers (ids without the "models/" prefix) — to ask only those."""
    key = _key()
    try:
        with _client() as c:
            r = c.get("/models", params={"pageSize": 200}, headers={"x-goog-api-key": key})
    except httpx.HTTPError as exc:
        raise GroqError("unavailable", f"Gemini není dostupný ({type(exc).__name__}).") from None
    if r.status_code != 200:
        raise _error(r)
    return [str(m.get("name", "")).removeprefix("models/") for m in (r.json() or {}).get("models") or []]

