"""FTI platform API: instrument identities and the data audit, source monitoring, settings and
keys (keys are write-only: the API never returns a key, only whether it is set)."""

from __future__ import annotations

import datetime as dt
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.data import bars as bars_mod
from app.data import health, mt5, quality, secrets, settings_store, universe
from app.db import get_session

router = APIRouter(prefix="/api")
_audit_cache: dict[str, tuple[float, object]] = {}
_audit_lock = threading.Lock()
_audit_compute = threading.Lock()
AUDIT_TTL = 600.0


@router.get("/instruments")
def list_instruments():
    return {"instruments": [universe.identity(i) for i in universe.INSTRUMENTS], "itypes": universe.ITYPE_CS}


@router.get("/instruments/{code}/identity")
def instrument_identity(code: str):
    inst = universe.get(code)
    if inst is None:
        raise HTTPException(status_code=404, detail="Tento instrument FTI nezná.")
    return {**universe.identity(inst), "data": _availability(inst)}


def _availability(inst: universe.Instrument) -> dict:
    """What FTI really gets for this instrument now: one intraday and one daily probe."""
    out = {}
    for tf in ("H1", "D1"):
        bs = bars_mod.get_bars(inst.code, tf)
        d = bs.describe()
        out[tf] = {k: d[k] for k in ("provider", "source", "kind", "kind_cs", "proxy", "close_only", "quality", "notes", "tried", "bars",
                                     "market", "last_quote")}
    return out


def _special_row(inst: universe.Instrument) -> dict | None:
    if inst.code == "DXY":
        return {"gets": "vypočtený index z kurzů (Kraken EUR, GBP, CAD, CHF + ECB JPY, SEK)", "source": "výpočet FTI",
                "verdict": "vypočtený index (proxy) — označeno", "status": quality.PROXY}
    if inst.itype == "perpetual_futures":
        from app.connectors import official_alt

        try:
            data = official_alt.kraken_perp().get(inst.symbol)
        except official_alt.OfficialUnavailable:
            data = None
        return {"gets": "funding rate a open interest (bez grafu; graf má spot " + (inst.underlying or "") + ")",
                "source": "Kraken Futures" if data else "—", "verdict": "odpovídá (positioning jedné burzy)" if data else "nedostupné",
                "status": quality.NRT if data else quality.UNAVAILABLE}
    return None


def _audit_row(inst: universe.Instrument) -> dict:
    special = _special_row(inst)
    if special:
        return {"code": inst.code, "symbol": inst.symbol, "name": inst.name, "itype_cs": universe.ITYPE_CS.get(inst.itype, inst.itype),
                **special, "limits": "; ".join(n for n in (inst.proxy_note, *inst.notes) if n) or "—",
                "recommendation": _recommendation(inst, {}, {})}
    av = _availability(inst) if inst.feeds else {}
    h1, d1 = av.get("H1") or {}, av.get("D1") or {}
    best = h1 if h1.get("bars") else d1
    matches = bool(best.get("bars")) and not best.get("proxy") and best.get("kind") not in ("reference_daily", "fixing_daily")
    if not best.get("bars"):
        gets, verdict = "nic — žádný zdroj teď nedává data", "nedostupné"
    else:
        tfs = "intradenní i denní" if h1.get("bars") else "jen denní"
        gets = f"{best.get('kind_cs')}, {tfs}"
        verdict = ("odpovídá" if matches else
                   "náhrada (proxy) — jasně označeno" if best.get("proxy") else
                   "referenční hodnota, ne tržní kotace — označeno")
    recommendation = _recommendation(inst, h1, d1)
    return {
        "code": inst.code, "symbol": inst.symbol, "name": inst.name, "itype_cs": universe.ITYPE_CS.get(inst.itype, inst.itype),
        "gets": gets, "source": best.get("source") or "—", "verdict": verdict,
        "status": (best.get("quality") or {}).get("status") or quality.UNAVAILABLE,
        "market": (best.get("market") or (h1.get("market") or d1.get("market")) or {}),
        "last_quote": best.get("last_quote") or {},
        "limits": "; ".join(dict.fromkeys((best.get("notes") or []) + list(inst.notes)))[:600] or "—",
        "recommendation": recommendation,
    }


def _recommendation(inst: universe.Instrument, h1: dict, d1: dict) -> str:
    if inst.itype in ("spot_metal", "cfd") or (inst.asset == "forex" and h1.get("provider") in (None, "kraken")):
        return ("Připojit vlastního brokera (MT5 terminál na tomto PC nebo token OANDA) — dá skutečné kotace "
                "včetně intradenní historie. Zdarma, ale vyžaduje tvůj souhlas.")
    if inst.itype == "cash_index" and not d1.get("bars"):
        return "Bez placeného zdroje nedostupné; pro obchodování použij CFD brokera (samostatný instrument .CFD)."
    if inst.itype == "cash_index":
        return "Hotovostní index má zdarma jen denní závěry; intradenně analyzovat CFD (.CFD) nebo futures."
    if inst.itype == "spot_commodity":
        return "Spot jen denně (EIA); pro intradenní analýzu CFD brokera (.CFD)."
    if inst.itype == "perpetual_futures":
        return "Ponechat jako samostatný zdroj positioningu; nikdy nezaměňovat za spot."
    if inst.itype in ("token", "calculated_index"):
        return "Ponechat jako samostatný instrument s označením proxy; nikdy nepoužívat místo podkladu."
    return "Ponechat."


