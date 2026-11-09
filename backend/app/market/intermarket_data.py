"""Synchronised history for Intermarket Intelligence (user's request 2026-11-08) — the DATA step only.

Separate steps of the module (user's request: no needless downloads or recomputation on every run):
  1. data      this file: which files are still missing (plan), fetching them within a budget and a time limit (run)
  2. quality   intermarket_intel.series_report / _quality: observations, gaps, staleness, synchronisation
  3. compute   intermarket_intel.compute: deterministic, only when the data fingerprint changed
  4. storage   intermarket_intel.get: the result and a short history in series_cache (only when switched on)

Primary source: Dukascopy's public datafeed (free, no account) — one bank, bid prices, one UTC hour grid for every market.
Verified 8. 11. 2026: EURUSD, USDJPY, WTI (LIGHT.CMD), Brent (BRENT.CMD), S&P 500 (USA500.IDX), US dollar index
(DOLLAR.IDX), VIX (VOL.IDX) and the 30-year US T-Bond (USTBOND.TR) exist with minute candles and monthly hour files.
The index and commodity symbols are Dukascopy CFDs on futures: they move with the market, their level is not the
official one (VIX CFD 24.4 when the spot VIX closed 28.2) — labelled CFD, used for co-movement only.
The datafeed is not an official API and fails often (503, timeouts): finished months and days are cached on disk and
never asked again, an outage stops the run at once (dukascopy pauses 2 → 30 min), the next run continues. Nothing is
ever filled in: a missing hour stays missing.
Second, independent (8. 11. 2026): FXCM's public candle archive - another dealer's bid prices of EURUSD, GBPUSD, USDJPY,
USDCAD, USDCHF on the same UTC hour grid, weekly files published after the week ended (history, not the latest days). It
has its own budget and time limit (fxcm_run); run_all runs both, and one failing never stops the other.
Third: the broker's MT5 history already in FTI (never overwritten). Official daily closes (Treasury,
CBOE, FRED, EIA) for daily relationships; DXY* is also computed by ICE's formula from the broker's FX (intermarket_intel).
"""

from __future__ import annotations

import datetime as dt
import lzma
import struct
import time

from app.connectors import dukascopy

UTC = dt.timezone.utc
# FTI code -> (Dukascopy symbol, label, kind, CFD on futures?) in PRIORITY order (the dollar first: gold's main driver)
FEEDS: dict[str, tuple[str, str, str, bool]] = {
    "DXY.CFD": ("DOLLARIDXUSD", "Dolarový index (CFD na futures)", "price", True),
    "XAUUSD": ("XAUUSD", "Zlato (XAU/USD)", "price", False),
    "EURUSD": ("EURUSD", "EUR/USD", "price", False),
    "USDJPY": ("USDJPY", "USD/JPY", "price", False),
    "VIX.CFD": ("VOLIDXUSD", "VIX (CFD na futures)", "vol", True),
    "US500.CFD": ("USA500IDXUSD", "S&P 500 (CFD)", "price", True),
    "USTBOND.CFD": ("USTBONDTRUSD", "US T-Bond 30 let (CFD, cena — výnos se hýbe opačně)", "price", True),
    "USOIL.CFD": ("LIGHTCMDUSD", "Ropa WTI (CFD na futures)", "price", True),
    "UKOIL.CFD": ("BRENTCMDUSD", "Ropa Brent (CFD na futures)", "price", True),
}
CATEGORY = {"XAUUSD": "spot kov", "EURUSD": "spot FX", "USDJPY": "spot FX"}
FILES_PER_RUN = 6  # in the app: the history fills up over many cycles
SECONDS_PER_RUN = 90  # never wait longer on one source in a cycle
MONTHS = 24
RECENT_DAYS = 7


def _cached(path: str) -> bool:
    return dukascopy._cache_path(path).exists()


def _file(kind: str, sym: str, when) -> str:
    if kind == "day":
        return f"{sym}/{when.year}/{when.month - 1:02d}/{when.day:02d}/BID_candles_min_1.bi5"
    return f"{sym}/{when[0]}/{when[1] - 1:02d}/BID_candles_hour_1.bi5"


