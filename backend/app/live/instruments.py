"""The live instruments of the first phase and where their prices come from.

A broker's CFD is NOT the index: US500 / NAS100 here are CFD quotes (Purple: US500_ecn / US100_ecn, Deriv: the OTC
indices "US 500" / "US Tech 100" during the US session only). FTI codes follow app/data/universe.py (US500.CFD,
US100.CFD); the index itself (US500 = official S&P 500 close) stays a different instrument.

`tolerance` = the largest median difference of simultaneous mid prices at which a backup provider counts as
compatible (one spread or a little more, measured 9. 11. 2026 against Purple MT5: gold 0.24 USD, EUR/USD 0.4 pip,
US 500 0.9 pt, US Tech 100 4.2 pt).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Feed:
    provider: str
    symbol: str
    product: str  # what this provider's price IS — shown with every quote
    price_type: str = "bid"  # candles from the bid, like the broker's charts (brief 9. 11.: decided once, documented)
    sessions_utc: tuple[int, int] | None = None  # (from, to) hours UTC when the provider quotes at all; None = market hours
    role: str = "primary"  # primary / backup (takes over only after proven compatible) / check (measured, never shown)
    store_candles: bool = True  # False: the provider already has another kind of history in FTI (Kraken = trades)


@dataclass(frozen=True)
class LiveInstrument:
    code: str  # FTI code
    label: str  # what the user calls it
    name: str
    kind: str  # spot_metal / forex / cfd_index
    digits: int
    tolerance: float
    feeds: tuple[Feed, ...] = field(default_factory=tuple)
    max_spread: float = 0.0  # a quote with a wider spread is rejected as invalid (0 = no limit)


INSTRUMENTS: tuple[LiveInstrument, ...] = (
    LiveInstrument("XAUUSD", "XAUUSD", "Zlato / americký dolar", "spot_metal", 2, 1.0, max_spread=5.0, feeds=(
        Feed("deriv", "frxXAUUSD", "Deriv Gold/USD — kotace brokera Deriv (spot zlato, OTC)"),
    )),
    LiveInstrument("EURUSD", "EURUSD", "Euro / americký dolar", "forex", 5, 0.00015, max_spread=0.001, feeds=(
        Feed("deriv", "frxEURUSD", "Deriv EUR/USD — kotace brokera Deriv (spot forex, OTC)"),
        Feed("kraken", "EUR/USD", "Kraken EUR/USD — nabídky kryptoburzy Kraken (jiný trh než mezibankovní forex)",
             role="backup", store_candles=False),
    )),
    LiveInstrument("US500.CFD", "US500", "S&P 500 — CFD", "cfd_index", 1, 2.0, max_spread=5.0, feeds=(
        Feed("deriv", "OTC_SPC", "Deriv US 500 — OTC index brokera Deriv (CFD na S&P 500, ne index sám), jen 6–21 h UTC",
             sessions_utc=(6, 21)),
    )),
    LiveInstrument("US100.CFD", "NAS100", "Nasdaq-100 — CFD", "cfd_index", 1, 10.0, max_spread=20.0, feeds=(
        Feed("deriv", "OTC_NDX", "Deriv US Tech 100 — OTC index brokera Deriv (CFD na Nasdaq-100, ne index sám), jen 6–21 h UTC",
             sessions_utc=(6, 21)),
    )),
)
CTRADER_PRODUCT = {
    "XAUUSD": "Purple Trading cTrader — XAUUSD kotace vašeho brokera (spot zlato, CFD)",
    "EURUSD": "Purple Trading cTrader — EURUSD kotace vašeho brokera (spot forex)",
    "US500.CFD": "Purple Trading cTrader — US500 kotace vašeho brokera (CFD na S&P 500, ne index sám)",
    "US100.CFD": "Purple Trading cTrader — NAS100 kotace vašeho brokera (CFD na Nasdaq-100, ne index sám)",
}


def build(ctrader: bool = False) -> tuple[LiveInstrument, ...]:
    """With the user's cTrader keys the broker's own quotes are primary and Deriv becomes a backup (it stands in only
    after its prices were proven compatible); without them Deriv is primary. Candles of cTrader from the bid, like the
    broker's charts."""
    if not ctrader:
        return INSTRUMENTS
    out = []
    for inst in INSTRUMENTS:
        backups = tuple(replace(f, role="backup") if f.role == "primary" else f for f in inst.feeds)
        out.append(replace(inst, feeds=(Feed("ctrader", inst.code, CTRADER_PRODUCT[inst.code], price_type="bid"), *backups)))
    return tuple(out)


def current() -> tuple[LiveInstrument, ...]:
    from app.live import ctrader

    return build(ctrader.configured())


BY_CODE = {i.code: i for i in INSTRUMENTS}
# the timeframes the engine builds from ticks (seconds) — on the broker's grid (app/connectors/dukascopy.bucket)
TIMEFRAMES = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
LIVE_MAX_AGE = 15.0  # s: a quote older than this is not LIVE (Deriv sends ~1 a second, quiet indices up to 4 s apart)
DELAYED_MAX_AGE = 15 * 60.0  # s: older than this → HISTORICAL (only the last stored price)
JUMP_ATR = 5.0  # a quote moving more than 5 × ATR(M1) from the previous one is rejected (brief: validation)
JUMP_CONFIRM = 3  # … unless 3 quotes in a row stay at the new level: then the market really moved
BANNER = "TRH OTEVŘEN – DATA NEAKTUÁLNÍ"
COMPAT_MIN_PAIRS = 30  # simultaneous quote pairs needed before a backup may take over
COMPAT_PAIR_GAP = 2.0  # s: two quotes count as simultaneous within this gap
