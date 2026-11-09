"""Test A of the master spec (cTrader / Purple Trading demo) — run it only when the FTI app in openapi.ctrader.com is
ACTIVE (Submitted is not enough). Read-only: sign-in, symbols, spot prices, history; never an order.

    backend\\.venv\\Scripts\\python.exe tools\\ctrader_test_a.py

Writes docs/CTRADER-TEST-A.md (private document, not published). Every check says PASS / FAIL with what was seen;
nothing is marked verified that was not seen. Keys and tokens are never printed.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.data import secrets  # noqa: E402
from app.live import ctrader, ctrader_history as ch, ctrader_oauth  # noqa: E402
from app.live.ctrader import CTrader  # noqa: E402

CODES = ["XAUUSD", "EURUSD", "US500.CFD", "US100.CFD"]
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")


async def live_ticks(seconds: int = 60) -> dict[str, list]:
    """Spot prices of the live stream for `seconds` (the same adapter FTI streams with)."""
    adapter = CTrader({c: c for c in CODES})
    got: dict[str, list] = {c: [] for c in CODES}
    stop = asyncio.Event()

    def emit(tick):
        got.setdefault(tick.code, []).append(tick)

    task = asyncio.create_task(adapter.run(emit, stop))
    await asyncio.sleep(seconds)
    stop.set()
    await asyncio.wait_for(task, 30)
    return got


async def main() -> int:
    st = ctrader_oauth.status(None)
    check("A1 OAuth autorizace", st["access_token"] and st["refresh_token"],
          "access i refresh token uložené v backend/.env" if st["access_token"] else "chybí token — přihlas se tlačítkem v aplikaci")
    if not (st["client_id"] and st["client_secret"] and st["access_token"]):
        print("Bez klíčů a tokenu test nejde spustit.")
        return 1
    now_ms = int(time.time() * 1000)
    try:
        async with ch.HistoryClient(symbols={c: c for c in CODES}) as c:
            check("A2 připojení demo účtu Purple", c.account > 0, "demo účet nalezen a autorizován (číslo účtu se nevypisuje)")
            names = {code: name for name, code in c.adapter.ids.values()}
            check("A3 seznam instrumentů", len(names) >= 2, ", ".join(f"{k} = {v}" for k, v in names.items()) or "nic")
            for tf, days in (("M1", 1), ("D1", 365), ("MN1", 365 * 5)):
                bars = await c.trendbars("XAUUSD", tf, now_ms - days * 86400000, now_ms)
                check(f"A8 historické OHLC XAUUSD {tf}", len(bars) > 0,
                      f"{len(bars)} svíček, první {dt.datetime.fromtimestamp(bars[0][0], dt.UTC):%Y-%m-%d %H:%M} UTC" if bars else "žádné")
            for side in ("bid", "ask"):
                ticks = await c.ticks("XAUUSD", side, now_ms - 10 * 60000, now_ms)
                check(f"A9 historické ticky XAUUSD {side}", len(ticks) > 0, f"{len(ticks)} ticků za posledních 10 min")
            old = secrets.get("CTRADER_ACCESS_TOKEN")
            await c.adapter.refresh(c.ws)
            check("A10 obnova tokenu", bool(secrets.get("CTRADER_ACCESS_TOKEN")) and secrets.get("CTRADER_ACCESS_TOKEN") != old,
                  "nový access token uložený" if secrets.get("CTRADER_ACCESS_TOKEN") != old else "token se nezměnil")
    except Exception as exc:  # noqa: BLE001 — the reason is the result (e.g. the app is not Active yet)
        check("A2 připojení demo účtu Purple", False, f"{type(exc).__name__}: {exc}")
        return report()
    t0 = time.time()
    try:
        async with ch.HistoryClient(symbols={"XAUUSD": "XAUUSD"}) as c2:
            ok = c2.account > 0
        check("A11 opětovné připojení po výpadku", ok, f"nové spojení a autorizace za {time.time() - t0:.1f} s")
    except Exception as exc:  # noqa: BLE001
        check("A11 opětovné připojení po výpadku", False, str(exc))
    got = await live_ticks(60)
    for code, label in (("XAUUSD", "A4 live XAU/USD"), ("EURUSD", "A5 live EUR/USD")):
        ticks = got.get(code) or []
        check(label, len(ticks) > 0, f"{len(ticks)} kotací za 60 s")
    both = [t for t in (got.get("XAUUSD") or []) if t.bid and t.ask]
    check("A6 bid/ask", bool(both) and all(t.ask >= t.bid for t in both),
          f"poslední bid {both[-1].bid} / ask {both[-1].ask}" if both else "žádná úplná kotace")
    check("A7 tickové aktualizace", len(got.get("XAUUSD") or []) >= 10, f"{len(got.get('XAUUSD') or [])} změn XAUUSD za 60 s")
    return report()


def report() -> int:
    ok = all(r[1] for r in results)
    lines = [f"# cTrader — Test A ({dt.datetime.now():%d. %m. %Y %H:%M})", "",
             "Spuštěno `tools/ctrader_test_a.py` proti demo serveru cTrader (Purple Trading), jen čtení.", "",
             "| Test | Výsledek | Co se ukázalo |", "|---|---|---|"]
    lines += [f"| {n} | {'PASS' if o else 'FAIL'} | {d} |" for n, o, d in results]
    lines += ["", f"Celkem: {'všechny testy prošly' if ok else 'některé testy neprošly'}."]
    (ROOT / "docs" / "CTRADER-TEST-A.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    print(f"cTrader host: {ctrader.HOSTS['demo']} (jen čtení, rozsah {ctrader_oauth.SCOPE})")
    sys.exit(asyncio.run(main()))
