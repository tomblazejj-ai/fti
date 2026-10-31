"""Registry of instruments the platform knows about.

`status="live"` means a scoring engine exists and is wired into ingestion.
Everything else is shown in the UI as "coming soon" with NO score — the
frontend must never render a number for an instrument that isn't live.
Adding an instrument = implement app/scoring/<code>.py, wire it into
ingestion, then flip its status here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InstrumentInfo:
    code: str
    name: str
    asset_class: str
    status: str  # "live" | "coming_soon"


INSTRUMENTS: list[InstrumentInfo] = [
    InstrumentInfo("XAUUSD", "Zlato", "Komodita", "live"),
    InstrumentInfo("EURUSD", "Euro / americký dolar", "Měny", "coming_soon"),
    InstrumentInfo("GBPUSD", "Britská libra / americký dolar", "Měny", "coming_soon"),
    InstrumentInfo("USDJPY", "Americký dolar / japonský jen", "Měny", "coming_soon"),
    InstrumentInfo("US100", "Nasdaq 100", "Index", "coming_soon"),
    InstrumentInfo("US500", "S&P 500", "Index", "coming_soon"),
    InstrumentInfo("WTI", "Ropa WTI", "Komodita", "coming_soon"),
    InstrumentInfo("BTCUSD", "Bitcoin", "Kryptoměna", "coming_soon"),
]

INSTRUMENTS_BY_CODE = {i.code: i for i in INSTRUMENTS}

PRIMARY_HORIZON = "1-10d"  # headline horizon for a swing-trading dashboard

# Which news factor tags feed which XAUUSD pillar (see scoring/xauusd.py).
XAUUSD_FACTOR_TO_PILLAR = {
    "fed_tone": "fed",
    "geopolitics": "geopolitics",
    "cb_gold_buying": "central_banks",
}
