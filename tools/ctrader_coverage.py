"""How much history Purple Trading's cTrader really gives (master spec 2.3) — run only when the FTI app is ACTIVE.
Read-only. Nothing is assumed: depth, tick counts, bid and ask, gaps, timestamp precision, how history meets the live
price, and a comparison with Dukascopy on the same minutes (from FTI's database, read only).

    backend\\.venv\\Scripts\\python.exe tools\\ctrader_coverage.py

Writes docs/CTRADER-POKRYTI.md (private). If the depth is not enough, Dukascopy stays the main history source.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.live import ctrader_history as ch  # noqa: E402

CODES = ["XAUUSD", "EURUSD", "US500.CFD", "US100.CFD"]
DAY = 86400000
lines: list[str] = []


def utc(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime("%Y-%m-%d %H:%M")


async def has(c, kind: str, code: str, a: int, z: int, tf: str = "D1") -> bool:
    if kind == "bars":
        return bool(await c.trendbars(code, tf, a, z))
    return bool(await c.ticks(code, "bid", a, z))


async def depth(c, kind: str, code: str, window: int, tf: str = "D1", max_days: int = 365 * 25) -> int | None:
    """Oldest start (ms) of a window that still has data: steps back 1, 2, 4 … days, then halves the gap."""
    now = int(time.time() * 1000)
    good, step = None, 1
    while step <= max_days:
        a = now - step * DAY
        if await has(c, kind, code, a, a + window, tf):
            good, step = a, step * 2
        else:
            break
    if good is None:
        return None
    lo, hi = good, now - min(step, max_days) * DAY  # data at lo, none at hi (hi older)
    while lo - hi > max(window, DAY):
        mid = (lo + hi) // 2
        if await has(c, kind, code, mid, mid + window, tf):
            lo = mid
        else:
            hi = mid
    return lo


def dukascopy_m1(code: str, a_s: int, z_s: int) -> dict[int, float]:
    db = ROOT / "backend" / "fti.db"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = con.execute("select t, c from market_bars where code=? and provider='dukascopy' and tf='M1' and t between ? and ?",
                           (code, a_s, z_s)).fetchall()
        con.close()
        return dict(rows)
    except sqlite3.Error:
        return {}


async def main() -> None:
    now = int(time.time() * 1000)
    lines.extend([f"# cTrader / Purple Trading — pokrytí historie ({dt.datetime.now():%d. %m. %Y %H:%M})", "",
                  "Změřeno `tools/ctrader_coverage.py` proti demo serveru (jen čtení). Časy v UTC.", ""])
    async with ch.HistoryClient(symbols={c: c for c in CODES}, cache=False) as c:
        found = {code for _, code in c.adapter.ids.values()}
        lines += ["| Instrument | D1 od | H1 od | M1 od | ticky od | bid / ask (poslední hodina) | ticků za hodinu |",
                  "|---|---|---|---|---|---|---|"]
        for code in CODES:
            if code not in found:
                lines.append(f"| {code} | u brokera nenalezen | | | | | |")
                continue
            d1 = await depth(c, "bars", code, 31 * DAY, "D1")
            h1 = await depth(c, "bars", code, 2 * DAY, "H1", 365 * 5)
            m1 = await depth(c, "bars", code, DAY, "M1", 365 * 2)
            tk = await depth(c, "ticks", code, 3600000, max_days=365)
            bid = await c.ticks(code, "bid", now - 3600000, now)
            ask = await c.ticks(code, "ask", now - 3600000, now)
            lines.append(f"| {code} | {utc(d1) if d1 else '—'} | {utc(h1) if h1 else '—'} | {utc(m1) if m1 else '—'} | "
                         f"{utc(tk) if tk else '—'} | {'ano' if bid else 'ne'} / {'ano' if ask else 'ne'} | {len(bid)} / {len(ask)} |")
        # XAUUSD in detail: gaps, timestamp precision, history vs live, Dukascopy on the same minutes
        bars = await c.trendbars("XAUUSD", "M1", now - 5 * DAY, now - 60000)
        ts = [b[0] for b in bars]
        gaps = [(a, b) for a, b in zip(ts, ts[1:]) if b - a > 60]
        long_gaps = [(a, b) for a, b in gaps if b - a > 3 * 3600]  # daily break and weekend are expected
        lines += ["", "## XAUUSD podrobně", "",
                  f"- M1 za 5 dní: {len(bars)} svíček, mezer delších než 1 min: {len(gaps)} (z toho delších než 3 h: "
                  f"{len(long_gaps)} — denní pauza a víkend se čekají; nic se nedoplňuje)."]
        ticks = await c.ticks("XAUUSD", "bid", now - 600000, now)
        if ticks:
            ms = [t for t, _ in ticks]
            sub = sum(1 for t in ms if t % 1000) / len(ms)
            spacing = statistics.median([b - a for a, b in zip(ms, ms[1:])]) if len(ms) > 1 else None
            lines.append(f"- Přesnost času ticků: {sub:.0%} ticků má milisekundy (ne celé sekundy); medián rozestupu {spacing} ms.")
            last_bar = bars[-1] if bars else None
            if last_bar:
                in_bar = [p for t, p in ticks if last_bar[0] * 1000 <= t < last_bar[0] * 1000 + 60000]
                if in_bar:
                    lines.append(f"- Napojení historie: poslední M1 svíčka close {last_bar[4]} × poslední bid tick ve stejné minutě "
                                 f"{in_bar[-1]} (rozdíl {abs(last_bar[4] - in_bar[-1]):.3f}).")
        duk = dukascopy_m1("XAUUSD", int(ts[0]) if ts else 0, int(ts[-1]) if ts else 0)
        pairs = [(b[4], duk[b[0]]) for b in bars if b[0] in duk]
        if pairs:
            diffs = [abs(a - b) for a, b in pairs]
            lines.append(f"- Srovnání s Dukascopy (Test C, M1 close, {len(pairs)} společných minut): medián rozdílu "
                         f"{statistics.median(diffs):.3f} USD, 95. percentil {sorted(diffs)[int(len(diffs) * 0.95) - 1]:.3f} USD.")
        else:
            lines.append("- Srovnání s Dukascopy: v databázi FTI nejsou M1 Dukascopy ze stejných minut.")
        lines += ["", f"Požadavků: {c.requests['history']} historických, {c.requests['general']} ostatních, opakování {c.requests['retries']}."]
    (ROOT / "docs" / "CTRADER-POKRYTI.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    asyncio.run(main())