@router.get("/data/audit")
def data_audit(refresh: bool = False):
    """The instrument audit: what FTI really gets for every instrument, from where, and what to fix."""
    with _audit_lock:
        hit = _audit_cache.get("audit")
        if hit and not refresh and time.monotonic() - hit[0] < AUDIT_TTL:
            return hit[1]
    asked = time.monotonic()
    with _audit_compute:  # a second request waits for the audit being computed instead of computing it all again
        with _audit_lock:
            hit = _audit_cache.get("audit")
            if hit and (hit[0] >= asked or (not refresh and time.monotonic() - hit[0] < AUDIT_TTL)):
                return hit[1]
        rows = [_audit_row(i) for i in universe.INSTRUMENTS]
        out = {"computed_at": dt.datetime.now(dt.timezone.utc), "rows": rows,
               "legend": {k: quality.LABELS_CS[k] for k in quality.LABELS_CS}}
        with _audit_lock:
            _audit_cache["audit"] = (time.monotonic(), out)
        return out


@router.get("/sources")
def sources():
    from app.market import service

    return {
        "sources": health.snapshot(),
        "stale_inputs": list(service.STALE_INPUTS.values()),
        "fred_last_source": __import__("app.connectors.fred", fromlist=["LAST_SOURCE"]).LAST_SOURCE,
        "keys": secrets.status(),
        "tickbase": __import__("app.connectors.tickbase", fromlist=["last_check"]).last_check(),
        "mt5": {"settings": settings_store.get("mt5"), "terminals": mt5.discover_terminals(), "package": _mt5_package()},
        "oanda": {"settings": settings_store.get("oanda"), "token_set": bool(secrets.get("OANDA_API_TOKEN"))},
        "legend": quality.LABELS_CS,
    }


def _mt5_package() -> bool:
    try:
        import MetaTrader5  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return False
    return True


class KeyIn(BaseModel):
    name: str
    value: str


