"""AI Router — chooses the provider and model for each analytical role, provider-agnostic.

Providers are a registry: adding one means adding its entry (and, when it is approved, its client) — the
analytical core never names a provider or a model. A provider is used only when ALL hold:
  * it is free (budget 0 Kč — no card, no pay-as-you-go),
  * the user approved it,
  * FTI has a client for it,
  * its key is set.
Paid providers (OpenAI, Anthropic …) are listed so the architecture is ready, but they are never called.

Roles (what a model is asked to do) map to model tiers: "strong" for synthesis and macro reasoning, "fast"
for narrower specialist work. Within a tier the order is the measured quality per role (ROLE_SCORES — filled
by the evaluation of FTI's own test cases; empty until a model has been evaluated, then the static order).
A failure (limit, outage, missing model) moves to the next candidate; when nothing is left the role reports
itself unavailable — an analysis is never pretended.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field

from app.ai import groq, guard
from app.data import secrets

UTC = dt.timezone.utc


@dataclass(frozen=True)
class Model:
    id: str
    tier: str  # "strong" | "fast"
    strict_json: bool = True
    note: str = ""


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    free: bool  # truly 0 Kč without a card
    approved: bool  # the user approved it for FTI
    implemented: bool  # FTI has a client for it
    key_name: str | None
    models: tuple[Model, ...] = ()
    terms: str = ""  # data use / limits, checked
    why_not: str = ""


PROVIDERS: dict[str, Provider] = {p.id: p for p in (
    Provider("groq", "Groq Free", free=True, approved=True, implemented=True, key_name=groq.KEY_NAME,
             models=(Model("openai/gpt-oss-120b", "strong"), Model("openai/gpt-oss-20b", "fast")),
             terms="Free plán bez karty: 1 000 dotazů/den a 8 000 tokenů/min na model (hlášeno účtu 1. 11. 2026); "
                   "FTI navíc 80 dotazů a 100 000 tokenů denně."),
    Provider("workers_ai", "Cloudflare Workers AI", free=True, approved=False, implemented=False, key_name="CLOUDFLARE_AI_TOKEN",
             terms="10 000 neuronů/den zdarma, po vyčerpání chyba (bez účtování) — ověřeno v dokumentaci 7. 11. 2026.",
             why_not="Čeká na schválení; klient FTI zatím není."),
    Provider("gemini", "Google Gemini API (free tier)", free=True, approved=False, implemented=False, key_name="GEMINI_API_KEY",
             why_not="Čeká na ověření limitů a podmínek použití dat ve free tieru a na schválení."),
    Provider("openrouter", "OpenRouter (modely :free)", free=True, approved=False, implemented=False, key_name="OPENROUTER_API_KEY",
             why_not="Čeká na ověření denních limitů bez kreditu a na schválení."),
    Provider("mistral", "Mistral (Experiment plán)", free=True, approved=False, implemented=False, key_name="MISTRAL_API_KEY",
             why_not="Bezplatný plán vyžaduje ověření telefonem; čeká na schválení."),
    Provider("openai", "OpenAI API (GPT)", free=False, approved=False, implemented=False, key_name="OPENAI_API_KEY",
             why_not="Placené API — ChatGPT Go API nezahrnuje. Jen s výslovně schváleným rozpočtem."),
    Provider("anthropic", "Anthropic API (Claude)", free=False, approved=False, implemented=False, key_name="ANTHROPIC_API_KEY",
             why_not="Placené API. Jen s výslovně schváleným rozpočtem."),
)}

# role → preferred tiers, in order
ROLES: dict[str, tuple[str, ...]] = {
    "technika": ("fast", "strong"),
    "makro": ("strong", "fast"),
    "synteza": ("strong", "fast"),
    "kontrola": ("fast", "strong"),
}
# measured quality per role and model (0–1) from FTI's own evaluation; higher first within a tier
ROLE_SCORES: dict[str, dict[str, float]] = {}
MAX_MINUTE_WAIT = 65  # seconds the router waits for Groq's per-minute token window inside one analysis


@dataclass(frozen=True)
class Candidate:
    provider: str
    model: str
    tier: str


class RoleUnavailable(RuntimeError):
    def __init__(self, role: str, reason: str, until: dt.datetime | None = None, attempts: list | None = None):
        super().__init__(reason)
        self.role, self.until, self.attempts = role, until, attempts or []


@dataclass
class RoleReply:
    role: str
    provider: str
    model: str
    content: dict | str
    tokens_in: int
    tokens_out: int
    seconds: float
    attempts: list = field(default_factory=list)


def usable(p: Provider) -> tuple[bool, str]:
    if not p.free:
        return False, p.why_not or "placený poskytovatel"
    if not p.approved:
        return False, p.why_not or "neschválený poskytovatel"
    if not p.implemented:
        return False, p.why_not or "klient FTI zatím není"
    if p.key_name and not secrets.get(p.key_name):
        return False, f"klíč {p.key_name} není nastavený"
    return True, ""


def candidates(role: str) -> list[Candidate]:
    tiers = ROLES.get(role, ("strong", "fast"))
    scores = ROLE_SCORES.get(role, {})
    out = []
    for tier in tiers:
        tier_models = [(p, m) for p in PROVIDERS.values() if usable(p)[0] for m in p.models if m.tier == tier]
        tier_models.sort(key=lambda pm: -scores.get(pm[1].id, 0.0))  # stable: registry order when unmeasured
        out += [Candidate(p.id, m.id, tier) for p, m in tier_models if guard.available(m.id) or p.id != "groq"]
    return out


def catalog() -> list[dict]:
    """Every provider with whether FTI uses it and why not — for the Data page; never a key."""
    rows = []
    for p in PROVIDERS.values():
        ok, why = usable(p)
        rows.append({"id": p.id, "name": p.name, "free": p.free, "approved": p.approved, "implemented": p.implemented,
                     "used": ok, "why_not": None if ok else why, "models": [{"id": m.id, "tier": m.tier} for m in p.models],
                     "terms": p.terms or None})
    return rows


def _call(c: Candidate, messages: list[dict], max_tokens: int, schema: dict | None, schema_name: str):
    if c.provider == "groq":
        return groq.chat(messages, c.model, max_tokens, schema=schema, schema_name=schema_name)
    raise RuntimeError(f"Poskytovatel {c.provider} nemá klienta")  # unreachable: usable() filters it out


def run_role(session, role: str, messages: list[dict], max_tokens: int, est_tokens: int, schema: dict | None,
             task: str, priority: str = "normal", now: dt.datetime | None = None, sleep=time.sleep) -> RoleReply:
    """Ask the best available model for this role; fall back on limits/outages. Raises RoleUnavailable."""
    attempts: list[dict] = []
    last_block: guard.Blocked | None = None
    for c in candidates(role):
        for wait_round in (0, 1):
            t = now or dt.datetime.now(UTC)
            try:
                guard.check(session, c.model, est_tokens, priority, t)
            except guard.Blocked as b:
                last_block = b
                if b.code == "minute" and wait_round == 0 and b.until:
                    pause = min(MAX_MINUTE_WAIT, max(1.0, (b.until - t).total_seconds()))
                    attempts.append({"provider": c.provider, "model": c.model, "result": f"čeká {pause:.0f} s na minutový limit"})
                    sleep(pause)
                    now = None if now is None else now + dt.timedelta(seconds=pause)
                    continue
                attempts.append({"provider": c.provider, "model": c.model, "result": str(b)})
                break
            try:
                reply = _call(c, messages, max_tokens, schema, f"fti_{task}_{role}")
            except groq.GroqError as err:
                guard.record_failure(session, f"{task}:{role}", c.model, err, t)
                attempts.append({"provider": c.provider, "model": c.model, "result": str(err)})
                if err.kind in ("rate_limit", "model", "invalid_output", "too_large"):
                    break  # next candidate
                raise RoleUnavailable(role, str(err), attempts=attempts) from None
            guard.record_success(session, f"{task}:{role}", c.model, reply, t)
            attempts.append({"provider": c.provider, "model": reply.model, "result": "ok"})
            return RoleReply(role, c.provider, reply.model, reply.content, reply.tokens_in, reply.tokens_out, reply.seconds, attempts)
        if last_block is not None and last_block.code not in ("model_paused", "minute"):
            break  # daily cap, AI off, no key …: no other Groq model would be allowed either
    reason = str(last_block) if last_block else "Žádný schválený bezplatný AI model není k dispozici."
    raise RoleUnavailable(role, reason, last_block.until if last_block else None, attempts)
