"""Source monitoring: every fetch reports success/failure, response time and record count.

Kept in memory while the app runs and written to the source_health table at the end of each
cycle (persist), so the Sources page shows status, last success, last error, lag and counts.
"""

from __future__ import annotations

import datetime as dt
import threading

_lock = threading.Lock()
_state: dict[str, dict] = {}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def record(key: str, name: str, ok: bool, ms: float | None = None, records: int | None = None, error: str | None = None,
           data_as_of: str | None = None) -> None:
    now = _now()
    with _lock:
        s = _state.setdefault(key, {"key": key, "name": name, "ok_count": 0, "error_count": 0, "last_ok": None,
                                    "last_error_at": None, "last_error": None, "last_ms": None, "last_records": None,
                                    "data_as_of": None, "last_attempt": None})
        s["name"] = name or s["name"]
        s["last_attempt"] = now
        if ok:
            s["ok_count"] += 1
            s["last_ok"] = now
            s["last_ms"] = round(ms, 1) if ms is not None else s["last_ms"]
            s["last_records"] = records if records is not None else s["last_records"]
            s["data_as_of"] = data_as_of or s["data_as_of"]
        else:
            s["error_count"] += 1
            s["last_error_at"] = now
            s["last_error"] = (error or "")[:500]


def snapshot() -> list[dict]:
    with _lock:
        rows = [dict(v) for v in _state.values()]
    for r in rows:
        r["status"] = status_of(r)
        for k in ("last_ok", "last_error_at", "last_attempt"):
            r[k] = r[k].isoformat() if isinstance(r[k], dt.datetime) else r[k]
    return sorted(rows, key=lambda r: r["name"])


def status_of(r: dict) -> str:
    """ok | degraded (last attempt failed but there was a success before) | down | unknown"""
    last_ok, last_err = r.get("last_ok"), r.get("last_error_at")
    if isinstance(last_ok, str):
        last_ok = dt.datetime.fromisoformat(last_ok)
    if isinstance(last_err, str):
        last_err = dt.datetime.fromisoformat(last_err)
    if last_ok is None and last_err is None:
        return "unknown"
    if last_err is None or (last_ok is not None and last_ok >= last_err):
        return "ok"
    return "degraded" if last_ok is not None else "down"


def persist(session) -> None:
    from app.models import SourceHealth

    for r in snapshot():
        row = session.get(SourceHealth, r["key"]) or SourceHealth(key=r["key"])
        row.name = r["name"]
        for k in ("last_attempt", "last_ok", "last_error_at"):
            setattr(row, k, dt.datetime.fromisoformat(r[k]) if r[k] else getattr(row, k))
        row.last_error = r["last_error"]
        row.ok_count, row.error_count = r["ok_count"], r["error_count"]
        row.last_ms, row.last_records, row.data_as_of = r["last_ms"], r["last_records"], r["data_as_of"]
        session.add(row)
    session.commit()


def load(session) -> None:
    """Fill the in-memory state from the table after a restart (counts and last times)."""
    from sqlalchemy import select

    from app.models import SourceHealth

    with _lock:
        for row in session.scalars(select(SourceHealth)):
            if row.key in _state:
                continue
            _state[row.key] = {"key": row.key, "name": row.name, "ok_count": row.ok_count, "error_count": row.error_count,
                               "last_ok": row.last_ok, "last_error_at": row.last_error_at, "last_error": row.last_error,
                               "last_ms": row.last_ms, "last_records": row.last_records, "data_as_of": row.data_as_of,
                               "last_attempt": row.last_attempt}


def reset() -> None:
    with _lock:
        _state.clear()
