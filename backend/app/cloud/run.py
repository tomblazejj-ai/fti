"""One cloud run of FTI — what the desktop app does every 30 minutes, without the PC (GitHub Actions, step C1).

    python -m app.cloud.run <out_dir> --compute   data cycle → AI → snapshot files in <out_dir>/data/*.json
    python -m app.cloud.run <out_dir> --upload    send the changed files to the user's Cloudflare Worker (D1)

  compute: 1. the full data cycle (the same code as on the PC)
           2. AI after the cycle: event-driven analyses, the complex XAU/USD analysis at most 6× a day (triggers.py) —
              only when the cloud's settings switch AI on and GROQ_API_KEY is a GitHub secret
           3. the snapshot files the phone reads (also the static site on GitHub Pages)
  upload:  separate, because it signs in with GitHub's OIDC token, which is valid only a few minutes

A failure of one step never stops the next; the printed summary names every step and never a key. The exit code is
1 when the data cycle failed or the upload did not reach the cloud, so GitHub reports the run as broken.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path


def compute(out: Path) -> tuple[dict, bool]:
    from fastapi.testclient import TestClient

    from app import export_static
    from app.ai import triggers
    from app.data import health
    from app.db import SessionLocal, init_db
    from app.ingestion import run_ingest
    from app.main import app

    summary: dict = {}
    init_db()
    ok = True
    t0 = time.monotonic()
    with SessionLocal() as session:
        try:
            run_ingest.compute_and_store_score(session)
        except Exception as exc:  # noqa: BLE001 — reported, the rest still runs on the stored data
            ok = False
            summary["cycle_error"] = f"{type(exc).__name__}: {exc}"[:300]
        summary["cycle_seconds"] = round(time.monotonic() - t0)
        try:
            health.persist(session)
        except Exception:  # noqa: BLE001
            session.rollback()
        t1 = time.monotonic()
        try:
            summary["ai"] = triggers.after_cycle(session)
        except Exception as exc:  # noqa: BLE001 — AI is an overlay, the data still go out
            session.rollback()
            summary["ai_error"] = f"{type(exc).__name__}: {exc}"[:300]
        summary["ai_seconds"] = round(time.monotonic() - t1)
    files, problems = export_static.collect(TestClient(app))  # no `with`: scheduler and desktop lifespan stay off
    data = out / "data"
    data.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (data / name).write_text(text, encoding="utf-8")
    summary["files"] = len(files)
    summary["missing"] = problems[:10]
    # what this run did, for anyone without access to GitHub's logs (never a key: only whether one is set)
    from app.data import secrets

    run_info = {"finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ai_key_set": bool(secrets.get("GROQ_API_KEY")),
                **{k: v for k, v in summary.items() if k != "missing"}, "missing_count": len(problems)}
    (data / "cloud-run.json").write_text(json.dumps(run_info, ensure_ascii=False, default=str), encoding="utf-8")
    return summary, ok


def upload(out: Path) -> tuple[dict, bool]:
    from app.cloud import sync

    files = {p.name: p.read_text(encoding="utf-8") for p in sorted((out / "data").glob("*.json"))}
    pushed = sync.push(snapshot=lambda names: (files, []))
    summary = {k: pushed.get(k) for k in ("ok", "text", "unchanged", "bytes", "seconds", "problems")}
    summary["uploaded"] = len(pushed.get("uploaded") or [])
    return summary, bool(pushed.get("ok"))


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.WARNING)
    if not argv or not ({"--compute", "--upload"} & set(argv)):
        print(__doc__)
        return 2
    out = Path(argv[0])
    summary, ok = compute(out) if "--compute" in argv else upload(out)
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