def plan(now: dt.datetime | None = None, months: int = MONTHS, days: int = RECENT_DAYS) -> list[dict]:
    """Every file still missing, in the order it should be fetched: the finished days of the last week (the freshest
    data), then month by month backwards, all markets of one month before the next month."""
    now = now or dt.datetime.now(UTC)
    days = max(days, now.day - 1) if days else 0  # the running month has no monthly file yet: all its finished days
    out = []
    for back in range(1, days + 1):
        day = now.date() - dt.timedelta(days=back)
        if day.weekday() == 5:
            continue
        for code, (sym, *_rest) in FEEDS.items():
            path = _file("day", sym, day)
            if not _cached(path):
                out.append({"code": code, "symbol": sym, "kind": "day", "date": day.isoformat(), "path": path})
    y, m = now.year, now.month
    for _ in range(months):
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        for code, (sym, *_rest) in FEEDS.items():
            path = _file("month", sym, (y, m))
            if not _cached(path):
                out.append({"code": code, "symbol": sym, "kind": "month", "year": y, "month": m, "path": path})
    return out


def _save(code: str, sym: str, tf: str, rows: list[tuple], complete_until: float, session, provider: str = "dukascopy") -> int:
    from app.data import store

    origin = {"dukascopy": f"Dukascopy datafeed {sym} ({tf}, bid)", "fxcm": f"FXCM veřejný archiv svíček {sym} ({tf}, bid)"}[provider]
    return store.save_bars(code, tf, rows, provider, session=session,
                           meta={"feed_symbol": sym, "price_type": "bid", "quality": "HISTORICAL", "complete_until": complete_until,
                                 "origin": origin})


def store_cached(session, now: dt.datetime | None = None, months: int = MONTHS, days: int = RECENT_DAYS) -> dict:
    """Put every file already on disk into the database (no download) — after a restore or a fresh database copy."""
    return {"dukascopy": run(session=session, now=now, months=months, days=days, max_files=0),
            "fxcm": fxcm_run(session=session, now=now, max_files=0, store_all=True)}


def run(session=None, now: dt.datetime | None = None, max_files: int = FILES_PER_RUN, max_seconds: float = SECONDS_PER_RUN,
        months: int = MONTHS, days: int = RECENT_DAYS) -> dict:
    """Fetch what the plan says is missing — at most `max_files` new files and `max_seconds` — and store all hours
    (and the quarter hours of the daily minute files) of every file of the plan's range. Stops at the first outage."""
    now = now or dt.datetime.now(UTC)
    t0 = time.monotonic()
    todo = plan(now, months, days)
    budget = [max_files]
    rep: dict = {"missing_before": len(todo), "fetched": 0, "outage": None, "stopped_by": None, "stored": {}, "errors": {}}
    # every period of the range: from disk when cached, downloaded when in the budget and still missing
    periods = []
    days = max(days, now.day - 1) if days else 0
    for back in range(1, days + 1):
        day = now.date() - dt.timedelta(days=back)
        if day.weekday() != 5:
            periods.append(("day", day))
    y, m = now.year, now.month
    for _ in range(months):
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        periods.append(("month", (y, m)))
    for kind, when in periods:
        for code, (sym, *_rest) in FEEDS.items():
            if rep["outage"]:
                break
            if code in rep["errors"]:
                continue
            if time.monotonic() - t0 > max_seconds and budget[0] > 0:
                budget[0] = 0  # time is up: only what is already on disk is still stored
                rep["stopped_by"] = "časový limit"
            before = budget[0]
            try:
                if kind == "day":
                    got = dukascopy._minute_day(sym, when, budget)
                else:
                    got = dukascopy.month_hours(sym, when[0], when[1], now, budget)
            except dukascopy.DukascopyUnavailable as exc:
                rep["outage"] = str(exc)
                rep["stopped_by"] = "výpadek Dukascopy"
                break
            except (lzma.LZMAError, struct.error, EOFError, ValueError) as exc:  # one broken file: only its instrument waits
                rep["fetched"] += before - budget[0]
                rep["errors"][code] = f"poškozený soubor Dukascopy ({type(exc).__name__})"
                dukascopy._cache_path(_file(kind, sym, when)).unlink(missing_ok=True)
                continue
            rep["fetched"] += before - budget[0]
            if not got:
                continue
            s = rep["stored"].setdefault(code, {"H1": 0, "M15": 0})
            if kind == "day":
                end = dt.datetime(when.year, when.month, when.day, tzinfo=UTC).timestamp() + 86400
                s["H1"] += _save(code, sym, "H1", dukascopy._aggregate(got, 3600), end, session)
                s["M15"] += _save(code, sym, "M15", dukascopy._aggregate(got, 900), end, session)
            else:
                end = dt.datetime(when[0] + (when[1] == 12), when[1] % 12 + 1, 1, tzinfo=UTC).timestamp()
                s["H1"] += _save(code, sym, "H1", got, end, session)
    if budget[0] <= 0 and not rep["stopped_by"] and plan(now, months, days):
        rep["stopped_by"] = "rozpočet souborů na běh"
    rep["missing_after"] = len(plan(now, months, days))
    rep["seconds"] = round(time.monotonic() - t0, 1)
    return rep


