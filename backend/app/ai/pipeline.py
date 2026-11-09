"""The complex AI analysis (LONG / SHORT / NO TRADE) — several AI roles over FTI's common context.

  1. makro     fundamentals, FRED macro, intermarket, COT, news, calendar, seasonality  → specialist conclusion
  2. technika  price, trends M15–D1, DXY, volatility                                    → specialist conclusion
  3. synteza   both conclusions + FTI's rule-based verdict + key facts → LONG / SHORT / NO TRADE with scenarios,
               confirmation and invalidation conditions, risks, and whether it agrees with FTI's own verdict

Why roles: Groq Free allows 8 000 tokens a minute per model — the whole context of gold does not fit one
request — and specialised roles are the base of the multi-model design (the router picks the model of each
role; more providers plug in without changing this file). Every number of every answer is checked against
FTI's facts; a specialist whose answer fails the check is left out of the synthesis and the result says so.
The analysis is input for the user, who alone places trades — FTI never trades and never pretends: when no
model is available the result is "unavailable".
"""

from __future__ import annotations

import datetime as dt
import json
import time

from app.ai import check, context, router, tasks, validate
from app.ai.facts import NotReady, Packet

UTC = dt.timezone.utc
TASK = "trade"
KIND = "ai_trade"
COOLDOWN_MIN = 30
CHARS_PER_TOKEN = 2.3  # measured on FTI's Czech JSON: 7 900 characters = 3 458 tokens (Groq, 1. 11. 2026)

_LEVEL = {"type": "string", "enum": ["nízká", "střední", "vysoká"]}
_POINTS = tasks._POINTS
SPEC_SCHEMA = {"type": "object", "additionalProperties": False,
               "required": ["zaver", "smer", "jistota", "pro_rust", "pro_pokles", "sledovat", "chybi"],
               "properties": {"zaver": {"type": "string"},
                              "smer": {"type": "string", "enum": ["býčí", "medvědí", "neutrální", "nejasný"]},
                              "jistota": _LEVEL, "pro_rust": _POINTS, "pro_pokles": _POINTS, "sledovat": _POINTS,
                              "chybi": {"type": "array", "items": {"type": "string"}}}}
_SCENARIO = {"type": "object", "additionalProperties": False, "required": ["typ", "popis", "potvrzeni", "invalidace"],
             "properties": {"typ": {"type": "string", "enum": ["LONG", "SHORT", "NO TRADE"]}, "popis": {"type": "string"},
                            "potvrzeni": _POINTS, "invalidace": _POINTS}}
TRADE_SCHEMA = {"type": "object", "additionalProperties": False,
                "required": ["shrnuti", "doporuceni", "bias", "horizont", "jistota", "technika", "fundament", "zpravy_sentiment",
                             "intermarket", "pro", "proti", "scenare", "rizika", "vztah_k_enginu", "chybejici_data"],
                "properties": {
                    "shrnuti": {"type": "string"},
                    "doporuceni": {"type": "string", "enum": ["LONG", "SHORT", "NO TRADE"]},
                    "bias": {"type": "string", "enum": ["býčí", "medvědí", "neutrální"]},
                    "horizont": {"type": "string", "enum": ["intradenní", "swing (dny)", "týdny"]},
                    "jistota": _LEVEL, "technika": _POINTS, "fundament": _POINTS, "zpravy_sentiment": _POINTS,
                    "intermarket": _POINTS, "pro": _POINTS, "proti": _POINTS,
                    "scenare": {"type": "array", "items": _SCENARIO}, "rizika": _POINTS,
                    "vztah_k_enginu": {"type": "object", "additionalProperties": False, "required": ["shoda", "text", "fakta"],
                                       "properties": {"shoda": {"type": "string", "enum": ["souhlasí", "částečně", "nesouhlasí"]},
                                                      "text": {"type": "string"},
                                                      "fakta": {"type": "array", "items": {"type": "string"}}}},
                    "chybejici_data": {"type": "array", "items": {"type": "string"}}}}

