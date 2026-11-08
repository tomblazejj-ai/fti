"""Restore one provider's bars from verified backups into its own history (market_bars).

    python tools/restore_provider_history.py <target.db> <provider> <backup.db>=<label>=<backup time ISO> [...] [--dry-run]

* One transaction for everything: any error rolls the whole restore back (--dry-run always rolls back).
* Only rows of <provider> are inserted; no row of any provider is ever updated or deleted.
* A bar the provider already has is not overwritten: its values are compared and it is skipped
  (identical / different are counted separately; a different one is listed, never changed).
* Backups are used in the order given (newest first); a bar restored from a newer backup is not taken again.
* received_at = when the backup was taken (the legacy table recorded no receipt time — the backup time is the
  latest moment the bar provably existed); origin = "obnoveno ze zálohy <label>".
* closed = finished before the backup was taken AND not the newest bar of its series in that backup
  (the newest one may be a snapshot of a still forming bar).
* Running it again inserts nothing.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.data import universe  # noqa: E402
from app.data.migrations import PROVIDER_META, TF_SECONDS  # noqa: E402

UTC = dt.timezone.utc


def restore(target: str, provider: str, backups: list[tuple[str, str, str]], dry_run: bool = False) -> dict:
    ptype, vkind, delay = PROVIDER_META.get(provider, (None, None, None))
    symbols = {i.code: s for i in universe.INSTRUMENTS for p, s in i.feeds if p == provider}
    conn = sqlite3.connect(f"file:{Path(target).as_posix()}", uri=True, isolation_level=None)  # transactions by hand
    for i, (path, _label, _when) in enumerate(backups):  # ATTACH is not allowed inside a transaction
        conn.execute(f"ATTACH DATABASE ? AS bk{i}", (f"file:{Path(path).as_posix()}?mode=ro",))
    count = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
    report = {"provider": provider, "dry_run": dry_run, "before": count("SELECT COUNT(*) FROM market_bars WHERE provider=?", provider),
              "others_before": dict(conn.execute("SELECT provider, COUNT(*) FROM market_bars WHERE provider!=? GROUP BY provider",
                                                 (provider,)).fetchall()), "per_backup": {}, "different": []}
    restored: set[tuple] = set()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for i, (_path, label, when) in enumerate(backups):
            taken = dt.datetime.fromisoformat(when).astimezone(UTC)
            received = taken.replace(tzinfo=None).isoformat(sep=" ")
            newest = {(c, tf): t for c, tf, t in conn.execute(
                f"SELECT code, tf, MAX(t) FROM bk{i}.price_bars WHERE source=? GROUP BY code, tf", (provider,))}
            stats = {"candidates": 0, "inserted": 0, "skipped_identical": 0, "skipped_different": 0, "skipped_restored_from_newer_backup": 0}
            for code, tf, t, o, h, low, c, v in conn.execute(
                    f"SELECT code, tf, t, o, h, l, c, v FROM bk{i}.price_bars WHERE source=? ORDER BY code, tf, t", (provider,)).fetchall():
                key = (code, tf, t)
                existing = conn.execute("SELECT o, h, l, c FROM market_bars WHERE code=? AND provider=? AND tf=? AND t=?",
                                        (code, provider, tf, t)).fetchone()
                if key in restored:
                    stats["skipped_restored_from_newer_backup"] += 1
                    continue
                stats["candidates"] += 1
                if existing is not None:
                    if tuple(existing) == (o, h, low, c):
                        stats["skipped_identical"] += 1
                    else:
                        stats["skipped_different"] += 1
                        report["different"].append({"code": code, "tf": tf, "t": t, "kept": list(existing), "backup": [o, h, low, c]})
                    continue
                closed = int(t + TF_SECONDS.get(tf, 0) <= taken.timestamp() and t < newest[(code, tf)])
                conn.execute("""INSERT INTO market_bars (code, provider, feed_symbol, tf, t, o, h, l, c, v, volume_kind, price_type, closed,
                                quality, delay_s, received_at, origin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                             (code, provider, symbols.get(code, ""), tf, t, o, h, low, c, v if vkind else None, vkind, ptype, closed,
                              None, delay, received, f"obnoveno ze zálohy {label}"))
                restored.add(key)
                stats["inserted"] += 1
            report["per_backup"][label] = stats
        others_now = dict(conn.execute("SELECT provider, COUNT(*) FROM market_bars WHERE provider!=? GROUP BY provider",
                                       (provider,)).fetchall())
        if others_now != report["others_before"]:
            raise RuntimeError(f"jiný poskytovatel by se změnil: {others_now}")
        conn.execute("ROLLBACK" if dry_run else "COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        report["error"] = f"{type(exc).__name__}: {exc} — vše vráceno, nic se nezměnilo"
    report["after"] = count("SELECT COUNT(*) FROM market_bars WHERE provider=?", provider)
    report["others_after"] = dict(conn.execute("SELECT provider, COUNT(*) FROM market_bars WHERE provider!=? GROUP BY provider",
                                               (provider,)).fetchall())
    report["others_unchanged"] = report["others_before"] == report["others_after"]
    report["inserted_total"] = sum(s["inserted"] for s in report["per_backup"].values())
    for i in range(len(backups)):
        conn.execute(f"DETACH DATABASE bk{i}")
    conn.close()
    return report


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    target, provider, *specs = args
    print(json.dumps(restore(target, provider, [tuple(s.split("=", 2)) for s in specs], dry_run="--dry-run" in sys.argv),
                     ensure_ascii=False, indent=1))
