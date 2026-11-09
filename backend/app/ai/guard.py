"""The AI guard — FTI's own protection on top of Groq Free. Every AI request goes through here.

  * at most 80 requests per UTC day (hard ceiling; settings can only lower it) — failed ones count too
  * at most 6 requests a minute, and a request is not sent if it would take the last minute past 90 % of Groq's
    tokens-per-minute (Groq answers 429 at 100 %)
  * at most ai.daily_token_cap tokens a day (default 100 000 — half of what Groq lists for gpt-oss)
  * the last 20 % of the daily cap is kept for high-priority events
  * HTTP 429: no request to that model until Groq's retry-after / reset time
  * outage (5xx, timeout): pause 1 → 5 → 15 → 60 minutes (circuit breaker)
  * key rejected (401/403): AI stays off until the key changes; payment demanded (402): off until re-enabled
  * every attempt is a row in ai_usage and the pauses are stored in the database, so a restart resets nothing

Nothing here retries or loops: a refused request is simply not sent, and the caller shows why.
"""

from __future__ import annotations

import contextlib
import copy
import datetime as dt
import hashlib
import threading

from sqlalchemy import case, func, select

from app.ai import gemini, groq
from app.data import secrets, settings_store, store

UTC = dt.timezone.utc
HARD_DAILY_CAP = 80
HARD_TOKEN_CAP = 150_000
HARD_PER_MINUTE = 10
RESERVE_SHARE = 0.2
TPM_SHARE = 0.9
BREAKER_MINUTES = (1, 5, 15, 60)
STATE_KEY = "ai:guard"
PROVIDER = "groq"
FREE_PROVIDERS = ("gemini", "groq")  # the only providers FTI may call (0 Kč); the setting ai.provider says which goes first
KEY_NAMES = {"gemini": gemini.KEY_NAME, "groq": groq.KEY_NAME}


def provider_of(model: str) -> str:
    return "gemini" if model in gemini.FREE_MODELS else "groq"

REASONS = {
    "off": "AI je vypnutá v nastavení — FTI ukazuje rozbor z pravidel.",
    "no_key": "Klíč GROQ_API_KEY není nastavený.",
    "auth": "Groq odmítl klíč. AI zůstane vypnutá, dokud neuložíš nový klíč.",
    "billing": "Groq požadoval platbu. AI je zastavená — FTI nic placeného nepoužije. Zkontroluj tarif v konzoli Groq.",
    "paused": "Groq teď neodpovídá — AI má přestávku.",
    "model_paused": "Bezplatný limit tohoto modelu je vyčerpaný.",
    "daily_cap": "Denní limit FTI pro AI je vyčerpaný.",
    "reserve": "Zbytek denního limitu je vyhrazený pro důležité události.",
    "token_cap": "Denní limit tokenů FTI je vyčerpaný.",
    "minute": "Limit dotazů za minutu — za chvíli to půjde znovu.",
}


class Blocked(RuntimeError):
    def __init__(self, code: str, until: dt.datetime | None = None, detail: str = ""):
        super().__init__(detail or REASONS.get(code, code))
        self.code = code
        self.until = until


_lock = threading.Lock()
_state: dict | None = None
_flights: dict[str, threading.Lock] = {}


def _now(now: dt.datetime | None) -> dt.datetime:
    return now or dt.datetime.now(UTC)


def _empty() -> dict:
    return {"models": {}, "paused_until": None, "pause_reason": None, "fail_streak": 0, "auth_block": None,
            "billing_block": False, "limits": {}, "limits_changed": None}


def _load() -> dict:
    global _state
    if _state is None:
        payload, _ = store.cache_get(STATE_KEY)
        _state = {**_empty(), **(payload if isinstance(payload, dict) else {})}
    return _state


def _save(state: dict) -> None:
    global _state
    _state = state
    store.cache_put(STATE_KEY, copy.deepcopy(state), source="FTI AI guard")


def reset_memory() -> None:
    """Forget the in-memory copy (tests; the stored state stays)."""
    global _state
    _state = None


def _iso(t: dt.datetime | None) -> str | None:
    return t.isoformat() if t else None


