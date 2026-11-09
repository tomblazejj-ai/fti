"""Static snapshot of the platform for the phone version (no server needed).

    python -m app.export_static <out_dir> [--cycle]

Writes every API answer the web app reads into <out_dir>/data/*.json — the same JSON
the FastAPI server returns, produced by calling the real endpoints in-process. The web
app built with VITE_STATIC=1 reads these files instead of /api/…, so the whole platform
can sit on free static hosting (e.g. GitHub Pages) and be opened on a phone anywhere;
live prices come straight from Kraken's public API in the browser.

`--cycle` first runs one full data cycle (what the desktop app does every 30 minutes).
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# each instrument's own data only (XAUUSD without a broker feed has just the NBP daily reference)
CANDLES = {"XAUUSD": ["H4", "D1", "W1", "MN1"], "PAXGUSD": ["H4", "D1", "W1", "MN1"], "EURUSD": ["H4", "D1", "W1", "MN1"],
           "GBPUSD": ["H4", "D1", "W1", "MN1"], "USDJPY": ["H4", "D1", "W1", "MN1"], "USOIL": ["D1", "W1", "MN1"]}
PRIVATE = ("mt5", "keys", "oanda")  # never published: settings and key status of this PC


def targets(names: set[str] | None = None) -> dict[str, str]:
    """API path -> snapshot file name, the same set the phone app reads (optionally only some files)."""
    out = {
        "/api/markets": "markets.json",
        "/api/calendar": "calendar.json",
        "/api/status": "status.json",
        "/api/tickers": "tickers.json",
        "/api/data/audit": "audit.json",
        "/api/sources": "sources.json",
        "/api/ai/analyses?code=XAUUSD&limit=10": "ai.json",  # the last AI analyses (complex one and interpretation)
        "/api/regime": "regime.json",  # market regime of gold (Ú2)
        "/api/intermarket/intel?tf=D1": "intermarket-D1.json",  # Intermarket Intelligence (synchronised correlations)
        "/api/intermarket/intel?tf=H1": "intermarket-H1.json",
    }
    for code, tfs in CANDLES.items():
        for tf in tfs:
            out[f"/api/instruments/{code}/candles?tf={tf}"] = f"candles-{code}-{tf}.json"
    return {u: n for u, n in out.items() if names is None or n in names}


def collect(client, names: set[str] | None = None) -> tuple[dict[str, str], list[str]]:
    """Every snapshot file as compact JSON text ({name: text}) — the PC's private settings removed."""
    files, problems = {}, []
    for url, name in targets(names).items():
        resp = client.get(url)
        if resp.status_code != 200:
            problems.append(f"{url}: {resp.status_code} {resp.text[:120]}")
            continue
        body = resp.json()
        if name == "sources.json":
            body = {k: v for k, v in body.items() if k not in PRIVATE}
        files[name] = json.dumps(_without_tickbase_prices(body), ensure_ascii=False, separators=(",", ":"))
    return files, problems


_PRICE_KEYS = ("price", "value", "bid", "ask", "quote", "last_quote")


def _without_tickbase_prices(node):
    """TickBase's terms forbid sharing its raw answers and these files are public: wherever a value came from TickBase
    (provider "tickbase" or a source named TickBase), its price is removed — FTI's own check result stays."""
    if isinstance(node, list):
        return [_without_tickbase_prices(v) for v in node]
    if not isinstance(node, dict):
        return node
    from_tickbase = node.get("provider") == "tickbase" or str(node.get("source") or "").startswith("TickBase (záloha")
    out = {}
    for k, v in node.items():
        if k == "quote" and isinstance(v, dict) and node.get("source") == "TickBase":
            continue  # the check's own copy of the price (kept only on the PC)
        if from_tickbase and k in _PRICE_KEYS:
            out[k] = None
            continue
        out[k] = _without_tickbase_prices(v)
    if from_tickbase:
        out["available"] = False
        out["note_public"] = "Záložní cena TickBase se podle jeho podmínek nezveřejňuje — jen na PC."
    return out


def export(out_dir: Path, run_cycle: bool = False) -> list[str]:
    from fastapi.testclient import TestClient

    from app.db import SessionLocal, init_db
    from app.ingestion import run_ingest
    from app.main import app

    init_db()
    if run_cycle:
        with SessionLocal() as session:
            run_ingest.compute_and_store_score(session)
    client = TestClient(app)  # no `with`: the scheduler and the desktop lifespan stay off
    data = out_dir / "data"
    data.mkdir(parents=True, exist_ok=True)
    files, problems = collect(client)
    for name, text in files.items():
        (data / name).write_text(text, encoding="utf-8")
    return problems


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.WARNING)
    if not argv:
        print(__doc__)
        return 2
    problems = export(Path(argv[0]), run_cycle="--cycle" in argv)
    for p in problems:
        print("chybí:", p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
