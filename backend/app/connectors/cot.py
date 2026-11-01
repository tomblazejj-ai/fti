"""CFTC Commitments of Traders — Legacy Futures Only report, COMEX Gold.

Free, no API key required, US government public-domain data, published
weekly (Friday, as of Tuesday's positions — genuinely lagged, not
real-time; the scoring engine must treat this as a slow signal, see
ARCHITECTURE.md section 5).

Dataset: publicreporting.cftc.gov (Socrata), Legacy Futures Only report,
dataset id 6dca-aqww — verified live against the real endpoint on
2026-09-27 (see docs/DECISIONS.md). An optional free Socrata app token
(https://publicreporting.cftc.gov/profile/app_tokens) raises the anonymous
rate limit; not required for our weekly polling cadence.
"""

from __future__ import annotations

import httpx

from app.config import settings

COT_DATASET_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
GOLD_MARKET_NAME = "GOLD - COMMODITY EXCHANGE INC."


class CotUnavailableError(RuntimeError):
    pass


def fetch_latest_two_gold_reports(client: httpx.Client | None = None) -> list[dict]:
    """Return the two most recent weekly Gold COT reports, oldest first.

    Each dict: {date, net_noncommercial_long} where net_noncommercial_long =
    noncomm_positions_long_all - noncomm_positions_short_all (large
    speculators' net positioning — the standard "smart money" positioning
    read). Raises CotUnavailableError on any failure — never fabricates data.
    """
    params = {
        "$limit": 2,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$where": f"market_and_exchange_names = '{GOLD_MARKET_NAME}'",
    }
    headers = {}
    if settings.cftc_app_token:
        headers["X-App-Token"] = settings.cftc_app_token

    owns_client = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        resp = client.get(COT_DATASET_URL, params=params, headers=headers)
        resp.raise_for_status()
        rows = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise CotUnavailableError(f"CFTC COT endpoint nedostupný nebo vrátil neplatná data: {exc}") from exc
    finally:
        if owns_client:
            client.close()

    if not isinstance(rows, list) or len(rows) < 2:
        raise CotUnavailableError("CFTC COT vrátil méně než 2 týdenní reporty — nelze spočítat trend.")

    out = []
    for row in reversed(rows):  # oldest first
        try:
            net = float(row["noncomm_positions_long_all"]) - float(row["noncomm_positions_short_all"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CotUnavailableError(f"CFTC COT řádek chybí očekávaná pole: {exc}") from exc
        out.append({"date": row["report_date_as_yyyy_mm_dd"][:10], "net_noncommercial_long": net})
    return out


HISTORY_FIELDS = (
    "report_date_as_yyyy_mm_dd,open_interest_all,noncomm_positions_long_all,noncomm_positions_short_all,"
    "comm_positions_long_all,comm_positions_short_all,nonrept_positions_long_all,nonrept_positions_short_all"
)


def fetch_gold_history(weeks: int = 160, client: httpx.Client | None = None) -> list[dict]:
    """Weekly Gold COT history, oldest first (~3 years by default).

    Each row: date, open_interest, spec_long, spec_short, spec_net (large
    speculators = "non-commercial"), comm_net (hedgers/producers =
    "commercial"), small_net (non-reportable). Raises CotUnavailableError.
    """
    params = {
        "$select": HISTORY_FIELDS,
        "$limit": weeks,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$where": f"market_and_exchange_names = '{GOLD_MARKET_NAME}'",
    }
    headers = {"X-App-Token": settings.cftc_app_token} if settings.cftc_app_token else {}
    owns_client = client is None
    client = client or httpx.Client(timeout=20.0)
    try:
        resp = client.get(COT_DATASET_URL, params=params, headers=headers)
        resp.raise_for_status()
        rows = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise CotUnavailableError(f"CFTC COT historie nedostupná: {exc}") from exc
    finally:
        if owns_client:
            client.close()

    if not isinstance(rows, list) or len(rows) < 30:
        raise CotUnavailableError(f"CFTC COT vrátil málo týdnů historie ({len(rows) if isinstance(rows, list) else 0}).")

    out = []
    for row in reversed(rows):
        try:
            f = {k: float(row[k]) for k in HISTORY_FIELDS.split(",")[1:]}
        except (KeyError, TypeError, ValueError) as exc:
            raise CotUnavailableError(f"CFTC COT řádek chybí očekávaná pole: {exc}") from exc
        out.append({
            "date": row["report_date_as_yyyy_mm_dd"][:10],
            "open_interest": f["open_interest_all"],
            "spec_long": f["noncomm_positions_long_all"],
            "spec_short": f["noncomm_positions_short_all"],
            "spec_net": f["noncomm_positions_long_all"] - f["noncomm_positions_short_all"],
            "comm_net": f["comm_positions_long_all"] - f["comm_positions_short_all"],
            "small_net": f["nonrept_positions_long_all"] - f["nonrept_positions_short_all"],
        })
    return out


# --- Disaggregated report: who exactly holds the positions (checked live 2026-10-02)
# Same CFTC Socrata portal, dataset 72hh-3qpy ("Disaggregated Futures Only").
# "Managed money" = hedge funds / CTAs — the precise "funds" number traders
# quote; the legacy "non-commercial" bucket mixes them with other big traders.
DISAGG_DATASET_URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
DISAGG_FIELDS = (
    "report_date_as_yyyy_mm_dd,open_interest_all,"
    "m_money_positions_long_all,m_money_positions_short_all,"
    "swap_positions_long_all,swap__positions_short_all,"
    "prod_merc_positions_long,prod_merc_positions_short,"
    "other_rept_positions_long,other_rept_positions_short,"
    "nonrept_positions_long_all,nonrept_positions_short_all"
)


CRUDE_MARKET_NAME = "WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE"  # the NYMEX WTI contract (renamed by CFTC in 2022)


def fetch_gold_disaggregated(weeks: int = 160, client: httpx.Client | None = None) -> list[dict]:
    """Weekly gold COT by trader group, oldest first. `spec_*` = managed money,
    so the same analysis code works on either report. Raises CotUnavailableError."""
    return fetch_disaggregated(GOLD_MARKET_NAME, weeks, client)


def fetch_crude_disaggregated(weeks: int = 160, client: httpx.Client | None = None) -> list[dict]:
    return fetch_disaggregated(CRUDE_MARKET_NAME, weeks, client)


def fetch_disaggregated(market: str, weeks: int = 160, client: httpx.Client | None = None) -> list[dict]:
    params = {
        "$select": DISAGG_FIELDS,
        "$limit": weeks,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$where": f"market_and_exchange_names = '{market}'",
    }
    headers = {"X-App-Token": settings.cftc_app_token} if settings.cftc_app_token else {}
    owns_client = client is None
    client = client or httpx.Client(timeout=20.0)
    try:
        resp = client.get(DISAGG_DATASET_URL, params=params, headers=headers)
        resp.raise_for_status()
        rows = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise CotUnavailableError(f"CFTC COT (podrobný report) nedostupný: {exc}") from exc
    finally:
        if owns_client:
            client.close()

    if not isinstance(rows, list) or len(rows) < 30:
        raise CotUnavailableError(f"CFTC podrobný COT vrátil málo týdnů ({len(rows) if isinstance(rows, list) else 0}).")

    out = []
    for row in reversed(rows):
        try:
            f = {k: float(row[k]) for k in DISAGG_FIELDS.split(",")[1:]}
        except (KeyError, TypeError, ValueError) as exc:
            raise CotUnavailableError(f"CFTC podrobný COT: chybí pole {exc}") from exc
        mm_long, mm_short = f["m_money_positions_long_all"], f["m_money_positions_short_all"]
        out.append({
            "date": row["report_date_as_yyyy_mm_dd"][:10],
            "open_interest": f["open_interest_all"],
            "spec_long": mm_long,
            "spec_short": mm_short,
            "spec_net": mm_long - mm_short,
            "swap_long": f["swap_positions_long_all"], "swap_short": f["swap__positions_short_all"],
            "prod_long": f["prod_merc_positions_long"], "prod_short": f["prod_merc_positions_short"],
            "other_long": f["other_rept_positions_long"], "other_short": f["other_rept_positions_short"],
            "small_long": f["nonrept_positions_long_all"], "small_short": f["nonrept_positions_short_all"],
            "swap_net": f["swap_positions_long_all"] - f["swap__positions_short_all"],
            "prod_net": f["prod_merc_positions_long"] - f["prod_merc_positions_short"],
            "other_net": f["other_rept_positions_long"] - f["other_rept_positions_short"],
            "small_net": f["nonrept_positions_long_all"] - f["nonrept_positions_short_all"],
            "comm_net": (f["prod_merc_positions_long"] - f["prod_merc_positions_short"])
                        + (f["swap_positions_long_all"] - f["swap__positions_short_all"]),
        })
    return out


# --- Traders in Financial Futures (TFF): who holds the US DOLLAR (checked live 2026-10-06)
# Dataset gpe5-46if, market "USD INDEX - ICE FUTURES U.S."; for currencies the "Leveraged
# Funds" (hedge funds) group of this report is the usual read.
TFF_DATASET_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
USD_INDEX_MARKET_NAME = "USD INDEX - ICE FUTURES U.S."
TFF_FIELDS = (
    "report_date_as_yyyy_mm_dd,open_interest_all,"
    "lev_money_positions_long,lev_money_positions_short,"
    "asset_mgr_positions_long,asset_mgr_positions_short,"
    "dealer_positions_long_all,dealer_positions_short_all,"
    "nonrept_positions_long_all,nonrept_positions_short_all"
)


# Currency futures in the same report (checked live 2026-10-31). A long yen future is a bet
# AGAINST USD/JPY — the market code turns it around.
TFF_MARKETS = {
    "USD": USD_INDEX_MARKET_NAME,
    "EUR": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
    "GBP": "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE",
    "JPY": "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE",
}


def fetch_usd_index_tff(weeks: int = 160, client: httpx.Client | None = None) -> list[dict]:
    """Weekly USD Index futures positions by trader group, oldest first. Raises CotUnavailableError."""
    return fetch_tff(USD_INDEX_MARKET_NAME, weeks, client)


def fetch_tff(market: str, weeks: int = 160, client: httpx.Client | None = None) -> list[dict]:
    params = {
        "$select": TFF_FIELDS,
        "$limit": weeks,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$where": f"market_and_exchange_names = '{market}'",
    }
    headers = {"X-App-Token": settings.cftc_app_token} if settings.cftc_app_token else {}
    owns_client = client is None
    client = client or httpx.Client(timeout=20.0)
    try:
        resp = client.get(TFF_DATASET_URL, params=params, headers=headers)
        resp.raise_for_status()
        rows = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise CotUnavailableError(f"CFTC COT dolaru (TFF) nedostupný: {exc}") from exc
    finally:
        if owns_client:
            client.close()
    if not isinstance(rows, list) or len(rows) < 30:
        raise CotUnavailableError(f"CFTC COT dolaru vrátil málo týdnů ({len(rows) if isinstance(rows, list) else 0}).")
    out = []
    for row in reversed(rows):
        try:
            f = {k: float(row[k]) for k in TFF_FIELDS.split(",")[1:]}
        except (KeyError, TypeError, ValueError) as exc:
            raise CotUnavailableError(f"CFTC COT dolaru: chybí pole {exc}") from exc
        out.append({
            "date": row["report_date_as_yyyy_mm_dd"][:10],
            "open_interest": f["open_interest_all"],
            "lev_long": f["lev_money_positions_long"], "lev_short": f["lev_money_positions_short"],
            "am_long": f["asset_mgr_positions_long"], "am_short": f["asset_mgr_positions_short"],
            "dealer_long": f["dealer_positions_long_all"], "dealer_short": f["dealer_positions_short_all"],
            "small_long": f["nonrept_positions_long_all"], "small_short": f["nonrept_positions_short_all"],
        })
    return out
