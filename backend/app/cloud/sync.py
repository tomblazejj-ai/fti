"""Cloud sync (variant A): the Python engine on this PC stays the only place where FTI computes.
After each cycle it sends the same snapshot files the phone app reads (markets, calendar, tickers,
audit, sources, charts) to the user's own Cloudflare Worker, which keeps them in D1 and serves them
to the phone even when this PC is off — always with the time of the last computation.

  * off until both the Worker address (Settings → cloud.url) and FTI_SYNC_TOKEN (backend/.env) are set
  * only changed files are uploaded (the Worker reports what it already has) — D1 free has 100 000 writes a day
  * the PC's private settings and keys are never part of the snapshot (export_static.PRIVATE)
  * a failure is recorded and shown, it never breaks the cycle and is never retried in a loop
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import time

import httpx

from app.ai.redact import redact
from app.data import secrets, settings_store, store

log = logging.getLogger(__name__)
UTC = dt.timezone.utc
TOKEN_NAME = "FTI_SYNC_TOKEN"
STATE_KEY = "cloud:sync"
TIMEOUT = httpx.Timeout(30.0, connect=5.0)
MAX_FILE_BYTES = 1_900_000  # one D1 row holds at most 2 000 000 bytes
LIGHT = {"tickers.json", "status.json"}  # after the 5-minute market refresh
_transport: httpx.BaseTransport | None = None  # tests inject an httpx.MockTransport


def config() -> dict:
    cfg = settings_store.get("cloud", {}) or {}
    url = str(cfg.get("url") or "").strip().rstrip("/")
    return {"url": url, "enabled": bool(cfg.get("enabled")), "token_set": bool(secrets.get(TOKEN_NAME))}


# bookkeeping times that change on every request although the data did not (when it was fetched, how
# old it was at that moment) — the phone recomputes ages itself from the real quote times
VOLATILE = {"fetched_at", "age_minutes", "age_hours", "checked_at"}


def content_hash(text: str) -> str:
    """SHA-256 of the data without the bookkeeping times: a file is uploaded only when real data changed."""
    import json

    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k not in VOLATILE}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    try:
        canon = json.dumps(strip(json.loads(text)), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except ValueError:
        canon = text
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _safe_url(url: str) -> bool:
    """The token only ever travels over HTTPS (plain HTTP only to this PC, for the local test Worker)."""
    return url.startswith("https://") or url.startswith(("http://127.0.0.1:", "http://localhost:"))


def _client(token: str) -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, transport=_transport, follow_redirects=False,
                        headers={"Authorization": f"Bearer {token}", "User-Agent": "FTI-sync/1.0"})


def _snapshot(names: set[str] | None) -> tuple[dict[str, str], list[str]]:
    from fastapi.testclient import TestClient

    from app import export_static
    from app.main import app

    return export_static.collect(TestClient(app), names)


def _remember(result: dict) -> None:
    store.cache_put(STATE_KEY, result, source="FTI cloud sync")


def push(names: set[str] | None = None, now: dt.datetime | None = None, snapshot=None) -> dict:
    """Upload changed snapshot files. Returns {ok, text, uploaded, unchanged, bytes, problems, at}."""
    now = now or dt.datetime.now(UTC)
    c = config()
    token = secrets.get(TOKEN_NAME)
    if not (c["enabled"] and c["url"] and token):
        return {"ok": False, "text": "Synchronizace s cloudem není nastavená.", "at": now.isoformat()}
    if not _safe_url(c["url"]):
        return {"ok": False, "text": "Adresa cloudu musí začínat https:// — token se jinak neposílá.", "at": now.isoformat()}
    t0 = time.monotonic()
    files, problems = (snapshot or _snapshot)(names)
    out = {"ok": False, "uploaded": [], "unchanged": 0, "bytes": 0, "problems": problems[:10], "at": now.isoformat()}
    try:
        with _client(token) as cl:
            r = cl.get(f"{c['url']}/internal/manifest")
            if r.status_code in (401, 403):
                raise RuntimeError("Cloud odmítl token synchronizace (FTI_SYNC_TOKEN se neshoduje s tajnou hodnotou Workeru).")
            r.raise_for_status()
            have = (r.json() or {}).get("files") or {}
            for name, text in files.items():
                raw = text.encode("utf-8")
                if len(raw) > MAX_FILE_BYTES:
                    out["problems"].append(f"{name}: {len(raw)} B je víc, než se vejde do jednoho řádku D1")
                    continue
                sha = content_hash(text)
                if have.get(name) == sha:
                    out["unchanged"] += 1
                    continue
                up = cl.put(f"{c['url']}/internal/snapshot/{name}", content=raw,
                            headers={"Content-Type": "application/json", "X-Sha256": sha, "X-Computed-At": now.isoformat()})
                up.raise_for_status()
                out["uploaded"].append(name)
                out["bytes"] += len(raw)
            cl.post(f"{c['url']}/internal/sync-done", json={"uploaded": len(out["uploaded"]), "unchanged": out["unchanged"],
                                                            "bytes": out["bytes"], "computed_at": now.isoformat(),
                                                            "problems": len(out["problems"])})
        out["ok"] = True
        out["text"] = f"Odesláno {len(out['uploaded'])} změněných souborů, beze změny {out['unchanged']}."
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        out["text"] = redact(f"Synchronizace selhala: {exc}")
        log.warning(out["text"])
    out["seconds"] = round(time.monotonic() - t0, 2)
    _remember(out)
    return out


def after_cycle(light: bool = False) -> dict | None:
    """Called by the scheduler; never raises."""
    if not config()["enabled"]:
        return None
    try:
        return push(LIGHT if light else None)
    except Exception:  # noqa: BLE001 — the cloud is an extra: FTI on the PC works the same without it
        log.exception("Cloud sync failed")
        return None


def status() -> dict:
    last, _ = store.cache_get(STATE_KEY)
    c = config()
    return {**c, "last": last, "cost": "0 Kč — Cloudflare Workers a D1 v bezplatném tarifu, bez platební metody"}