SYSTEM = (
    "Jsi analytik aplikace FTI (Financial Trading Intelligence). Pracuješ VÝHRADNĚ s fakty v poli „fakta“; každý fakt má "
    "označení F1, F2 … , zdroj a čas „k“. Nevymýšlej žádné ceny, úrovně, procenta, data, zprávy ani indikátory — každé "
    "číslo, které napíšeš, musí být ve faktech. Ke každému bodu uveď do pole „fakta“ označení faktů, ze kterých vychází. "
    "Co chybí nebo je zastaralé, napiš jako chybějící. U zpráv pole „puvod_casu“ říká, zda je čas časem publikace, "
    "zachycení GDELT nebo stažení FTI — čas zachycení ani stažení neuváděj jako čas publikace. Korelace popisuje souběh "
    "pohybů, nikdy ji nevydávej za příčinu. Hodnotíš scénáře LONG / SHORT / NO TRADE jako podklad pro uživatele, který "
    "obchody zadává sám — nejde o pokyn k obchodu ani investiční doporučení. Piš česky, věcně a stručně. Odpověz jen "
    "objektem JSON přesně podle schématu."
)
STAGES = [
    # role, areas of the context, max answer tokens, instruction
    ("makro", ("fundament", "mezitrh", "pozice", "kalendar", "zpravy", "sezonnost", "rezim", "kvalita"), 1600,
     "Jsi makroekonomický a fundamentální specialista pro {code}. Vyhodnoť: model FTI a jeho složky (data FRED s daty "
     "zveřejnění), sazby a výnosy, reálný výnos, VIX, ropu a akcie (korelace = souběh, ne příčina), pozice fondů a retailu "
     "(COT), zprávy a riziko titulků, nadcházející události kalendáře a sezónnost. Uveď argumenty pro růst a pro pokles "
     "zlata, co sledovat a co chybí nebo je zastaralé. V každém seznamu nejvýš 4 krátké body."),
    ("mezitrh", ("intermarket", "intermarket_souhrn", "kvalita"), 1400,
     "Jsi intermarketový specialista pro {code}. Máš korelace zlata s ostatními trhy z Intermarket Intelligence FTI: "
     "synchronizované výnosy, okno, počet pozorování, p a q, stabilita, změna proti předchozímu oknu, rozpad vztahu, kvalita "
     "dat a zda trh potvrzuje nebo odporuje poslednímu pohybu zlata. Vyhodnoť, které vztahy jsou pevné a stabilní, které se "
     "rozpadají nebo jsou málo spolehlivé (CFD, vypočtený index, málo pozorování, posun uzávěrek), a zda mezitrh pohyb zlata "
     "potvrzuje. Korelace je souběh, ne příčina — nevymýšlej ekonomické vysvětlení, které ve faktech není. Uveď argumenty "
     "pro růst a pro pokles, co sledovat a co chybí. V každém seznamu nejvýš 4 krátké body."),
    ("technika", ("trh", "technika", "dolar", "volatilita", "rezim", "kvalita"), 1400,
     "Jsi technický specialista pro {code}. Vyhodnoť stav trhu a stáří cen, trendy M15/H1/H4/D1 (EMA20/50, ADX, ATR), "
     "swingová maxima a minima jako možné úrovně potvrzení a invalidace, volatilitu (ATR, GVZ) a dolar (trend a úrovně DXY, "
     "korelace se zlatem) a režim trhu (trend × pásmo, volatilita). Uveď argumenty pro růst a pro pokles, co sledovat a co "
     "chybí. V každém seznamu nejvýš 4 krátké body."),
]
SYNTHESIS = ("synteza", ("trh", "engine", "rezim", "kalendar", "kvalita", "specialista", "intermarket_souhrn"), 3200,
             "Jsi hlavní analytik FTI pro {code}. Máš závěry specialistů (fakta „Závěr specialisty …“), pravidlový verdikt FTI a "
             "klíčová fakta. Rozhodni LONG, SHORT, nebo NO TRADE a horizont. Když se technika a makro rozcházejí, když je trh "
             "zavřený nebo ceny nejsou čerstvé, nebo když se blíží důležitá událost, zvaž NO TRADE a vysvětli proč. U LONG i "
             "SHORT scénáře uveď podmínky potvrzení a invalidace — úrovně ber jen z faktů (swing high/low, EMA, úrovně DXY). "
             "Uveď i opačný scénář. Ve „vztah_k_enginu“ porovnej závěr s pravidlovým verdiktem FTI; když nesouhlasíš, řekni "
             "proč — nevytvářej umělou shodu. „pro“ a „proti“ se týkají doporučení. Nehledej jen potvrzení: když mezitrh "
             "(fakta „Mezitrh … potvrzení pohybu zlata“) pohyb, na který doporučení navazuje, nepotvrzuje, uveď to v „proti“ "
             "nebo v „rizicích“ s odkazem na ten fakt a zvaž NO TRADE. Režim trhu (fakta „Režim trhu …“) říká, jaký typ "
             "obchodu teď dává smysl: v pásmu bez trendu neber průraz sám jako potvrzení, při zvýšené volatilitě uveď širší "
             "stop-loss a menší pozici. Buď stručný: v každém seznamu nejvýš "
             "3 krátké body, nejvýš 3 scénáře.")