def _parse(s: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(s) if s else None


def _fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def caps() -> dict:
    cfg = settings_store.get("ai", {}) or {}

    def bounded(name: str, default: int, hard: int) -> int:
        try:
            v = int(cfg.get(name, default))
        except (TypeError, ValueError):
            v = default
        return max(0, min(v, hard))

    return {"requests": bounded("daily_request_cap", HARD_DAILY_CAP, HARD_DAILY_CAP),
            "tokens": bounded("daily_token_cap", 100_000, HARD_TOKEN_CAP),
            "per_minute": bounded("per_minute_cap", 6, HARD_PER_MINUTE)}


def _day_start(now: dt.datetime) -> dt.datetime:
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def usage(session, now: dt.datetime | None = None, since: dt.datetime | None = None) -> dict:
    from app.models import AiUsage

    now = _now(now)
    since = since or _day_start(now)
    n, tok, failed = session.execute(
        select(func.count(AiUsage.id), func.coalesce(func.sum(AiUsage.input_tokens + AiUsage.output_tokens), 0),
               func.coalesce(func.sum(case((AiUsage.ok.is_(False), 1), else_=0)), 0))
        .where(AiUsage.provider.in_(FREE_PROVIDERS), AiUsage.at >= since)).one()  # ONE cap over every AI call
    return {"requests": int(n), "tokens": int(tok), "failed": int(failed)}


def check(session, model: str, est_tokens: int, priority: str = "normal", now: dt.datetime | None = None,
          require_enabled: bool = True) -> None:
    """Raises Blocked when the request must not be sent. Never sleeps, never retries.
    require_enabled=False only for the user's connection test before AI is switched on."""
    now = _now(now)
    cfg = settings_store.get("ai", {}) or {}
    if require_enabled and cfg.get("provider") not in FREE_PROVIDERS:
        raise Blocked("off")
    key = secrets.get(KEY_NAMES[provider_of(model)])
    if not key:
        raise Blocked("no_key")
    with _lock:
        st = _load()
        if st["billing_block"]:
            raise Blocked("billing")
        if st["auth_block"] and st["auth_block"] == _fingerprint(key):
            raise Blocked("auth")
        until = _parse(st["paused_until"])
        if until and until > now:
            raise Blocked("paused", until, f"{REASONS['paused']} {st.get('pause_reason') or ''}".strip())
        m_until = _parse((st["models"].get(model) or {}).get("paused_until"))
        if m_until and m_until > now:
            raise Blocked("model_paused", m_until)
        tpm = ((st["limits"].get(model) or {}).get("tokens_per_minute"))
    c = caps()
    day = usage(session, now)
    tomorrow = _day_start(now) + dt.timedelta(days=1)
    if day["requests"] >= c["requests"]:
        raise Blocked("daily_cap", tomorrow)
    if priority != "high" and day["requests"] >= c["requests"] * (1 - RESERVE_SHARE):
        raise Blocked("reserve", tomorrow)
    if day["tokens"] + est_tokens > c["tokens"]:
        raise Blocked("token_cap", tomorrow)
    minute = usage(session, now, since=now - dt.timedelta(seconds=60))
    if minute["requests"] >= c["per_minute"] or (tpm and minute["tokens"] + est_tokens > tpm * TPM_SHARE):
        raise Blocked("minute", now + dt.timedelta(seconds=60))


def _log(session, task: str, model: str, ok: bool, tokens_in: int = 0, tokens_out: int = 0, note: str = "",
         now: dt.datetime | None = None) -> None:
    from app.models import AiUsage

    session.add(AiUsage(at=_now(now), task=task[:40], provider=provider_of(model), model=model[:60], input_tokens=tokens_in,
                        output_tokens=tokens_out, cost_usd=0.0, ok=ok, note=note[:500]))
    session.commit()


def _remember_limits(st: dict, model: str, limits: dict, now: dt.datetime) -> None:
    if not limits:
        return
    old = st["limits"].get(model) or {}
    for k in ("requests_per_day", "tokens_per_minute"):
        if old.get(k) is not None and limits.get(k) is not None and old[k] != limits[k]:
            st["limits_changed"] = {"model": model, "what": k, "old": old[k], "new": limits[k], "at": _iso(now)}
    st["limits"][model] = {**old, **limits, "seen_at": _iso(now)}
    if limits.get("requests_left_today") is not None and limits["requests_left_today"] <= 1:
        until = now + dt.timedelta(seconds=max(limits.get("requests_reset_s") or 3600, 10))
        st["models"][model] = {"paused_until": _iso(until), "reason": "denní limit Groq vyčerpaný"}


def record_success(session, task: str, model: str, reply: groq.GroqReply, now: dt.datetime | None = None) -> None:
    now = _now(now)
    _log(session, task, model, True, reply.tokens_in, reply.tokens_out, now=now)
    with _lock:
        st = copy.deepcopy(_load())
        st["fail_streak"] = 0
        st["paused_until"] = st["pause_reason"] = None
        _remember_limits(st, model, reply.limits, now)
        _save(st)


def record_failure(session, task: str, model: str, err: groq.GroqError, now: dt.datetime | None = None) -> None:
    now = _now(now)
    _log(session, task, model, False, note=f"{err.kind}: {err}", now=now)
    with _lock:
        st = copy.deepcopy(_load())
        _remember_limits(st, model, err.limits, now)
        if err.kind == "rate_limit":
            wait = err.retry_after or 0
            if err.limits.get("requests_left_today") == 0:
                wait = max(wait, err.limits.get("requests_reset_s") or 0)
            until = now + dt.timedelta(seconds=max(wait, 10))
            st["models"][model] = {"paused_until": _iso(until),
                                   "reason": f"HTTP 429 — bezplatný limit {'Gemini' if provider_of(model) == 'gemini' else 'Groq'}"}
        elif err.kind == "unavailable":
            st["fail_streak"] = int(st.get("fail_streak") or 0) + 1
            minutes = BREAKER_MINUTES[min(st["fail_streak"], len(BREAKER_MINUTES)) - 1]
            st["paused_until"] = _iso(now + dt.timedelta(minutes=minutes))
            st["pause_reason"] = f"{err} Další pokus nejdřív za {minutes} min."
        elif err.kind == "auth":
            st["auth_block"] = _fingerprint(secrets.get(KEY_NAMES[provider_of(model)]) or "")
        elif err.kind == "billing":
            st["billing_block"] = True
        elif err.kind == "model":
            st["models"][model] = {"paused_until": _iso(now + dt.timedelta(hours=24)), "reason": "model u poskytovatele nedostupný"}
        _save(st)


def remember_available(models: list[str], now: dt.datetime | None = None) -> None:
    """The free models Groq offers this account (from the connection test) — others are never tried."""
    with _lock:
        st = copy.deepcopy(_load())
        st["available"] = {"models": [m for m in groq.FREE_MODELS if m in models], "at": _iso(_now(now))}
        _save(st)


def available(model: str) -> bool:
    """False only when the connection test showed the account does not have this model."""
    known = (_load().get("available") or {}).get("models")
    return known is None or model in known


def resume() -> None:
    """The user re-enabled AI after a payment warning or an outage (button in the app)."""
    with _lock:
        st = copy.deepcopy(_load())
        st["billing_block"] = False
        st["paused_until"] = st["pause_reason"] = None
        st["fail_streak"] = 0
        _save(st)


@contextlib.contextmanager
def single_flight(key: str):
    """Two identical requests at the same time become one: the second waits and then finds the stored answer."""
    with _lock:
        lock = _flights.setdefault(key, threading.Lock())
    with lock:
        yield


def status(session, now: dt.datetime | None = None) -> dict:
    now = _now(now)
    cfg = settings_store.get("ai", {}) or {}
    keys = {p: bool(secrets.get(k)) for p, k in KEY_NAMES.items()}
    key_set = any(keys.values())
    c = caps()
    day = usage(session, now)
    st = copy.deepcopy(_load())
    state, until = "ready", None
    first = next((m for p in _order(cfg) if keys[p] for m in (gemini.FREE_MODELS if p == "gemini" else groq.FREE_MODELS)),
                 next(iter(groq.FREE_MODELS)))
    try:
        check(session, first, 0, "high", now)
    except Blocked as b:
        state, until = b.code, b.until
    models = {m: {"provider": provider_of(m), "paused_until": (st["models"].get(m) or {}).get("paused_until"),
                  "reason": (st["models"].get(m) or {}).get("reason"), "limits": st["limits"].get(m)}
              for m in (*gemini.FREE_MODELS, *groq.FREE_MODELS)}
    if state == "model_paused" and any(not v["paused_until"] or _parse(v["paused_until"]) <= now for v in models.values()):
        state, until = "ready", None  # another free model is still available
    order = [p for p in _order(cfg) if keys[p]]
    ready_text = "AI je připravená (" + " → ".join("Gemini Free" if p == "gemini" else "Groq Free" for p in order) + ")."
    return {"provider": cfg.get("provider", "none"), "key_set": key_set, "keys": keys, "order": order, "state": state,
            "text": REASONS.get(state, ready_text if state == "ready" else state),
            "until": _iso(until), "auto_analyses": bool(cfg.get("auto_analyses")),
            "usage": {**day, "cap": c["requests"], "token_cap": c["tokens"], "per_minute_cap": c["per_minute"],
                      "reserve_from": int(c["requests"] * (1 - RESERVE_SHARE))},
            "models": models, "limits_changed": st.get("limits_changed"), "terms_checked": groq.TERMS_CHECKED,
            "calls_today": day["requests"], "calls_cap": c["requests"],
            "cost": "0 Kč — jen bezplatné tarify Gemini (bez billingu) a Groq Free, bez platební metody; "
                    "vyčerpaný limit = NO TRADE „AI nedostupná“, nikdy placená náhrada"}


def _order(cfg: dict) -> list[str]:
    """The free providers, the chosen one first (ai.provider), the other as the backup."""
    first = cfg.get("provider") if cfg.get("provider") in FREE_PROVIDERS else "gemini"
    return [first] + [p for p in FREE_PROVIDERS if p != first]
