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

CANDLES = {"XAUUSD": ["H4", "D1", "W1"], "EURUSD": ["H4", "D1", "W1"], "GBPUSD": ["H4", "D1", "W1"],
           "USDJPY": ["D1", "W1"], "USOIL": ["D1", "W1"]}


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
    targets = {
        "/api/markets": "markets.json",
        "/api/calendar": "calendar.json",
        "/api/status": "status.json",
        "/api/dashboard": "dashboard.json",
        "/api/tickers": "tickers.json",
        "/api/metodika": "metodika.json",
        "/api/instruments/XAUUSD/analysis": "analysis-XAUUSD.json",
        "/api/instruments/XAUUSD/scores": "scores-XAUUSD.json",
        "/api/instruments/XAUUSD/news": "news-XAUUSD.json",
        "/api/instruments/XAUUSD/tra-history?days=365": "tra-XAUUSD.json",
        "/api/instruments/DXY/tra-history?days=365": "tra-DXY.json",
    }
    for code, tfs in CANDLES.items():
        for tf in tfs:
            targets[f"/api/instruments/{code}/candles?tf={tf}"] = f"candles-{code}-{tf}.json"
    problems = []
    for url, name in targets.items():
        resp = client.get(url)
        if resp.status_code != 200:
            problems.append(f"{url}: {resp.status_code} {resp.text[:120]}")
            continue
        (data / name).write_text(json.dumps(resp.json(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
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