KEY_TECH = ("Swingový trend", "Celkový trend", "Technika H4", "Technika D1", "Úrovně DXY")
BUDGET_TOKENS = 7200  # Groq 8 000 tokens a minute per model, 90 % used at most


def _est(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def _message(instruction: str, facts: list[dict]) -> str:
    return json.dumps({"uloha": instruction, "fakta": facts}, ensure_ascii=False)


def _fit(facts: list[dict], instruction: str, max_tokens: int) -> list[dict]:
    """Keep input + answer under Groq's minute budget: headlines go first, then long texts are shortened."""
    out = list(facts)
    while _est(SYSTEM + _message(instruction, out)) + max_tokens > BUDGET_TOKENS:
        idx = next((i for i in range(len(out) - 1, -1, -1) if out[i]["co"] in ("Klíčová zpráva", "Chybí")), None)
        if idx is not None:
            out.pop(idx)
            continue
        longest = max(range(len(out)), key=lambda i: len(out[i].get("text") or ""))
        if len(out[longest].get("text") or "") < 80:
            break
        out[longest] = {**out[longest], "text": out[longest]["text"][: len(out[longest]["text"]) // 2] + "…"}
    return out


def _subset(facts: list[dict], areas: tuple[str, ...]) -> list[dict]:
    return [f for f in facts if f.get("oblast") in areas
            or ("technika" not in areas and "engine" in areas and f["co"].startswith(KEY_TECH))]


def _points_text(points: list[dict]) -> str:
    return "; ".join(f"{p['text']} [{', '.join(p.get('fakta') or [])}]" for p in points or [])


def _specialist_fact(p: Packet, stage: dict) -> None:
    o = stage["output"]
    p.add(f"Závěr specialisty: {stage['role']}", o.get("smer"), source=f"{stage['provider']} · {stage['model']}",
          section="specialista",
          text=(f"{o.get('zaver')} Jistota {o.get('jistota')}. Pro růst: {_points_text(o.get('pro_rust'))}. "
                f"Pro pokles: {_points_text(o.get('pro_pokles'))}. Sledovat: {_points_text(o.get('sledovat'))}.")[:1100])


def rules(out: dict, facts: list[dict] | None = None) -> list[str]:
    """What a trading scenario must contain beyond the schema."""
    problems = []
    rec = out.get("doporuceni")
    scen = out.get("scenare") or []
    if rec in ("LONG", "SHORT"):
        mine = [s for s in scen if s.get("typ") == rec]
        if not mine or not mine[0].get("potvrzeni") or not mine[0].get("invalidace"):
            problems.append(f"Doporučení {rec} nemá scénář s podmínkami potvrzení i invalidace.")
        # the user's rule: FTI must not only look for confirmation — a recommendation that continues a move the intermarket
        # contradicts has to say so (in "proti" or "rizika", citing the Intermarket fact)
        cited = {i for k in ("proti", "rizika") for pt in out.get(k) or [] if isinstance(pt, dict) for i in pt.get("fakta") or []}
        for f in facts or []:
            m = f.get("mezitrh")
            if m and m.get("verdict") == "odporuje" and m.get("gold_pct") and (rec == "LONG") == (m["gold_pct"] > 0)                     and f["id"] not in cited:
                problems.append(f"Doporučení {rec} navazuje na pohyb zlata, kterému mezitrh ({m['tf']}) odporuje, a neuvádí to "
                                f"v „proti“ ani v „rizicích“ ({f['id']}).")
    return problems  # a condition without a cited fact is removed by FTI's independent check (check.py), not fatal


def _live_gate(code: str, final: dict) -> dict | None:
    """The user's rule (9. 11. 2026): without a current price no valid trade signal. Applies while the LIVE engine runs;
    a LONG / SHORT made without a LIVE price becomes NO TRADE, and the reason is stored and shown."""
    from app.live import engine as live_engine, runner as live_runner

    lr = live_runner.get()
    allowed, why = live_engine.signal_allowed(lr.engine if lr else None, code)
    if allowed is None:
        return None
    gate = {"allowed": allowed, "reason": why, "ai_recommendation": final.get("doporuceni")}
    if not allowed and final.get("doporuceni") in ("LONG", "SHORT"):
        final["doporuceni"] = "NO TRADE"
        final["shrnuti"] = f"{why} (AI navrhovala {gate['ai_recommendation']}.) " + str(final.get("shrnuti") or "")
        gate["overridden"] = True
    return gate


def run(session, code: str = "XAUUSD", reason: str = "na požádání", priority: str = "normal",
        now: dt.datetime | None = None, quote_fn=None, sleep=time.sleep) -> dict:
    """Same result shape as tasks.run: {status, text, analysis, until}."""
    from app.models import AnalysisRecord

    now = now or dt.datetime.now(UTC)
    from app.live import engine as live_engine, runner as live_runner

    lr = live_runner.get()
    allowed, why = live_engine.signal_allowed(lr.engine if lr else None, (code or "XAUUSD").upper())
    if allowed is False:  # brief 9. 11.: without a LIVE price the code decides NO TRADE before any AI call
        return {"status": "unavailable", "text": f"NO TRADE — {why} AI se nevolala.", "no_trade": True}
    try:
        facts, meta = context.trade(session, code, quote_fn=quote_fn)
    except NotReady as exc:
        return {"status": "not_ready", "text": str(exc)}
    code = meta["instrument"]
    key = f"{code}:"
    input_hash = tasks._hash(TASK, key, facts)
    with tasks.guard.single_flight(f"{TASK}:{key}"):
        previous = tasks._record(session, KIND, code, key)
        same = next((r for r in previous if (r.payload or {}).get("input_hash") == input_hash), None)
        if same:
            return {"status": "cached", "text": "Stejná data už AI analyzovala — bez nového dotazu.", "analysis": tasks.to_dict(same)}
        last = previous[0] if previous else None
        if last and priority != "high" and last.created_at + dt.timedelta(minutes=COOLDOWN_MIN) > now:
            until = last.created_at + dt.timedelta(minutes=COOLDOWN_MIN)
            return {"status": "cooldown", "text": f"Další komplexní analýza nejdřív {until.isoformat()}.", "until": until.isoformat(),
                    "analysis": tasks.to_dict(last)}
        p = Packet()
        p.facts = [dict(f) for f in facts]
        stages: list[dict] = []
        t0 = time.monotonic()
        try:
            for role, areas, max_tokens, instruction in STAGES:
                instr = instruction.format(code=code)
                if role == "mezitrh" and not any(f.get("oblast") == "intermarket" for f in p.facts):
                    continue  # no synchronised Intermarket data: no specialist without facts (listed as missing in the context)
                sub = _fit(_subset(p.facts, areas), instr, max_tokens)
                msg = _message(instr, sub)
                r = router.run_role(session, role, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}],
                                    max_tokens, _est(SYSTEM + msg) + max_tokens, SPEC_SCHEMA, TASK, priority, sleep=sleep)
                verdict = validate.validate(r.content, SPEC_SCHEMA, sub)
                content, removed, stuck = r.content, [], []
                if verdict["ok"]:  # FTI's independent check: wrong points are dropped, a wrong conclusion drops the role
                    content, removed, stuck = check.drop(r.content, check.attribution(r.content, sub))
                    verdict = {**verdict, "ok": not stuck, "attribution": [p["problem"] for p in stuck],
                               "removed": [{"text": p["text"], "problem": p["problem"]} for p in removed]}
                stage = {"role": role, "provider": r.provider, "model": r.model, "output": content, "validation": verdict,
                         "facts_used": [f["id"] for f in sub], "tokens": {"in": r.tokens_in, "out": r.tokens_out},
                         "seconds": round(r.seconds, 2), "attempts": r.attempts}
                stages.append(stage)
                if verdict["ok"]:
                    _specialist_fact(p, stage)
            role, areas, max_tokens, instruction = SYNTHESIS
            instr = instruction.format(code=code)
            if not any(s["validation"]["ok"] for s in stages):
                instr += " Žádný specialista neprošel kontrolou dat — vycházej jen z faktů níže a jistotu sniž."
            sub = _fit(_subset(p.facts, areas), instr, max_tokens)
            msg = _message(instr, sub)
            r = router.run_role(session, role, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}],
                                max_tokens, _est(SYSTEM + msg) + max_tokens, TRADE_SCHEMA, TASK, priority, sleep=sleep)
        except router.RoleUnavailable as exc:
            done = ", ".join(s["role"] for s in stages) or "žádná"
            # the user's rule (9. 11. 2026): free limits gone (HTTP 429 everywhere) or no free model → NO TRADE, never a paid one
            return {"status": "unavailable", "no_trade": True,
                    "text": f"NO TRADE — AI nedostupná ({exc.role}): {exc} Placený poskytovatel se nepoužije. Hotové role: {done}.",
                    "until": exc.until.isoformat() if exc.until else None, "analysis": tasks.to_dict(last) if last else None}
        verdict = validate.validate(r.content, TRADE_SCHEMA, p.facts)
        final = r.content if isinstance(r.content, dict) else {}
        removed, stuck = [], []
        if verdict["ok"]:
            final, removed, stuck = check.drop(final, check.attribution(final, p.facts))
        problems = rules(final, p.facts)
        verdict = {**verdict, "rules": problems, "attribution": [x["problem"] for x in stuck],
                   "removed": [{"text": x["text"], "problem": x["problem"]} for x in removed],
                   "ok": verdict["ok"] and not problems and not stuck}
        stages.append({"role": role, "provider": r.provider, "model": r.model, "output": None, "validation": verdict,
                       "facts_used": [f["id"] for f in sub], "tokens": {"in": r.tokens_in, "out": r.tokens_out},
                       "seconds": round(r.seconds, 2), "attempts": r.attempts})
        gate = _live_gate(code, final)
        out = final
        tok_in = sum(s["tokens"]["in"] for s in stages)
        tok_out = sum(s["tokens"]["out"] for s in stages)
        rec = AnalysisRecord(kind=KIND, code=code, created_at=now, data_as_of=meta.get("engine_computed_at"),
                             confidence=out.get("jistota"), ai_model=r.model, question=reason,
                             payload={"task": TASK, "key": key, "input_hash": input_hash, "facts": p.facts, "output": final,
                                      "raw_output": r.content, "validation": verdict, "priority": priority, "stages": stages,
                                      "tokens": {"in": tok_in, "out": tok_out}, "seconds": round(time.monotonic() - t0, 1),
                                      "providers": sorted({s["provider"] for s in stages}), "missing": meta.get("missing"),
                                      "live_gate": gate})
        session.add(rec)
        session.commit()
        return {"status": "ok" if verdict["ok"] else "invalid",
                "text": "Hotovo." if verdict["ok"] else "AI analýza neprošla kontrolou dat — neověřené části jsou označené.",
                "analysis": tasks.to_dict(rec)}
