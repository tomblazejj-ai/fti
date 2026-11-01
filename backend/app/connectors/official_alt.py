"""Official keyless sources that back up FRED and add the markets FRED does not cover.

All checked live 2026-11-01, free, no registration:
  * BLS public API v1 (api.bls.gov/publicAPI/v1) — CPI, core CPI, unemployment, payrolls.
    Keyless limit: 25 queries a day, so all series go in ONE query, cached 12 hours.
  * US Treasury daily par yield curve + real yield curve (home.treasury.gov CSV) — 2Y/10Y
    nominal and 10Y real yields, the official source of FRED's DGS2/DGS10/DFII10.
  * CBOE daily index history (cdn.cboe.com) — VIX open/high/low/close since 1990.
  * EIA daily spot prices (XLS of each eia.gov series page) — WTI, Brent, Henry Hub gas.
  * OECD Data Explorer API (sdmx.oecd.org, CC BY 4.0) — CPI, unemployment, short-term rates
    of Canada, Australia, New Zealand, Switzerland and others.
  * Bank of Canada Valet API — policy rate and 2-year bond yield.
  * SNB data portal — Swiss policy rate.
  * Kraken Futures public tickers — funding rate and open interest of BTC/ETH perpetuals
    (real data of ONE exchange, labelled as such).
Rejected: RBA and RBNZ statistics (HTTP 403 for scripts), Stooq (robots.txt: Disallow /),
LBMA price JSON (HTTP 403).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import threading
import time

import httpx

UA = {"User-Agent": "FTI/1.0 (personal market analysis; contact via GitHub tomblazejj-ai/fti)"}
_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


class OfficialUnavailable(RuntimeError):
    pass


def _cached(key: str, ttl: float, fn):
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
    value = fn()
    with _lock:
        _cache[key] = (time.monotonic(), value)
    return value


def _get(url: str, params: dict | None = None, timeout: float = 40.0, retries: int = 2) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, headers=UA) as c:
                r = c.get(url, params=params)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except httpx.HTTPError as exc:
            last = exc
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise OfficialUnavailable(f"{url.split('/')[2]}: {last}")


# --- BLS ---------------------------------------------------------------------------------------
BLS_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
BLS_SERIES = {
    "CPIAUCSL": "CUSR0000SA0",  # CPI-U all items, seasonally adjusted, index
    "CPILFESL": "CUSR0000SA0L1E",  # core CPI, SA, index
    "UNRATE": "LNS14000000",  # unemployment rate, SA, %
    "PAYEMS": "CES0000000001",  # nonfarm payrolls, SA, thousands
}


def bls_all() -> dict[str, dict[str, float]]:
    """{FRED id: {YYYY-MM-01: value}} for the BLS-backed series, one keyless query (cached 12 h)."""
    def fetch():
        year = dt.date.today().year
        try:
            with httpx.Client(timeout=40.0, headers={**UA, "Content-Type": "application/json"}) as c:
                r = c.post(BLS_URL, json={"seriesid": list(BLS_SERIES.values()), "startyear": str(year - 3), "endyear": str(year)})
            r.raise_for_status()
            body = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OfficialUnavailable(f"BLS: {exc}") from exc
        if body.get("status") != "REQUEST_SUCCEEDED":
            raise OfficialUnavailable(f"BLS: {'; '.join(body.get('message') or []) or body.get('status')}")
        by_bls = {s["seriesID"]: s.get("data", []) for s in body.get("Results", {}).get("series", [])}
        out: dict[str, dict[str, float]] = {}
        for fred_id, bls_id in BLS_SERIES.items():
            rows = {}
            for d in by_bls.get(bls_id, []):
                if not str(d.get("period", "")).startswith("M") or d["period"] == "M13":
                    continue
                try:
                    rows[f"{d['year']}-{d['period'][1:]}-01"] = float(d["value"])
                except (KeyError, ValueError):
                    continue
            if rows:
                out[fred_id] = dict(sorted(rows.items()))
        if not out:
            raise OfficialUnavailable("BLS nevrátil žádná data")
        return out
    return _cached("bls", 12 * 3600, fetch)


# --- US Treasury -------------------------------------------------------------------------------
TREASURY_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all"
TREASURY_SERIES = {"DGS2": ("daily_treasury_yield_curve", "2 Yr"), "DGS10": ("daily_treasury_yield_curve", "10 Yr"),
                   "DGS3MO": ("daily_treasury_yield_curve", "3 Mo"), "DFII10": ("daily_treasury_real_yield_curve", "10 YR"),
                   "DFII5": ("daily_treasury_real_yield_curve", "5 YR")}


def _treasury_year(kind: str, year: int) -> list[dict]:
    r = _get(TREASURY_URL.format(year=year), params={"type": kind, "field_tdr_date_value": year, "page": "", "_format": "csv"})
    return list(csv.DictReader(io.StringIO(r.text)))


def treasury(series: str, years: int = 3) -> dict[str, float]:
    """{YYYY-MM-DD: yield %} for DGS2 / DGS10 / DGS3MO / DFII10 / DFII5 from the Treasury itself."""
    kind, col = TREASURY_SERIES[series]

    def fetch():
        out = {}
        this = dt.date.today().year
        for y in range(this - years + 1, this + 1):
            for row in _treasury_year(kind, y):
                try:
                    d = dt.datetime.strptime(row["Date"], "%m/%d/%Y").date().isoformat()
                    out[d] = float(row[col])
                except (KeyError, ValueError):
                    continue
        if len(out) < 20:
            raise OfficialUnavailable(f"Treasury {series}: málo dat")
        return dict(sorted(out.items()))
    return _cached(f"treasury:{series}:{years}", 3 * 3600, fetch)


# --- CBOE --------------------------------------------------------------------------------------
CBOE_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{sym}_History.csv"


def cboe_history(sym: str = "VIX") -> list[tuple]:
    def fetch():
        r = _get(CBOE_URL.format(sym=sym))
        out = []
        for row in csv.DictReader(io.StringIO(r.text)):
            try:
                d = dt.datetime.strptime(row["DATE"], "%m/%d/%Y").replace(tzinfo=dt.timezone.utc)
                out.append((int(d.timestamp()), float(row["OPEN"]), float(row["HIGH"]), float(row["LOW"]), float(row["CLOSE"]), None))
            except (KeyError, ValueError):
                continue
        if len(out) < 100:
            raise OfficialUnavailable(f"CBOE {sym}: málo dat")
        return out
    return _cached(f"cboe:{sym}", 3 * 3600, fetch)


def vix_closes() -> dict[str, float]:
    return {dt.datetime.fromtimestamp(b[0], dt.timezone.utc).date().isoformat(): b[4] for b in cboe_history("VIX")}


# --- EIA daily spot ----------------------------------------------------------------------------
EIA_DAILY = {"RWTC": "https://www.eia.gov/dnav/pet/hist_xls/RWTCd.xls",
             "RBRTE": "https://www.eia.gov/dnav/pet/hist_xls/RBRTEd.xls",
             "RNGWHHD": "https://www.eia.gov/dnav/ng/hist_xls/RNGWHHDd.xls"}


def eia_daily(series: str) -> dict[str, float]:
    import xlrd

    def fetch():
        r = _get(EIA_DAILY[series], timeout=60.0)
        try:
            book = xlrd.open_workbook(file_contents=r.content)
            sheet = book.sheet_by_name("Data 1")
            out = {}
            for i in range(3, sheet.nrows):
                d, v = sheet.cell_value(i, 0), sheet.cell_value(i, 1)
                if isinstance(d, float) and isinstance(v, float) and v > 0:
                    out[xlrd.xldate_as_datetime(d, book.datemode).date().isoformat()] = v
        except Exception as exc:  # noqa: BLE001 — a format surprise is "unavailable", never a guess
            raise OfficialUnavailable(f"EIA {series}: nečekaný formát ({exc})") from exc
        if len(out) < 100:
            raise OfficialUnavailable(f"EIA {series}: málo dat")
        return out
    return _cached(f"eia:{series}", 6 * 3600, fetch)


# --- OECD --------------------------------------------------------------------------------------
OECD = "https://sdmx.oecd.org/public/rest/data/"
OECD_FLOWS = {
    "cpi": "OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0/{areas}.{freq}.N.CPI.PA._T.N.GY",
    "unemp": "OECD.SDD.TPS,DSD_LFS@DF_IALFS_UNE_M,1.0/{areas}.UNE_LF_M.PT_LF_SUB._Z.Y._T.Y_GE15._Z.M",
    "rate3m": "OECD.SDD.STES,DSD_STES@DF_FINMARK,4.0/{areas}.M.IR3TIB.PA.....",
    "rate10y": "OECD.SDD.STES,DSD_STES@DF_FINMARK,4.0/{areas}.M.IRLT.PA.....",
}


def oecd(measure: str, areas: tuple[str, ...], freq: str = "M", start: str = "2022-01") -> dict[str, dict[str, float]]:
    """{area: {YYYY-MM-01: value}} — monthly (or quarterly with freq="Q": first month of the quarter)."""
    key = f"oecd:{measure}:{'+'.join(areas)}:{freq}:{start}"

    def fetch():
        path = OECD_FLOWS[measure].format(areas="+".join(areas), freq=freq)
        r = _get(OECD + path, params={"startPeriod": start if freq == "M" else start[:4] + "-Q1", "format": "csvfile"}, timeout=60.0)
        out: dict[str, dict[str, float]] = {}
        for row in csv.DictReader(io.StringIO(r.text)):
            try:
                p, v = row["TIME_PERIOD"], float(row["OBS_VALUE"])
            except (KeyError, ValueError):
                continue
            if "-Q" in p:
                y, q = p.split("-Q")
                p = f"{y}-{(int(q) - 1) * 3 + 1:02d}"
            out.setdefault(row["REF_AREA"], {})[f"{p[:7]}-01"] = v
        if not out:
            raise OfficialUnavailable(f"OECD {measure}: žádná data")
        return {a: dict(sorted(s.items())) for a, s in out.items()}
    return _cached(key, 12 * 3600, fetch)


# --- Bank of Canada, SNB -----------------------------------------------------------------------
def boc(series: str, recent: int = 800) -> dict[str, float]:
    """Bank of Canada Valet: V39079 = policy rate target, BD.CDN.2YR.DQ.YLD = 2-year yield."""
    def fetch():
        r = _get(f"https://www.bankofcanada.ca/valet/observations/{series}/json", params={"recent": recent})
        out = {}
        for o in r.json().get("observations", []):
            try:
                out[o["d"]] = float(o[series]["v"])
            except (KeyError, ValueError, TypeError):
                continue
        if not out:
            raise OfficialUnavailable(f"Bank of Canada {series}: žádná data")
        return dict(sorted(out.items()))
    return _cached(f"boc:{series}:{recent}", 6 * 3600, fetch)


def snb_policy_rate() -> dict[str, float]:
    """SNB policy rate (cube snbgwdzid, series LZ = SNB policy rate), {YYYY-MM-DD: %}."""
    def fetch():
        r = _get("https://data.snb.ch/api/cube/snbgwdzid/data/csv/en")
        text = r.content.decode("utf-8-sig")
        out = {}
        for line in text.splitlines():
            parts = [p.strip().strip('"') for p in line.split(";")]
            if len(parts) == 3 and parts[1] == "LZ":
                try:
                    out[parts[0]] = float(parts[2])
                except ValueError:
                    continue
        if not out:
            raise OfficialUnavailable("SNB: řada sazby nenalezena")
        return dict(sorted(out.items()))
    return _cached("snb:policy", 12 * 3600, fetch)


# --- Kraken Futures ----------------------------------------------------------------------------
def kraken_perp(symbols: tuple[str, ...] = ("PF_XBTUSD", "PF_ETHUSD", "PF_SOLUSD")) -> dict[str, dict]:
    """Funding rate (relative, per hour) and open interest of Kraken's perpetual futures."""
    def fetch():
        r = _get("https://futures.kraken.com/derivatives/api/v3/tickers")
        out = {}
        for t in r.json().get("tickers", []):
            if t.get("symbol") in symbols:
                out[t["symbol"]] = {"funding_rate": t.get("fundingRate"), "funding_rate_prediction": t.get("fundingRatePrediction"),
                                    "open_interest": t.get("openInterest"), "mark_price": t.get("markPrice"),
                                    "last_time": t.get("lastTime")}
        if not out:
            raise OfficialUnavailable("Kraken Futures: žádná data")
        return out
    return _cached("kraken_perp", 300, fetch)
