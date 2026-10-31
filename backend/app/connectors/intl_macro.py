"""Official macro data for the euro area, the UK and Japan + US oil inventories.

All free, no key, no registration; checked live 2026-10-31:
  * ECB Data Portal (data-api.ecb.europa.eu, SDMX csvdata) — euro area HICP until 12/2025,
    unemployment, 2-year AAA government yield (daily)
  * Eurostat API (prc_hicp_minr) — euro area HICP from 2026 on (ECOICOP version 2)
  * ONS (www.ons.gov.uk/<series>/data, the JSON behind every ONS time-series page) — UK CPI,
    core CPI, unemployment, GDP q/q, retail sales volume
  * Ministry of Finance Japan (mof.go.jp, CSV of JGB yields) — 2-year JGB yield (daily)
  * EIA (eia.gov/dnav, the XLS download of every series page) — weekly US crude stocks
FRED (keyless CSV, see fred.py) adds euro GDP, the ECB deposit rate, SONIA, Japan
unemployment, Japan GDP and the Japan call rate.

The Bank of England database (IADB) is NOT used: its robots.txt disallows bots.
Japan CPI has no free source without registration (e-Stat needs an app ID, OECD and
FRED copies stopped in 2021) — the Japanese inflation category is left without data.

Every function returns {"YYYY-MM-DD": value} (monthly series on the 1st of the month,
quarterly on the 1st month of the quarter) or raises MacroUnavailableError.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re

import httpx

UA = {"User-Agent": "Mozilla/5.0 (compatible; fundamental-trading-intelligence/0.8)"}
ECB_URL = "https://data-api.ecb.europa.eu/service/data/{flow}/{key}"
ONS_URL = "https://www.ons.gov.uk/{path}/data"
MOF_HIST = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"
MOF_NOW = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"
EIA_XLS = "https://www.eia.gov/dnav/pet/hist_xls/{series}w.xls"
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}

# Euro area — ECB Data Portal keys
ECB_HICP = ("ICP", "M.U2.N.000000.4.ANR")  # HICP all items, annual rate of change
ECB_CORE = ("ICP", "M.U2.N.XEF000.4.ANR")  # HICP excl. energy, food, alcohol & tobacco
ECB_UNEMP = ("LFSI", "M.I9.S.UNEHRT.TOTAL0.15_74.T")  # unemployment rate, %
ECB_2Y = ("YC", "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y")  # 2-year AAA euro government spot rate, daily

# Since 2026 the HICP uses ECOICOP version 2: the ECB's ICP series above stop at 12/2025 and
# Eurostat publishes the new ones (dataset prc_hicp_minr, annual rate of change). Checked 2026-10-31.
EUROSTAT_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset}"
EUROSTAT_HICP_TOTAL = "TOTAL"
EUROSTAT_HICP_CORE = "TOT_X_NRG_FOOD"  # excluding energy, food, alcohol & tobacco

# United Kingdom — ONS time series (path = topic/timeseries/<id>/<dataset>)
ONS_CPI = "economy/inflationandpriceindices/timeseries/d7g7/mm23"
ONS_CORE = "economy/inflationandpriceindices/timeseries/dko8/mm23"
ONS_UNEMP = "employmentandlabourmarket/peoplenotinwork/unemployment/timeseries/mgsx/lms"
ONS_GDP = "economy/grossdomesticproductgdp/timeseries/ihyq/qna"
ONS_RETAIL = "businessindustryandtrade/retailindustry/timeseries/j5ek/drsi"

EIA_CRUDE = "WCESTUS1"  # weekly US ending stocks of crude oil excluding SPR, thousand barrels


class MacroUnavailableError(RuntimeError):
    pass


def _client(client: httpx.Client | None) -> tuple[httpx.Client, bool]:
    return (client, False) if client else (httpx.Client(timeout=45.0, follow_redirects=True, headers=UA), True)


def ecb_series(flow: str, key: str, start: str = "2018-01", client: httpx.Client | None = None) -> dict[str, float]:
    c, owns = _client(client)
    try:
        resp = c.get(ECB_URL.format(flow=flow, key=key), params={"startPeriod": start, "format": "csvdata"})
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise MacroUnavailableError(f"ECB {flow}.{key}: {exc}") from exc
    finally:
        if owns:
            c.close()
    out: dict[str, float] = {}
    for row in csv.DictReader(io.StringIO(resp.text)):
        period, value = row.get("TIME_PERIOD", ""), row.get("OBS_VALUE", "")
        if not value:
            continue
        day = f"{period}-01" if len(period) == 7 else period
        try:
            out[day] = float(value)
        except ValueError:
            continue
    if not out:
        raise MacroUnavailableError(f"ECB {flow}.{key}: žádná data")
    return out


def eurostat_hicp(coicop: str, since: str = "2024-01", client: httpx.Client | None = None) -> dict[str, float]:
    """Euro-area HICP, annual rate of change (JSON-stat from the Eurostat API)."""
    c, owns = _client(client)
    try:
        resp = c.get(EUROSTAT_URL.format(dataset="prc_hicp_minr"),
                     params={"geo": "EA", "unit": "RCH_A", "coicop18": coicop, "sinceTimePeriod": since, "format": "JSON", "lang": "en"})
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise MacroUnavailableError(f"Eurostat HICP {coicop}: {exc}") from exc
    finally:
        if owns:
            c.close()
    try:
        times = body["dimension"]["time"]["category"]["index"]
        values = body.get("value", {})
        out = {f"{t}-01": float(values[str(i)]) for t, i in times.items() if str(i) in values}
    except (KeyError, TypeError, ValueError) as exc:
        raise MacroUnavailableError(f"Eurostat HICP {coicop}: nečekaný formát ({exc})") from exc
    if not out:
        raise MacroUnavailableError(f"Eurostat HICP {coicop}: žádná data")
    return out


def ons_series(path: str, client: httpx.Client | None = None) -> dict[str, float]:
    """Monthly values if the series has them, otherwise quarterly."""
    c, owns = _client(client)
    try:
        resp = c.get(ONS_URL.format(path=path))
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise MacroUnavailableError(f"ONS {path}: {exc}") from exc
    finally:
        if owns:
            c.close()
    out: dict[str, float] = {}
    if body.get("months"):
        for r in body["months"]:
            m = re.fullmatch(r"(\d{4}) ([A-Z]{3})", r.get("date", ""))
            if m and r.get("value") not in ("", None):
                out[f"{m.group(1)}-{MONTHS[m.group(2)]:02d}-01"] = float(r["value"])
    elif body.get("quarters"):
        for r in body["quarters"]:
            m = re.fullmatch(r"(\d{4}) Q([1-4])", r.get("date", ""))
            if m and r.get("value") not in ("", None):
                out[f"{m.group(1)}-{(int(m.group(2)) - 1) * 3 + 1:02d}-01"] = float(r["value"])
    if not out:
        raise MacroUnavailableError(f"ONS {path}: žádná data")
    return out


def _mof_rows(text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 3 or not re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", row[0].strip()):
            continue
        y, m, d = (int(x) for x in row[0].strip().split("/"))
        try:
            out[dt.date(y, m, d).isoformat()] = float(row[2])
        except ValueError:
            continue  # "-" = not quoted that day
    return out


def mof_jgb_2y(start: str = "2018-01-01", client: httpx.Client | None = None) -> dict[str, float]:
    """2-year JGB yield, daily: the history file (to the end of last month) + this month."""
    c, owns = _client(client)
    try:
        hist = c.get(MOF_HIST)
        hist.raise_for_status()
        now = c.get(MOF_NOW)
        out = _mof_rows(hist.content.decode("utf-8", "replace"))
        if now.status_code == 200:
            out.update(_mof_rows(now.content.decode("utf-8", "replace")))
    except httpx.HTTPError as exc:
        raise MacroUnavailableError(f"MOF JGB: {exc}") from exc
    finally:
        if owns:
            c.close()
    out = {d: v for d, v in out.items() if d >= start}
    if len(out) < 20:
        raise MacroUnavailableError("MOF JGB: málo dat")
    return out


def eia_weekly(series: str = EIA_CRUDE, client: httpx.Client | None = None) -> dict[str, float]:
    import xlrd  # small, pure-Python reader of the old .xls format EIA publishes

    c, owns = _client(client)
    try:
        resp = c.get(EIA_XLS.format(series=series))
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise MacroUnavailableError(f"EIA {series}: {exc}") from exc
    finally:
        if owns:
            c.close()
    try:
        book = xlrd.open_workbook(file_contents=resp.content)
        sheet = book.sheet_by_name("Data 1")
        out = {}
        for i in range(3, sheet.nrows):
            d, v = sheet.cell_value(i, 0), sheet.cell_value(i, 1)
            if isinstance(d, float) and isinstance(v, float):
                out[xlrd.xldate_as_datetime(d, book.datemode).date().isoformat()] = v
    except Exception as exc:  # noqa: BLE001 — any format surprise means "unavailable", never a guess
        raise MacroUnavailableError(f"EIA {series}: nečekaný formát souboru ({exc})") from exc
    if len(out) < 60:
        raise MacroUnavailableError(f"EIA {series}: málo dat")
    return out
