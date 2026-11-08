"""Source monitoring: every fetch reports success/failure, response time and record count.

Kept in memory while the app runs and written to the source_health table at the end of each
cycle (persist), so the Sources page shows status, last success, last error, lag and counts.

A source is judged only by what it offers: a timeframe it does not have at all (H1 from a daily
source) is counted apart as "unsupported", never as its error; data that came but failed FTI's
quality check are "rejected", apart from outages. The status says which case applies:
ok | delayed (later than the source normally delivers) | stale | outage (the last attempt failed,
it worked before) | unavailable (never delivered) | unknown (not tried yet).
Counters the table has no columns for live in series_cache under EXTRA_KEY (no schema change).
"""

from __future__ import annotations

import datetime as dt
import threading

_lock = threading.Lock()
_state: dict[str, dict] = {}
_since: dict[str, str | None] = {"at": None}  # since when outages are counted apart from the other cases
EXTRA_KEY = "health:extra"
EXTRA_FIELDS = ("outage_count", "rejected_count", "last_rejected", "last_rejected_at", "unsupported_count", "unsupported_tfs",
                "last_quality", "expected_quality")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _row(key: str, name: str) -> dict:
    return _state.setdefault(key, {"key": key, "name": name, "ok_count": 0, "error_count": 0, "last_ok": None,
                                   "last_error_at": None, "last_error": None, "last_ms": None, "last_records": None,
                                   "data_as_of": None, "last_attempt": None, "outage_count": 0, "rejected_count": 0,
                                   "last_rejected": None, "last_rejected_at": None, "unsupported_count": 0,
                                   "unsupported_tfs": [], "last_quality": None, "expected_quality": None})


def record(key: str, name: str, ok: bool, ms: float | None = None, records: int | None = None, error: str | None = None,
           data_as_of: str | None = None, quality: str | None = None, expected: str | None = None,
           kind: str = "outage") -> None:
    """ok=True: a successful fetch (quality = the data's quality label, expected = what the source normally delivers).
    ok=False: kind "outage" (the source failed) or "rejected" (it answered, the data failed FTI's quality check)."""
    now = _now()
    with _lock:
        s = _row(key, name)
        s["name"] = name or s["name"]
        s["last_attempt"] = now
        if ok:
            s["ok_count"] += 1
            s["last_ok"] = now
            s["last_ms"] = round(ms, 1) if ms is not None else s["last_ms"]
            s["last_records"] = records if records is not None else s["last_records"]
            s["data_as_of"] = data_as_of or s["data_as_of"]
            s["last_quality"] = quality or s["last_quality"]
            s["expected_quality"] = expected or s["expected_quality"]
        elif kind == "rejected":
            s["rejected_count"] += 1
            s["last_rejected_at"] = now
            s["last_rejected"] = (error or "")[:500]
        else:
            s["error_count"] += 1
            s["outage_count"] += 1
            s["last_error_at"] = now
            s["last_error"] = (error or "")[:500]


def unsupported(key: str, name: str, tf: str) -> None:
    """The source was not asked for `tf` because it does not offer it — information, not an error."""
    with _lock:
        s = _row(key, name)
        s["unsupported_count"] += 1
        if tf not in s["unsupported_tfs"]:
            s["unsupported_tfs"] = sorted([*s["unsupported_tfs"], tf])


def snapshot() -> list[dict]:
    with _lock:
        rows = [dict(v) for v in _state.values()]
        since = _since["at"]
    for r in rows:
        r["status"] = status_of(r)
        r["counting_since"] = since
        for k in ("last_ok", "last_error_at", "last_attempt", "last_rejected_at"):
            r[k] = r[k].isoformat() if isinstance(r[k], dt.datetime) else r[k]
    return sorted(rows, key=lambda r: r["name"])


def status_of(r: dict) -> str:
    """ok | delayed | stale | outage | unavailable | unknown — see the module docstring."""
    from app.data import quality

    last_ok, last_err = r.get("last_ok"), r.get("last_error_at")
    if isinstance(last_ok, str):
        last_ok = dt.datetime.fromisoformat(last_ok)
    if isinstance(last_err, str):
        last_err = dt.datetime.fromisoformat(last_err)
    if last_ok is None and last_err is None:
        return "unknown"
    if last_err is not None and (last_ok is None or last_err > last_ok):
        return "outage" if last_ok is not None else "unavailable"
    q = r.get("last_quality")
    if q == quality.STALE:
        return "stale"
    if q == quality.UNAVAILABLE:
        return "unavailable"
    if q == quality.DELAYED and r.get("expected_quality") != quality.DELAYED:
        return "delayed"  # later than this source normally delivers (a daily source's yesterday value is not "late")
    return "ok"


def persist(session) -> None:
    from app.data import store
    from app.models import SourceHealth

    with _lock:
        _since["at"] = _since["at"] or _now().isoformat()
    rows = snapshot()
    for r in rows:
        row = session.get(SourceHealth, r["key"]) or SourceHealth(key=r["key"])
        row.name = r["name"]
        for k in ("last_attempt", "last_ok", "last_error_at"):
            setattr(row, k, dt.datetime.fromisoformat(r[k]) if r[k] else getattr(row, k))
        row.last_error = r["last_error"]
        row.ok_count, row.error_count = r["ok_count"], r["error_count"]
        row.last_ms, row.last_records, row.data_as_of = r["last_ms"], r["last_records"], r["data_as_of"]
        session.add(row)
    session.commit()
    store.cache_put(EXTRA_KEY, {"since": _since["at"], "rows": {r["key"]: {k: r[k] for k in EXTRA_FIELDS} for r in rows}},
                    source="FTI monitoring", session=session)


def load(session) -> None:
    """Fill the in-memory state from the table after a restart (counts and last times)."""
    from sqlalchemy import select

    from app.data import store
    from app.models import SourceHealth

    extra, _ = store.cache_get(EXTRA_KEY, session=session)
    extra = extra if isinstance(extra, dict) else {}
    with _lock:
        _since["at"] = _since["at"] or extra.get("since")
        for row in session.scalars(select(SourceHealth)):
            if row.key in _state:
                continue
            s = _row(row.key, row.name)
            s.update({"ok_count": row.ok_count, "error_count": row.error_count, "last_ok": row.last_ok,
                      "last_error_at": row.last_error_at, "last_error": row.last_error, "last_ms": row.last_ms,
                      "last_records": row.last_records, "data_as_of": row.data_as_of, "last_attempt": row.last_attempt})
            s.update({k: v for k, v in (extra.get("rows") or {}).get(row.key, {}).items() if k in EXTRA_FIELDS})
            if isinstance(s.get("last_rejected_at"), str):
                s["last_rejected_at"] = dt.datetime.fromisoformat(s["last_rejected_at"])
            if kind_of(s["last_error"]) != "outage":
                # stored before the fix, when "no H1 from a daily source" and rejected data counted as outages:
                # it does not make the source look down now (the table keeps the record as it was)
                s["last_error_at"] = None


def kind_of(error: str | None) -> str:
    """The case an error text from before the fix belongs to: unsupported | rejected | outage."""
    text = error or ""
    if "má jen denní data, ne " in text or ("rámec" in text and "nepodporuje" in text):
        return "unsupported"
    if "kotace nespolehlivá" in text or "neplatné svíčky" in text:
        return "rejected"
    return "outage"


def reset() -> None:
    with _lock:
        _state.clear()
        _since["at"] = None
