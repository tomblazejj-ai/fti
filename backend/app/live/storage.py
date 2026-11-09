"""What the live engine keeps (brief 9. 11. 2026, docs/fti-research.md):

  candles   market_bars, each provider its own history (ETAPA 1), from the bid
  ticks     NOT in the database — hourly gzip files (one JSON line per tick: [unix time, bid, ask, last]) under
            backend/cache/ticks/<YYYY-MM-DD>/<HH>/<code>@<provider>.jsonl.gz, kept 30 days (in the cloud: R2 files)

The table live_tick_blocks of the first test version (9. 11. 2026) is no longer written; its rows stay as they were.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import logging
import shutil
from pathlib import Path

from app.config import BACKEND_DIR
from app.data import store

log = logging.getLogger(__name__)
TICK_DIR = BACKEND_DIR / "cache" / "ticks"
KEEP_TICK_DAYS = 30
UTC = dt.timezone.utc


def _path(base: Path, code: str, provider: str, t: float) -> Path:
    d = dt.datetime.fromtimestamp(t, UTC)
    return base / d.strftime("%Y-%m-%d") / d.strftime("%H") / f"{code}@{provider}.jsonl.gz"


def save_ticks(blocks: list[tuple], base: Path | None = None) -> int:
    """blocks = [(code, provider, minute_t, rows)], rows = [[seconds into the minute, bid, ask, last], …] — appended to
    the hour's file (each append is one gzip member; gzip reads them all as one stream)."""
    base = base or TICK_DIR
    by_file: dict[Path, list[str]] = {}
    for code, provider, minute_t, rows in blocks:
        for r in rows:
            t = round(minute_t + r[0], 3)
            by_file.setdefault(_path(base, code, provider, t), []).append(json.dumps([t, r[1], r[2], r[3]], separators=(",", ":")))
    n = 0
    for path, lines in by_file.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "ab") as f:
            f.write(("\n".join(lines) + "\n").encode("utf-8"))
        n += len(lines)
    return n


def load_ticks(code: str, provider: str, since: float, until: float | None = None, base: Path | None = None) -> list[tuple]:
    """[(unix time, bid, ask, last)] of one provider from the hourly files, oldest first, without duplicates."""
    base = base or TICK_DIR
    until = until or dt.datetime.now(UTC).timestamp()
    out: dict[float, tuple] = {}
    t = since - since % 3600
    while t <= until:
        path = _path(base, code, provider, t)
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        r = json.loads(line)
                        if since <= r[0] <= until:
                            out[r[0]] = tuple(r)
        t += 3600
    return [out[k] for k in sorted(out)]


def prune_ticks(now: dt.datetime, base: Path | None = None) -> int:
    base = base or TICK_DIR
    cutoff = (now - dt.timedelta(days=KEEP_TICK_DAYS)).strftime("%Y-%m-%d")
    n = 0
    for day in base.glob("????-??-??") if base.exists() else []:
        if day.name < cutoff:
            shutil.rmtree(day, ignore_errors=True)
            n += 1
    return n


def save_candles(session, groups: list[dict]) -> int:
    n = 0
    for g in groups:
        n += store.save_bars(g["code"], g["tf"], g["rows"], g["provider"], session=session, meta={
            "feed_symbol": g["symbol"], "quality": "LIVE", "origin": g["product"][:120], "price_type": g["price_type"],
            "complete_until": g.get("complete_until")})
    return n


def load_own_candles(session, code: str, provider: str, tf: str, since: int) -> list[tuple]:
    """The provider's own stored candles (bid) — where the live candles continue after a restart."""
    return [(int(r[0]), r[1], r[2], r[3], r[4]) for r in store.load_bars(code, tf, provider, since=since, session=session)]
