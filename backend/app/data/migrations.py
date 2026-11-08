"""One-time data migrations. Each runs exactly once, is recorded in schema_migrations with what it did,
never deletes or changes existing rows, and can be re-run safely (a second run inserts nothing).

split_price_bars_by_provider (2026-11-01)
    A legacy row without a recorded source gets provider "unknown" — its origin is not guessed.
    The legacy table price_bars kept ONE bar per instrument/timeframe/time for all providers together, so a
    newly connected provider (MT5) overwrote another's history (Kraken). This copies every legacy row into
    market_bars, where each provider has its own row, with the provider's price type, volume meaning and
    publication delay. price_bars itself stays exactly as it was (frozen, readable, the way back).
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import text

log = logging.getLogger(__name__)
UTC = dt.timezone.utc
LEGACY_ORIGIN = "price_bars (sdílená tabulka před oddělením zdrojů)"
TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800, "MN1": 2678400}
# what a provider's OHLC is: price type, meaning of its volume (None = no meaningful volume), known publication delay
PROVIDER_META = {
    "mt5": ("bid", "tick", None),  # MT5 candles are built from the broker's bid; volume = the broker's tick count
    "oanda": ("mid", "tick", None),
    "dukascopy": ("bid", None, 3600),  # hour files appear about an hour late; one bank's volume is not market volume
    "kraken": ("trade", "exchange", None),  # trades on the Kraken exchange; volume traded there
    "ecb": ("fixing", None, None),
    "nbp": ("fixing", None, None),
    "fred": ("close", None, None),
    "cboe": ("close", None, None),
    "eia": ("spot", None, None),
    "treasury": ("yield", None, None),
}


def _done(conn, name: str) -> bool:
    return conn.execute(text("SELECT 1 FROM schema_migrations WHERE name = :n"), {"n": name}).first() is not None


def _record(conn, name: str, details: dict) -> None:
    conn.execute(text("INSERT INTO schema_migrations (name, applied_at, details) VALUES (:n, :a, :d)"),
                 {"n": name, "a": dt.datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" "),
                  "d": __import__("json").dumps(details, ensure_ascii=False)})


def split_price_bars_by_provider(conn, now: dt.datetime | None = None) -> dict:
    from app.data import universe

    now = now or dt.datetime.now(UTC)
    now_ts = int(now.timestamp())
    received = now.astimezone(UTC).replace(tzinfo=None).isoformat(sep=" ")
    seconds = " ".join(f"WHEN '{tf}' THEN {s}" for tf, s in TF_SECONDS.items())
    before = conn.execute(text("SELECT COUNT(*) FROM market_bars")).scalar()
    legacy = conn.execute(text("SELECT COUNT(*) FROM price_bars")).scalar()
    conn.execute(text(f"""
        INSERT INTO market_bars (code, provider, feed_symbol, tf, t, o, h, l, c, v, volume_kind, price_type, closed, quality,
                                 delay_s, received_at, origin)
        SELECT code, COALESCE(NULLIF(source, ''), 'unknown'), '', tf, t, o, h, l, c, v, NULL, NULL,
               CASE WHEN t + (CASE tf {seconds} ELSE 0 END) <= :now THEN 1 ELSE 0 END, NULL, NULL, :received, :origin
        FROM price_bars WHERE true  -- SQLite needs a WHERE before ON CONFLICT in INSERT … SELECT
        ON CONFLICT (code, provider, tf, t) DO NOTHING"""), {"now": now_ts, "received": received, "origin": LEGACY_ORIGIN})
    # the newest legacy bar of every series may be a snapshot taken while it was still forming — not provably closed
    conn.execute(text("""UPDATE market_bars SET closed = 0 WHERE origin = :o AND EXISTS (
        SELECT 1 FROM (SELECT code, COALESCE(NULLIF(source, ''), 'unknown') AS provider, tf, MAX(t) AS t FROM price_bars
                       GROUP BY code, source, tf) last
        WHERE last.code = market_bars.code AND last.provider = market_bars.provider AND last.tf = market_bars.tf
        AND last.t = market_bars.t)"""), {"o": LEGACY_ORIGIN})
    for provider, (ptype, vkind, delay) in PROVIDER_META.items():
        conn.execute(text("UPDATE market_bars SET price_type = :p, volume_kind = :v, delay_s = :d "
                          "WHERE provider = :pr AND origin = :o AND price_type IS NULL"),
                     {"p": ptype, "v": vkind, "d": delay, "pr": provider, "o": LEGACY_ORIGIN})
    for inst in universe.INSTRUMENTS:
        for provider, symbol in inst.feeds:
            conn.execute(text("UPDATE market_bars SET feed_symbol = :s WHERE code = :c AND provider = :p AND feed_symbol = ''"),
                         {"s": symbol, "c": inst.code, "p": provider})
    copied = conn.execute(text("SELECT COUNT(*) FROM market_bars WHERE origin = :o"), {"o": LEGACY_ORIGIN}).scalar()
    # every legacy row must be in market_bars with identical values — otherwise the migration is not recorded
    missing = conn.execute(text("""
        SELECT COUNT(*) FROM price_bars p WHERE NOT EXISTS (
            SELECT 1 FROM market_bars m WHERE m.code = p.code AND m.provider = COALESCE(NULLIF(p.source, ''), 'unknown')
            AND m.tf = p.tf AND m.t = p.t
            AND m.o = p.o AND m.h = p.h AND m.l = p.l AND m.c = p.c)""")).scalar()
    return {"legacy_rows": legacy, "market_bars_before": before, "copied": copied, "not_identical_or_missing": missing,
            "by_provider": dict(conn.execute(text("SELECT provider, COUNT(*) FROM market_bars GROUP BY provider")).all())}


def add_news_time_basis(conn) -> dict:
    """News: record where each item's time comes from (ETAPA 2, 2026-11-07). The times themselves are not changed.
    Old rows by a fixed rule checked on the data: a time stamped by FTI in place of a missing publication time has
    microseconds and lies within 10 min of the fetch (30 rows, all of one RSS feed); feed times are whole seconds."""
    cols = {r[1] for r in conn.execute(text("PRAGMA table_info(news_items)"))}
    if "time_basis" not in cols:
        conn.execute(text("ALTER TABLE news_items ADD COLUMN time_basis VARCHAR(16)"))
    stamped = ("substr(published_at, 21, 6) NOT IN ('', '000000') "
               "AND ABS(julianday(fetched_at) - julianday(published_at)) * 86400 < 600")
    conn.execute(text(f"""UPDATE news_items SET time_basis = CASE WHEN {stamped} THEN 'fetched'
                          WHEN source LIKE 'gdelt:%' THEN 'gdelt_seen' ELSE 'published' END WHERE time_basis IS NULL"""))
    return {"time_basis": {k: v for k, v in conn.execute(text("SELECT time_basis, COUNT(*) FROM news_items GROUP BY time_basis"))}}


MIGRATIONS = [("2026-11-01_split_price_bars_by_provider", split_price_bars_by_provider),
              ("2026-11-07_news_time_basis", add_news_time_basis)]


def apply_all(bind) -> list[str]:
    """Run the migrations that have not run yet (each in its own transaction). Returns their names."""
    applied = []
    for name, fn in MIGRATIONS:
        with bind.begin() as conn:
            if _done(conn, name):
                continue
            details = fn(conn)
            if details.get("not_identical_or_missing"):
                raise RuntimeError(f"Migrace {name} neprošla kontrolou: {details}")  # rolls back, nothing recorded
            _record(conn, name, details)
            log.info("Migrace %s: %s", name, details)
            applied.append(name)
    return applied
