"""AI tasks: what Groq interprets, from which engine output, with which token limit and cooldown.

run() is the only way an AI analysis is made:
  facts from the engine → same inputs already analysed? return the stored analysis (no request)
  → cooldown still running? return the last one → guard allows it? → one request per free model at
  most (a 429 moves to the next free model, nothing else retries) → answer checked → stored in the
  analysis history (table analyses, never overwritten).

Tasks whose inputs the engine does not compute yet are listed as not ready, with the reason —
no AI text is produced for them.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json

from sqlalchemy import select

from app.ai import facts as facts_mod
from app.ai import groq, guard, validate

UTC = dt.timezone.utc
M120, M20, LLAMA = "openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"
MAX_INPUT_TOKENS = 2500  # with the answer it stays well under Groq Free's 8 000 tokens a minute

SYSTEM = (
    "Jsi analytický pomocník aplikace FTI (Financial Trading Intelligence). Pracuješ VÝHRADNĚ s fakty v poli „fakta“; "
    "každý fakt má označení F1, F2 … "
    "Nevymýšlej žádné ceny, úrovně, procenta, data, zprávy, objemy ani indikátory — každé číslo, které napíšeš, musí být "
    "ve faktech. Ke každému bodu uveď do pole „fakta“ označení faktů, ze kterých vychází. Co ve faktech chybí, "
    "napiš jako chybějící, nedomýšlej to. U zpráv pole „puvod_casu“ říká, odkud je čas „k“: čas publikace uvedený "
    "zdrojem, čas zachycení službou GDELT, nebo čas stažení FTI. Čas zachycení ani stažení nikdy neuváděj jako čas "
    "publikace a z času stažení neusuzuj, že je zpráva čerstvá. Výsledky enginu FTI (skóre, BIAS) vykládáš, neměníš je a nedáváš pokyny "
    "k obchodu ani investiční doporučení. Piš česky, stručně a srozumitelně pro obchodníka. Odpověz jen objektem JSON "
    "přesně podle zadaného schématu."
)

_POINT = {"type": "object", "additionalProperties": False, "required": ["text", "fakta"],
          "properties": {"text": {"type": "string"}, "fakta": {"type": "array", "items": {"type": "string"}}}}
_POINTS = {"type": "array", "items": _POINT}
_LEVEL = {"type": "string", "enum": ["nízká", "střední", "vysoká"]}

MARKET_SCHEMA = {"type": "object", "additionalProperties": False,
                 "required": ["shrnuti", "bias", "pro", "proti", "sledovat", "chybi", "jistota"],
                 "properties": {"shrnuti": {"type": "string"}, "bias": {"type": "string"}, "pro": _POINTS, "proti": _POINTS,
                                "sledovat": _POINTS, "chybi": {"type": "array", "items": {"type": "string"}}, "jistota": _LEVEL}}
NEWS_SCHEMA = {"type": "object", "additionalProperties": False,
               "required": ["shrnuti_cs", "fakta_zpravy", "vyklad", "dopady", "dulezitost"],
               "properties": {"shrnuti_cs": {"type": "string"}, "fakta_zpravy": _POINTS, "vyklad": {"type": "string"},
                              "dopady": {"type": "array", "items": {
                                  "type": "object", "additionalProperties": False,
                                  "required": ["instrument", "smer", "horizont", "fakta"],
                                  "properties": {"instrument": {"type": "string"},
                                                 "smer": {"type": "string", "enum": ["nahoru", "dolů", "nejasný"]},
                                                 "horizont": {"type": "string", "enum": ["hodiny", "dny", "týdny"]},
                                                 "fakta": {"type": "array", "items": {"type": "string"}}}}},
                              "dulezitost": _LEVEL}}
REPORT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["titulek", "shrnuti", "trhy", "udalosti", "rizika"],
                 "properties": {"titulek": {"type": "string"}, "shrnuti": {"type": "string"},
                                "trhy": {"type": "array", "items": {
                                    "type": "object", "additionalProperties": False, "required": ["instrument", "text", "fakta"],
                                    "properties": {"instrument": {"type": "string"}, "text": {"type": "string"},
                                                   "fakta": {"type": "array", "items": {"type": "string"}}}}},
                                "udalosti": _POINTS, "rizika": _POINTS}}
CHANGE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["co_se_zmenilo", "proc", "co_sledovat"],
                 "properties": {"co_se_zmenilo": {"type": "string"}, "proc": _POINTS, "co_sledovat": _POINTS}}


@dataclasses.dataclass(frozen=True)
class Task:
    id: str
    name: str
    kind: str  # AnalysisRecord.kind
    ready: bool
    why_not: str = ""
    models: tuple = ()
    max_tokens: int = 0
    cooldown_min: int = 0
    schema: dict | None = None
    instruction: str = ""


TASKS: dict[str, Task] = {t.id: t for t in (
    Task("market", "Tržní podmínky, BIAS, fundamentální skóre a konfluence", "ai_market", True, models=(M120, M20, LLAMA),
         max_tokens=1000, cooldown_min=60, schema=MARKET_SCHEMA,
         instruction="Vylož tržní podmínky instrumentu: co znamená fundamentální skóre a BIAS, které faktory BIAS podporují "
                     "(„pro“), které mu odporují („proti“) a jak spolu souhlasí (konfluence), co sledovat dál a co chybí."),
    Task("news", "Analýza ekonomické zprávy", "ai_news", True, models=(M20, M120, LLAMA), max_tokens=700, cooldown_min=0,
         schema=NEWS_SCHEMA,
         instruction="Shrň zprávu česky. Do „fakta_zpravy“ dej jen to, co zpráva skutečně uvádí; do „vyklad“ svůj výklad. "
                     "V „dopady“ uveď instrumenty z klasifikace FTI, pravděpodobný směr a horizont."),
    Task("report", "Analytický report (briefing)", "ai_report", True, models=(M120, M20, LLAMA), max_tokens=1200,
         cooldown_min=240, schema=REPORT_SCHEMA,
         instruction="Napiš krátký briefing přes všechny trhy: titulek, shrnutí, jedna věta ke každému trhu, důležité "
                     "události a hlavní rizika."),
    Task("change", "Vyhodnocení významné změny", "ai_change", True, models=(M20, M120, LLAMA), max_tokens=600,
         cooldown_min=15, schema=CHANGE_SCHEMA,
         instruction="Vysvětli, co se ve výpočtu FTI změnilo, proč (které složky) a co teď sledovat."),
    Task("trade", "Komplexní AI analýza: LONG / SHORT / NO TRADE", "ai_trade", True, cooldown_min=30,
         instruction="Více AI rolí nad společným kontextem FTI (app/ai/pipeline.py) — zatím XAU/USD."),
    Task("event", "Interpretace makroekonomické události", "ai_event", False,
         why_not="Kalendář FTI zatím neukládá skutečné výsledky zveřejněných událostí (actual), jen očekávání a minulou "
                 "hodnotu. Zveřejněná data se promítají do fundamentálního skóre."),
    Task("zones", "Supply/demand zóny, order blocks a FVG", "ai_zones", False,
         why_not="Engine FTI zatím zóny, order blocky ani FVG nepočítá — AI je nesmí vymýšlet."),
)}


def catalog() -> list[dict]:
    return [{"id": t.id, "name": t.name, "ready": t.ready, "why_not": t.why_not or None, "cooldown_min": t.cooldown_min}
            for t in TASKS.values()]


def _hash(task: str, key: str, facts: list[dict]) -> str:
    stable = [{k: v for k, v in f.items() if k != "volatile"} for f in facts if not f.get("volatile")]
    return hashlib.sha256(json.dumps([task, key, stable], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _estimate_tokens(text: str) -> int:
    return int(len(text) / 2.8) + 1  # Czech JSON: ~2.8 characters per token — on the safe side


def _trim(facts: list[dict], message) -> list[dict]:
    """Keep the input under MAX_INPUT_TOKENS: headlines and portal articles go first, then long texts."""
    out = list(facts)
    while _estimate_tokens(message(out)) > MAX_INPUT_TOKENS:
        idx = next((i for i in range(len(out) - 1, -1, -1) if out[i]["co"].startswith(("Titulek", "Technický", "Zpráva"))), None)
        if idx is not None:
            out.pop(idx)
            continue
        longest = max(range(len(out)), key=lambda i: len(out[i].get("text") or ""))
        if len(out[longest].get("text") or "") < 80:
            break
        out[longest] = {**out[longest], "text": out[longest]["text"][: len(out[longest]["text"]) // 2] + "…"}
    return out


def _record(session, kind: str, code: str | None, item_key: str):
    from app.models import AnalysisRecord

    q = select(AnalysisRecord).where(AnalysisRecord.kind == kind).order_by(AnalysisRecord.created_at.desc()).limit(200)
    if code:
        q = q.where(AnalysisRecord.code == code)
    return [r for r in session.scalars(q) if (r.payload or {}).get("key") == item_key]


def to_dict(r) -> dict:
    p = r.payload or {}
    return {"id": r.id, "task": p.get("task"), "code": r.code, "created_at": r.created_at.isoformat(), "model": r.ai_model,
            "reason": r.question, "engine_computed_at": r.data_as_of, "output": p.get("output"), "facts": p.get("facts"),
            "validation": p.get("validation"), "tokens": p.get("tokens"), "confidence": r.confidence,
            "stages": p.get("stages"), "providers": p.get("providers") or (["groq"] if r.ai_model else None),
            "seconds": p.get("seconds"), "missing": p.get("missing")}


def _build(task: Task, session, code: str | None, item_id: int | None):
    if task.id == "market":
        return facts_mod.market(session, code or "XAUUSD")
    if task.id == "news":
        return facts_mod.news(session, int(item_id or 0))
    if task.id == "report":
        return facts_mod.report(session)
    raise facts_mod.NotReady("Tuto úlohu spouští jen sledování změn.")


def run(session, task_id: str, code: str | None = None, item_id: int | None = None, reason: str = "na požádání",
        priority: str = "normal", built=None, now: dt.datetime | None = None) -> dict:
    """{status: ok | cached | cooldown | unavailable | invalid | not_ready, text, analysis, until}"""
    from app.models import AnalysisRecord

    now = now or dt.datetime.now(UTC)
    task = TASKS.get(task_id)
    if task is None:
        return {"status": "not_ready", "text": "Neznámá úloha."}
    if not task.ready:
        return {"status": "not_ready", "text": task.why_not}
    if task.id == "trade":  # several AI roles through the router — its own runner, same result shape
        from app.ai import pipeline

        return pipeline.run(session, code or "XAUUSD", reason=reason, priority=priority, now=now)
    try:
        facts, meta = built or _build(task, session, code, item_id)
    except facts_mod.NotReady as exc:
        return {"status": "not_ready", "text": str(exc)}
    code = meta.get("instrument") or code
    item_key = f"{code or ''}:{meta.get('item_id') or ''}"

    def message(fs):
        return json.dumps({"uloha": task.instruction, "schema_odpovedi": task.schema, "fakta": fs}, ensure_ascii=False)

    facts = _trim(facts, message)
    input_hash = _hash(task.id, item_key, facts)
    with guard.single_flight(f"{task.id}:{item_key}"):
        previous = _record(session, task.kind, code, item_key)
        same = next((r for r in previous if (r.payload or {}).get("input_hash") == input_hash), None)
        if same:
            return {"status": "cached", "text": "Stejná vstupní data už AI vyložila — bez nového dotazu.", "analysis": to_dict(same)}
        last = previous[0] if previous else None
        if last and task.cooldown_min and priority != "high":
            next_at = last.created_at + dt.timedelta(minutes=task.cooldown_min)
            if next_at > now:
                return {"status": "cooldown", "text": f"Další AI rozbor nejdřív {next_at.isoformat()}.", "until": next_at.isoformat(),
                        "analysis": to_dict(last)}
        msg = message(facts)
        est = _estimate_tokens(SYSTEM + msg) + task.max_tokens
        blocked: guard.Blocked | None = None
        for model in [m for m in task.models if guard.available(m)]:
            try:
                guard.check(session, model, est, priority, now)
            except guard.Blocked as b:
                blocked = b
                if b.code == "model_paused":
                    continue
                break
            try:
                reply = groq.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}], model,
                                  task.max_tokens, schema=task.schema, schema_name=f"fti_{task.id}")
            except groq.GroqError as err:
                guard.record_failure(session, task.id, model, err, now)
                if err.kind in ("rate_limit", "model"):
                    blocked = guard.Blocked("model_paused", detail=str(err))
                    continue
                status = "invalid" if err.kind == "invalid_output" else "unavailable"
                return {"status": status, "text": str(err), "analysis": to_dict(last) if last else None}
            guard.record_success(session, task.id, model, reply, now)
            check = validate.validate(reply.content, task.schema, facts)
            out = reply.content if isinstance(reply.content, dict) else {}
            rec = AnalysisRecord(kind=task.kind, code=code, created_at=now, data_as_of=meta.get("engine_computed_at"),
                                 confidence=(out.get("jistota") or out.get("dulezitost")), ai_model=reply.model, question=reason,
                                 payload={"task": task.id, "key": item_key, "input_hash": input_hash, "facts": facts,
                                          "output": reply.content, "validation": check, "priority": priority,
                                          "tokens": {"in": reply.tokens_in, "out": reply.tokens_out},
                                          "seconds": round(reply.seconds, 2), "finish_reason": reply.finish_reason})
            session.add(rec)
            session.commit()
            return {"status": "ok" if check["ok"] else "invalid",
                    "text": "Hotovo." if check["ok"] else "AI odpověď neprošla kontrolou — zobrazuje se rozbor z pravidel.",
                    "analysis": to_dict(rec)}
        b = blocked or guard.Blocked("off")
        return {"status": "unavailable", "text": str(b), "code": b.code, "until": b.until.isoformat() if b.until else None,
                "analysis": to_dict(last) if last else None}


def history(session, code: str | None = None, task_id: str | None = None, limit: int = 10) -> list[dict]:
    from app.models import AnalysisRecord

    kinds = [TASKS[task_id].kind] if task_id in TASKS else [t.kind for t in TASKS.values()]
    q = select(AnalysisRecord).where(AnalysisRecord.kind.in_(kinds)).order_by(AnalysisRecord.created_at.desc()).limit(max(1, min(limit, 50)))
    if code:
        q = q.where(AnalysisRecord.code == code.upper())
    return [to_dict(r) for r in session.scalars(q)]
