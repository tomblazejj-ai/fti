"""A real availability test of every data source (Data page → "Otestovat zdroje").

Each probe makes one real request and checks the CONTENT, not just HTTP 200: how many records
came back and how old the newest one is, compared with the source's normal rhythm (and the
market state for live feeds). Probes run in parallel with a timeout; nothing is cached, so the
test always shows the state right now.
"""

from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import time
from collections.abc import Callable

from app.data import health, quality

TIMEOUT_S = 60


def _latest(d: dict) -> str | None:
    return max(d) if d else None


def _p_kraken() -> tuple[int, str | None, str]:
    import httpx

    r = httpx.get("https://api.kraken.com/0/public/OHLC", params={"pair": "XBTUSD", "interval": 1}, timeout=20).json()
    rows = next(v for k, v in r["result"].items() if k != "last")
    last = dt.datetime.fromtimestamp(int(rows[-1][0]), dt.timezone.utc).isoformat()
    return len(rows), last, "tick"


def _p_kraken_status() -> tuple[int, str | None, str]:
    import httpx

    r = httpx.get("https://api.kraken.com/0/public/SystemStatus", timeout=15).json()["result"]
    if r.get("status") != "online":
        raise RuntimeError(f"Kraken hlásí stav {r.get('status')}")
    return 1, r.get("timestamp"), "tick"


def _p_kraken_futures() -> tuple[int, str | None, str]:
    from app.connectors import official_alt

    official_alt._cache.pop("kraken_perp", None)
    d = official_alt.kraken_perp()
    return len(d), max((v.get("last_time") or "") for v in d.values()) or None, "tick"


def _p_ecb() -> tuple[int, str | None, str]:
    from app.connectors import ecb

    ecb._cache.update({"at": None, "rates": None})
    rates = ecb.fetch_history(dt.datetime.now(dt.timezone.utc))
    return len(rates), _latest(rates), "daily"


def _p_fred() -> tuple[int, str | None, str]:
    from app.connectors import fred

    obs = fred.fetch_observations("DGS10", history_days=30)
    return len(obs), obs[-1]["date"], "daily"


def _official(name: str, fn: Callable, rhythm: str) -> Callable:
    def probe():
        from app.connectors import official_alt

        official_alt._cache.clear()
        d = fn(official_alt)
        if isinstance(d, list):
            return len(d), dt.datetime.fromtimestamp(d[-1][0], dt.timezone.utc).isoformat(), rhythm
        return len(d), _latest(d), rhythm
    probe.__name__ = name
    return probe


def _p_nbp() -> tuple[int, str | None, str]:
    import httpx

    r = httpx.get("https://api.nbp.pl/api/cenyzlota/last/5/", params={"format": "json"}, timeout=20).json()
    return len(r), r[-1]["data"], "daily"


def _p_cftc() -> tuple[int, str | None, str]:
    from app.connectors import cot

    rows = cot.fetch_tff("EURO FX - CHICAGO MERCANTILE EXCHANGE", weeks=60)
    return len(rows), rows[-1]["date"], "weekly"


def _p_ff() -> tuple[int, str | None, str]:
    import httpx

    r = httpx.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=20, headers={"User-Agent": "FTI/1.0"})
    r.raise_for_status()
    rows = r.json()
    return len(rows), dt.datetime.now(dt.timezone.utc).isoformat() if rows else None, "intraday"


def _p_rss() -> tuple[int, str | None, str]:
    from app.connectors import portals

    entries, errors = portals.fetch_all()
    if not entries:
        raise RuntimeError("; ".join(errors[:3]) or "žádné zprávy")
    dated = [e.published_at for e in entries if getattr(e, "time_basis", "published") == "published"]
    newest = max(dated) if dated else None  # a fetch time is not the newest article's time
    return len(entries), newest.isoformat() if newest else None, "intraday"


