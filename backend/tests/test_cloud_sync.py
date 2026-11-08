"""Variant A sync (app/cloud/sync.py): the PC sends only changed snapshot files to the user's own
Worker, with the token, never over plain HTTP to the internet, never the PC's private settings,
and a failure never breaks anything."""

import hashlib
import json

import httpx
import pytest

from app import export_static
from app.cloud import sync
from app.data import secrets, settings_store, store

TOKEN = "t" * 64
URL = "https://fti.example.workers.dev"
FILES = {"markets.json": '{"computed_at":"2026-11-02T10:00:00+00:00","markets":[]}', "tickers.json": '{"live":[]}'}


@pytest.fixture()
def cloud(monkeypatch):
    cfg = {"url": URL, "enabled": True}
    keys = {"FTI_SYNC_TOKEN": TOKEN}
    saved = {}
    monkeypatch.setattr(settings_store, "get", lambda path, default=None: cfg if path == "cloud" else default)
    monkeypatch.setattr(secrets, "get", lambda name: keys.get(name, ""))
    monkeypatch.setattr(store, "cache_put", lambda key, payload, source="", session=None: saved.__setitem__(key, payload))
    monkeypatch.setattr(store, "cache_get", lambda key, session=None: (saved.get(key), None))
    state = {"cfg": cfg, "keys": keys, "have": {}, "seen": [], "fail": None}

    def handler(request: httpx.Request):
        state["seen"].append(request)
        if state["fail"]:
            return httpx.Response(state["fail"])
        if request.url.path == "/internal/manifest":
            return httpx.Response(200, json={"files": state["have"]})
        if request.url.path.startswith("/internal/snapshot/"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(sync, "_transport", httpx.MockTransport(handler))
    return state


def snap(names=None):
    return {n: t for n, t in FILES.items() if names is None or n in names}, []


def test_off_until_set_up(cloud):
    cloud["cfg"]["enabled"] = False
    assert sync.push(snapshot=snap)["ok"] is False and cloud["seen"] == []
    cloud["cfg"]["enabled"] = True
    cloud["keys"].clear()
    assert sync.push(snapshot=snap)["ok"] is False and cloud["seen"] == []


def test_token_never_goes_over_plain_http_to_the_internet(cloud):
    cloud["cfg"]["url"] = "http://fti.example.workers.dev"
    r = sync.push(snapshot=snap)
    assert r["ok"] is False and "https://" in r["text"] and cloud["seen"] == []


def test_only_changed_files_are_uploaded_with_token_and_hash(cloud):
    cloud["have"] = {"tickers.json": sync.content_hash(FILES["tickers.json"])}
    r = sync.push(snapshot=snap)
    assert r["ok"] is True and r["uploaded"] == ["markets.json"] and r["unchanged"] == 1
    put = next(s for s in cloud["seen"] if s.method == "PUT")
    assert put.url.path == "/internal/snapshot/markets.json" and put.headers["authorization"] == f"Bearer {TOKEN}"
    assert put.headers["x-sha256"] == sync.content_hash(FILES["markets.json"])
    assert put.content.decode() == FILES["markets.json"]
    done = json.loads(cloud["seen"][-1].content)
    assert cloud["seen"][-1].url.path == "/internal/sync-done" and done["uploaded"] == 1


def test_light_sync_after_market_refresh_sends_only_prices(cloud):
    r = sync.push(sync.LIGHT, snapshot=snap)
    assert r["uploaded"] == ["tickers.json"]


def test_rejected_token_or_outage_is_recorded_not_raised(cloud):
    cloud["fail"] = 401
    r = sync.push(snapshot=snap)
    assert r["ok"] is False and "token" in r["text"]
    cloud["fail"] = 503
    r = sync.push(snapshot=snap)
    assert r["ok"] is False and sync.status()["last"]["ok"] is False
    assert TOKEN not in json.dumps(sync.status())


def test_after_cycle_never_raises(cloud, monkeypatch):
    def boom(names=None, now=None, snapshot=None):
        raise RuntimeError("x")

    monkeypatch.setattr(sync, "push", boom)
    assert sync.after_cycle() is None


def test_snapshot_never_contains_the_pcs_private_settings():
    class Client:
        def get(self, url):
            body = {"sources": [], "keys": [{"name": "GROQ_API_KEY", "set": True}], "mt5": {"terminal_path": "C:\\x"},
                    "oanda": {}, "legend": {}} if url == "/api/sources" else {"ok": True}
            return httpx.Response(200, json=body)

    files, problems = export_static.collect(Client(), {"sources.json", "markets.json"})
    src = json.loads(files["sources.json"])
    assert problems == [] and "keys" not in src and "mt5" not in src and "oanda" not in src


def test_bookkeeping_times_alone_do_not_cause_an_upload():
    a = '{"price":1.1,"fetched_at":"2026-11-02T10:00:00Z","last_quote":{"time":"2026-11-02T09:59:00Z","age_minutes":1}}'
    b = '{"price":1.1,"fetched_at":"2026-11-02T10:05:00Z","last_quote":{"time":"2026-11-02T09:59:00Z","age_minutes":6}}'
    c = '{"price":1.2,"fetched_at":"2026-11-02T10:05:00Z","last_quote":{"time":"2026-11-02T10:04:00Z","age_minutes":1}}'
    assert sync.content_hash(a) == sync.content_hash(b)  # same data, only the bookkeeping changed
    assert sync.content_hash(a) != sync.content_hash(c)  # a new price is always uploaded