@router.post("/keys")
def set_key(body: KeyIn):
    try:
        secrets.set_key(body.name, body.value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    bars_mod.clear_cache()
    with _audit_lock:
        _audit_cache.clear()
    return {"keys": secrets.status()}


class SettingsIn(BaseModel):
    patch: dict


@router.get("/settings")
def get_settings():
    return settings_store.load()


@router.post("/settings")
def update_settings(body: SettingsIn):
    try:
        out = settings_store.update(body.patch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    bars_mod.clear_cache()
    with _audit_lock:
        _audit_cache.clear()
    return out


@router.post("/data/test")
def data_test():
    """A real availability test of every source: one request each, content and freshness checked."""
    from app.data import probes

    if _test_lock.locked():
        raise HTTPException(status_code=409, detail="Test už běží.")
    with _test_lock:
        rows = probes.run_all()
    return {"tested_at": dt.datetime.now(dt.timezone.utc), "rows": rows}


_test_lock = threading.Lock()


@router.get("/intermarket/intel")
def intermarket_intel(tf: str = "D1", refresh: bool = False, session: Session = Depends(get_session)):
    """Intermarket Intelligence: gold's correlations with the other markets on synchronised data (D1 = US closes of the
    same day, H1 = the same UTC hours), with window, observations, significance, stability, change, breakdown,
    confirmation of gold's move, discovered pairs and lead/lag. Correlation is not causation."""
    from app.market import intermarket_intel

    if tf not in intermarket_intel.WINDOWS:
        raise HTTPException(status_code=400, detail=f"Časový rámec jen {', '.join(intermarket_intel.WINDOWS)}.")
    return intermarket_intel.get(session, tf, refresh=refresh)


@router.get("/ai/status")
def ai_status(session: Session = Depends(get_session)):
    """Groq Free state (ready / paused / limit reached …), today's usage against FTI's caps, the limits
    Groq reported, and which AI tasks have the engine inputs they need. Never the key."""
    from app.ai import guard, provider, router, tasks

    return {**provider.status(), "groq": guard.status(session), "tasks": tasks.catalog(), "providers": router.catalog()}


@router.post("/ai/test")
def ai_test(session: Session = Depends(get_session)):
    """The user's connection test: the key is checked on Groq's model list (no tokens), then one tiny
    answer (counts as 1 of the 80 daily requests) shows the real limits of the account."""
    from app.ai import groq, guard

    model = "openai/gpt-oss-20b"
    try:
        guard.check(session, model, 200, "high", require_enabled=False)
        available = groq.list_models()
    except guard.Blocked as b:
        return {"ok": False, "text": str(b), "until": b.until.isoformat() if b.until else None}
    except groq.GroqError as err:
        guard.record_failure(session, "test", model, err)
        return {"ok": False, "text": str(err)}
    free_ok = [m for m in groq.FREE_MODELS if m in available]
    guard.remember_available(available)
    try:
        reply = groq.chat([{"role": "user", "content": "Odpověz jedním slovem: OK"}], model, 64)
    except groq.GroqError as err:
        guard.record_failure(session, "test", model, err)
        return {"ok": False, "text": str(err), "models": free_ok}
    guard.record_success(session, "test", model, reply)
    return {"ok": True, "text": "Groq odpovídá, klíč funguje.", "models": free_ok, "seconds": round(reply.seconds, 2),
            "limits": reply.limits, "answer": str(reply.content)[:40]}


@router.post("/ai/test-gemini")
def ai_test_gemini(session: Session = Depends(get_session)):
    """The user's connection test of Gemini Free: the key on Google's model list (no tokens), then one tiny answer
    (counts as 1 call of FTI's daily cap). Without billing nothing can be charged."""
    from app.ai import gemini, guard

    try:
        available = gemini.list_models()
    except gemini.GroqError as err:
        return {"ok": False, "text": str(err)}
    free_ok = [m for m in gemini.FREE_MODELS if m in available]
    if not free_ok:
        return {"ok": False, "text": "Klíč funguje, ale žádný model Flash z bezplatného seznamu FTI není k dispozici.",
                "models": available[:20]}
    model = free_ok[-1]  # the lighter one for the test
    try:
        guard.check(session, model, 200, "high", require_enabled=False)
        reply = gemini.chat([{"role": "user", "content": "Odpověz jedním slovem: OK"}], model, 64)
    except guard.Blocked as b:
        return {"ok": False, "text": str(b), "until": b.until.isoformat() if b.until else None}
    except gemini.GroqError as err:
        guard.record_failure(session, "test", model, err)
        return {"ok": False, "text": str(err), "models": free_ok}
    guard.record_success(session, "test", model, reply)
    return {"ok": True, "text": f"Gemini odpovídá ({reply.model}), klíč funguje, bez billingu.", "models": free_ok,
            "seconds": round(reply.seconds, 2), "answer": str(reply.content)[:40]}


class AnalyzeIn(BaseModel):
    task: str
    code: str | None = None
    item_id: int | None = None


@router.post("/ai/analyze")
def ai_analyze(body: AnalyzeIn, session: Session = Depends(get_session)):
    """One AI analysis on request — through the same guard, cache and cooldown as the automatic ones."""
    from app.ai import tasks

    return tasks.run(session, body.task, code=(body.code or "").upper() or None, item_id=body.item_id, reason="na požádání")


@router.get("/ai/analyses")
def ai_analyses(code: str | None = None, task: str | None = None, limit: int = 10, session: Session = Depends(get_session)):
    from app.ai import tasks

    return {"analyses": tasks.history(session, code=code, task_id=task, limit=limit)}


@router.get("/data/feedcheck")
def data_feedcheck(code: str = "XAUUSD"):
    """Long-term comparison of two independent feeds (MT5 Purple × Dukascopy) on identical timestamps."""
    from app.connectors import dukascopy
    from app.data import feedcheck

    return {**feedcheck.summary(code.upper()), "dukascopy_downloads": dukascopy.stats()}


@router.get("/cloud/status")
def cloud_status():
    """Variant A: is the sync to the user's own Cloudflare Worker set up, and how did the last one go."""
    from app.cloud import sync

    return sync.status()


@router.post("/cloud/sync")
def cloud_sync():
    """Send the snapshot to the cloud now (the same as after every cycle)."""
    from app.cloud import sync

    if _sync_lock.locked():
        raise HTTPException(status_code=409, detail="Synchronizace už běží.")
    with _sync_lock:
        return sync.push()


@router.post("/cloud/token")
def cloud_token():
    """Create the sync token once (random, stored only in backend/.env). It is never returned by the API."""
    import secrets as pysecrets

    if secrets.get("FTI_SYNC_TOKEN"):
        return {"created": False, "token_set": True}
    secrets.set_key("FTI_SYNC_TOKEN", pysecrets.token_urlsafe(48))
    return {"created": True, "token_set": True}


_sync_lock = threading.Lock()


@router.post("/ai/resume")
def ai_resume(session: Session = Depends(get_session)):
    """Re-enable AI after a pause (outage) or a payment warning — the caps stay as they are."""
    from app.ai import guard

    guard.resume()
    return guard.status(session)


@router.post("/mt5/test")
def mt5_test(code: str = "XAUUSD"):
    """Try the configured MT5 terminal once (only when the user enabled it)."""
    if not mt5.enabled():
        raise HTTPException(status_code=400, detail="MT5 není zapnutý nebo není vybraný terminál.")
    try:
        bars, meta = mt5.fetch_bars(code, "H1", count=50)
    except mt5.Mt5Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "bars": len(bars), "last": bars[-1] if bars else None, **meta}