FXCM_FILES_PER_RUN = 30  # small files (~2.5 kB an hour-week, ~150 kB a minute-week); a separate host: its own budget
FXCM_YEARS = 2
FXCM_M1_WEEKS = 4


def fxcm_weeks(now: dt.datetime, years: int = FXCM_YEARS) -> list[tuple[int, int]]:
    """(year, week number) newest first: every week that may already be published and lies within `years`. FXCM's week
    numbers do not follow one calendar rule, so this is generous by a week on both ends; the bars carry their own times."""
    out = []
    oldest = now - dt.timedelta(days=365 * years + 14)
    for year in range(now.year, now.year - years - 1, -1):
        jan1 = dt.datetime(year, 1, 1, tzinfo=UTC)
        for week in range(53, -1, -1):
            if jan1 + dt.timedelta(weeks=week - 1) > now or jan1 + dt.timedelta(weeks=week + 1) < oldest:
                continue
            out.append((year, week))
    return out


def fxcm_run(session=None, now: dt.datetime | None = None, max_files: int = FXCM_FILES_PER_RUN,
             max_seconds: float = SECONDS_PER_RUN, years: int = FXCM_YEARS, m1_weeks: int = FXCM_M1_WEEKS,
             store_all: bool = False) -> dict:
    """FXCM's weekly hour files of the major pairs (newest first), then the minute files of the latest weeks aggregated to
    M15. Only newly fetched files are stored (store_all: everything on disk - after a restore). Independent of Dukascopy.
    A broken file or an error answer skips only its instrument for this run; when a second instrument fails too, the
    host is taken as down and FXCM's run stops (Dukascopy's goes on)."""
    from app.connectors import fxcm

    now = now or dt.datetime.now(UTC)
    t0 = time.monotonic()
    budget = [max_files]
    rep: dict = {"fetched": 0, "outage": None, "stopped_by": None, "stored": {}, "errors": {}, "weeks_on_disk": 0}
    recent: dict[str, list[tuple[int, int]]] = {}
    down: list[str] = []
    have: dict[tuple[str, str], set[int]] = {}
    if session is not None:  # which FXCM bars this database already holds (one query, not one per file)
        from sqlalchemy import select

        from app.models import MarketBar

        for code, tf, t in session.execute(select(MarketBar.code, MarketBar.tf, MarketBar.t).where(MarketBar.provider == "fxcm")):
            have.setdefault((code, tf), set()).add(int(t))

    def one(sym: str, year: int, week: int, period: str) -> list[tuple] | None:
        if sym in rep["errors"] or rep["outage"]:
            return None
        if time.monotonic() - t0 > max_seconds and budget[0] > 0:
            budget[0] = 0
            rep["stopped_by"] = "časový limit"
        before = budget[0]
        try:
            bars = fxcm.week_file(sym, year, week, now, budget, period=period)
        except fxcm.FxcmBadFile as exc:
            rep["errors"][sym] = str(exc)  # this instrument waits for the next run; the others go on
            return None
        except fxcm.FxcmUnavailable as exc:
            rep["errors"][sym] = str(exc)  # maybe only this instrument's file; a second instrument failing = the host is down
            down.append(sym)
            if len(down) >= 2:
                rep["outage"], rep["stopped_by"] = str(exc), "výpadek FXCM"
            return None
        finally:
            rep["fetched"] += before - budget[0]
        tf = "H1" if period == "H1" else "M15"
        rows = (bars if period == "H1" else dukascopy._aggregate(bars, 900)) if bars else []
        # stored when just downloaded, or when this database does not have it yet (the file cache is shared by copies)
        if rows and (store_all or budget[0] < before or rows[-1][0] not in have.get((sym, tf), ())):
            s = rep["stored"].setdefault(sym, {"H1": 0, "M15": 0})
            s[tf] += _save(sym, sym, tf, rows, bars[-1][0] + (3600 if period == "H1" else 60), session, "fxcm")
        return bars

    for year, week in fxcm_weeks(now, years):
        for sym in fxcm.SYMBOLS:
            bars = one(sym, year, week, "H1")
            if bars:
                rep["weeks_on_disk"] += 1
                if bars[-1][0] > (now - dt.timedelta(weeks=m1_weeks + 1)).timestamp():
                    recent.setdefault(sym, []).append((year, week))
    for sym, weeks in recent.items():  # quarter hours of the latest weeks from the minute files
        for year, week in weeks[:m1_weeks]:
            one(sym, year, week, "m1")
    if budget[0] <= 0 and not rep["stopped_by"]:
        rep["stopped_by"] = "rozpočet souborů na běh"
    rep["seconds"] = round(time.monotonic() - t0, 1)
    return rep


