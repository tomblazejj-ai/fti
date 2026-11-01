"""FTI platform API: instrument identities and the data audit, source monitoring, settings and
keys (keys are write-only: the API never returns a key, only whether it is set)."""

from __future__ import annotations

import datetime as dt
import threading
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.data import bars as bars_mod
from app.data import health, mt5, quality, secrets, settings_store, universe

router = APIRouter(prefix="/api")
_audit_cache: dict[str, tuple[float, object]] = {}
_audit_lock = threading.Lock()
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
        out[tf] = {k: d[k] for k in ("provider", "source", "kind", "kind_cs", "proxy", "close_only", "quality", "notes", "tried", "bars")}
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


@router.get("/ai/status")
def ai_status():
    from app.ai import provider

    return provider.status()


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
