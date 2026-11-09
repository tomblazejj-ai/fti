"""Safe activation of Intermarket Intelligence in the live FTI (user's request 2026-11-08).

    python tools/intermarket_activation.py zkouska    rehearsal on a FRESH COPY of the live database — nothing live changes
    python tools/intermarket_activation.py zapnout    only with the user's consent: backup of fti.db and fti_settings.json,
                                                       then intermarket.enabled = true (takes effect at the next FTI start)
    python tools/intermarket_activation.py vypnout    immediate off: intermarket.enabled = false (also while FTI runs: the
                                                       next cycle reads the setting and does nothing)
    python tools/intermarket_activation.py stav       what is set and what the live database holds (read-only)
    python tools/intermarket_activation.py beh        one Intermarket step of the data cycle NOW on the live database,
                                                       exactly what FTI's cycle runs (only when switched on)

The rehearsal checks: the configuration, one limited cycle (Dukascopy at most 6 files / 90 s, FXCM at most 30 files / 90 s),
that the results and their history are written, that a Dukascopy outage stops its download without partial data while FXCM
goes on and the correlations still compute, and how long it all takes. Report: backend/cache/intermarket-activation/zkouska-<time>.json.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND / "cache" / "intermarket-activation"
UTC = dt.timezone.utc


def _stamp() -> str:
    return dt.datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")


def _copy_db(dst: Path) -> str:
    src = sqlite3.connect(f"file:{(BACKEND / 'fti.db').as_posix()}?mode=ro", uri=True)
    out = sqlite3.connect(dst)
    src.backup(out)
    ok = out.execute("pragma integrity_check").fetchone()[0]
    out.close()
    src.close()
    return ok


def rehearsal() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    copy = OUT / f"kopie-{_stamp()}.db"
    rep: dict = {"started": dt.datetime.now(UTC).isoformat(), "copy": str(copy), "copy_integrity": _copy_db(copy)}
    os.environ["DATABASE_URL"] = f"sqlite:///{copy.as_posix()}"
    os.environ["FTI_DISABLE_SCHEDULER"] = "1"
    sys.path.insert(0, str(BACKEND))
    from app.config import settings

    assert "intermarket-activation" in settings.database_url, "the rehearsal must run on the copy"
    import httpx

    from app.connectors import dukascopy
    from app.data import settings_store
    from app.db import SessionLocal
    from app.market import intermarket_data as imd
    from app.market import intermarket_intel as im

    rep["config_live"] = {"intermarket.enabled": settings_store.get("intermarket.enabled", False),
                          "mt5.enabled": settings_store.get("mt5.enabled", False)}
    real_get = settings_store.get
    settings_store.get = lambda path, default=None: True if path == "intermarket.enabled" else real_get(path, default)  # only here

    with SessionLocal() as s:
        t0 = time.monotonic()
        cycle = im.refresh(s)  # exactly what the live cycle would do once switched on
        s.commit()
        rep["cycle"] = {"seconds": round(time.monotonic() - t0, 1), "fetch": cycle.get("fetch"),
                        "D1": cycle.get("D1"), "H1": cycle.get("H1")}
        rows = s.execute(__import__("sqlalchemy").text(
            "select key, fetched_at, length(payload) from series_cache where key like 'intermarket:%' order by key")).fetchall()
        rep["written"] = [{"key": k, "at": str(a), "bytes": n} for k, a, n in rows]
        t1 = time.monotonic()
        again = im.refresh(s)  # the second run: the same data must not be recomputed
        rep["second_run"] = {"seconds": round(time.monotonic() - t1, 1), "same_fingerprint_D1":
                             again.get("D1", {}).get("fingerprint") == cycle.get("D1", {}).get("fingerprint")}
        # the source fails: the download stops at once, nothing partial is stored, the correlations still compute
        before = s.execute(__import__("sqlalchemy").text("select count(*) from market_bars where provider='dukascopy'")).scalar()
        dukascopy._transport = httpx.MockTransport(lambda req: httpx.Response(503))
        dukascopy.reset()
        both = imd.run_all(session=s)  # Dukascopy down: its run stops, FXCM's runs on its own
        out = both["dukascopy"]
        after = s.execute(__import__("sqlalchemy").text("select count(*) from market_bars where provider='dukascopy'")).scalar()
        res = im.compute(s, "D1")
        rep["outage_test"] = {"stopped_by": out.get("stopped_by"), "bars_before": before, "bars_after": after,
                              "partial_writes": after != before, "compute_ok": bool(res.get("relations")),
                              "fxcm_during_outage": {k: both["fxcm"].get(k) for k in ("outage", "stopped_by", "fetched")}}
        dukascopy._transport = None
    settings_store.get = real_get
    rep["finished"] = dt.datetime.now(UTC).isoformat()
    rep["verdict"] = ("připraveno" if rep["written"] and not rep["outage_test"]["partial_writes"] and rep["outage_test"]["compute_ok"]
                      else "NEPŘIPRAVENO — viz podrobnosti")
    path = OUT / f"zkouska-{_stamp()}.json"
    path.write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    rep["report"] = str(path)
    return rep


def _settings_backup() -> Path:
    src = BACKEND / "fti_settings.json"
    dst = BACKEND / "backups" / f"fti_settings-{_stamp()}.json"
    dst.parent.mkdir(exist_ok=True)
    shutil.copyfile(src, dst)
    return dst


def switch(on: bool) -> dict:
    sys.path.insert(0, str(BACKEND))
    from app.data import settings_store

    rep: dict = {"settings_backup": str(_settings_backup())}
    if on:
        dst = BACKEND / "backups" / f"fti-{_stamp()}-pred-intermarket.db"
        rep["db_backup"], rep["db_backup_integrity"] = str(dst), _copy_db(dst)
        if rep["db_backup_integrity"] != "ok":
            return {**rep, "error": "záloha databáze neprošla kontrolou — nic se nezapnulo"}
    settings_store.update({"intermarket": {"enabled": on}})
    rep["intermarket.enabled"] = settings_store.get("intermarket.enabled", False)
    return rep


def one_cycle() -> dict:
    """The step FTI's data cycle runs (intermarket_intel.refresh) on the live database, without opening the app."""
    sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("FTI_DISABLE_SCHEDULER", "1")
    from app.db import SessionLocal
    from app.market import intermarket_intel as im

    t0 = time.monotonic()
    with SessionLocal() as s:
        rep = im.refresh(s)
        s.commit()
    return {"seconds": round(time.monotonic() - t0, 1), **rep}


def state() -> dict:
    sys.path.insert(0, str(BACKEND))
    from app.data import settings_store

    db = sqlite3.connect(f"file:{(BACKEND / 'fti.db').as_posix()}?mode=ro", uri=True)
    rows = db.execute("select key, fetched_at from series_cache where key like 'intermarket:%'").fetchall()
    bars = db.execute("select provider, code, tf, count(*), max(t) from market_bars where provider in ('dukascopy', 'fxcm') "
                      "group by provider, code, tf").fetchall()
    return {"intermarket.enabled": settings_store.get("intermarket.enabled", False), "stored_results": rows,
            "bars": [(p, c, tf, n, dt.datetime.fromtimestamp(t, UTC).isoformat()) for p, c, tf, n, t in bars]}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = (sys.argv[1:] or ["stav"])[0]
    result = {"zkouska": rehearsal, "zapnout": lambda: switch(True), "vypnout": lambda: switch(False), "stav": state,
              "beh": one_cycle}[cmd]()
    print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