def run_all(session=None, now: dt.datetime | None = None) -> dict:
    """Both sources in one cycle, each with its own budget and time limit - one failing never blocks the other."""
    out = {}
    for name, fn in (("dukascopy", run), ("fxcm", fxcm_run)):
        try:
            out[name] = fn(session=session, now=now)
        except Exception as exc:  # noqa: BLE001 - an unexpected error of one source never stops the other
            if session is not None:
                session.rollback()
            out[name] = {"outage": f"{type(exc).__name__}: {exc}"[:200], "stopped_by": "chyba"}
    return out


def status(session) -> list[dict]:
    """What the database holds per market and timeframe (all providers) — for the report and the Data page."""
    from sqlalchemy import func, select

    from app.models import MarketBar

    codes = set(FEEDS) | {"US10Y", "US02Y", "US10YR", "VIX", "US500", "USOIL", "UKOIL", "GBPUSD", "USDCAD", "USDCHF"}
    q = (select(MarketBar.code, MarketBar.provider, MarketBar.tf, func.count(), func.min(MarketBar.t), func.max(MarketBar.t))
         .where(MarketBar.code.in_(codes)).group_by(MarketBar.code, MarketBar.provider, MarketBar.tf))
    f = lambda t: dt.datetime.fromtimestamp(t, UTC).isoformat()  # noqa: E731
    return [{"code": c, "provider": p, "tf": tf, "bars": n, "first": f(a), "last": f(b)} for c, p, tf, n, a, b in session.execute(q)]


# kept for callers of the first version
def backfill_h1(months: int = 24, now: dt.datetime | None = None, session=None, max_requests: int = FILES_PER_RUN,
                codes: list[str] | None = None) -> dict:
    return run(session=session, now=now, max_files=max_requests, months=months, days=0)


def update_recent(days: int = 10, now: dt.datetime | None = None, session=None, max_requests: int = FILES_PER_RUN,
                  codes: list[str] | None = None) -> dict:
    return run(session=session, now=now, max_files=max_requests, months=0, days=days)