def _p_worldbank() -> tuple[int, str | None, str]:
    from app.connectors import worldbank

    d = worldbank.fetch_gold_monthly(dt.datetime.now(dt.timezone.utc))
    prices = d.get("prices", {})
    last = _latest(prices)
    return len(prices), (last + "-01") if last and len(last) == 7 else last, "monthly"


PROBES: list[tuple[str, str, Callable]] = [
    ("kraken", "Kraken (spot burza)", _p_kraken),
    ("kraken_status", "Kraken — stav burzy", _p_kraken_status),
    ("kraken_futures", "Kraken Futures (funding, open interest)", _p_kraken_futures),
    ("ecb", "ECB referenční kurzy", _p_ecb),
    ("fred", "FRED", _p_fred),
    ("bls", "BLS (inflace a trh práce USA)", _official("bls", lambda o: o.bls_all()["CPIAUCSL"], "monthly")),
    ("treasury", "US Treasury (výnosy)", _official("treasury", lambda o: o.treasury("DGS10", years=1), "daily")),
    ("cboe", "CBOE (VIX)", _official("cboe", lambda o: o.cboe_history("VIX"), "daily")),
    ("eia", "EIA (WTI, Brent, plyn)", _official("eia", lambda o: o.eia_daily("RWTC"), "daily")),
    ("oecd", "OECD (CPI ostatních zemí)", _official("oecd", lambda o: o.oecd("cpi", ("CAN", "AUS"))["CAN"], "monthly")),
    ("boc", "Bank of Canada", _official("boc", lambda o: o.boc("V39079"), "daily")),
    ("snb", "SNB (Švýcarsko)", _official("snb", lambda o: o.snb_policy_rate(), "monthly")),
    ("nbp", "NBP (referenční řada zlata, jen sezónnost)", _p_nbp),
    ("worldbank", "Světová banka (měsíční ceny komodit)", _p_worldbank),
    ("cftc", "CFTC COT", _p_cftc),
    ("ffcal", "ForexFactory kalendář (export týdne)", _p_ff),
    ("rss", "Zprávy (RSS portálů a centrálních bank)", _p_rss),
]


def _verdict(rhythm: str, latest: str | None, now: dt.datetime) -> dict:
    if rhythm == "daily":
        # a daily series is fresh when its last value is from the last few business days
        return quality.classify(latest + "T23:59:00+00:00" if latest and len(latest) == 10 else latest, now, "daily")
    return quality.classify(latest, now, rhythm)


def run_all(now: dt.datetime | None = None) -> list[dict]:
    now = now or dt.datetime.now(dt.timezone.utc)
    out: list[dict] = []

    def one(key: str, name: str, fn: Callable) -> dict:
        t0 = time.monotonic()
        try:
            records, latest, rhythm = fn()
            ms = (time.monotonic() - t0) * 1000
            q = _verdict(rhythm, latest, now)
            ok = records > 0 and q["status"] != quality.STALE
            health.record(f"probe:{key}", name, ok=ok, ms=ms, records=records, data_as_of=latest,
                          error=None if ok else "data jsou starší, než je u zdroje obvyklé")
            return {"key": key, "name": name, "ok": ok, "ms": round(ms), "records": records, "latest": latest, "quality": q,
                    "error": None if ok else q["text"]}
        except Exception as exc:  # noqa: BLE001 — every failure is reported as such
            ms = (time.monotonic() - t0) * 1000
            health.record(f"probe:{key}", name, ok=False, error=str(exc)[:300])
            return {"key": key, "name": name, "ok": False, "ms": round(ms), "records": 0, "latest": None,
                    "quality": quality.classify(None, now, "daily"), "error": str(exc)[:300]}

    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(one, k, n, f): k for k, n, f in PROBES}
        for fut in cf.as_completed(futures, timeout=TIMEOUT_S * 3):
            out.append(fut.result())
    order = [k for k, _, _ in PROBES]
    return sorted(out, key=lambda r: order.index(r["key"]))
