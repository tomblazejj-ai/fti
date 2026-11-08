"""Instrument registry — one truthful identity per instrument, used by every module.

Global rule (user's spec 2026-11-01, "PRAVDIVOST A IDENTITA VŠECH TRŽNÍCH INSTRUMENTŮ"):
  * Each instrument is the market or product it really is. A cash index is not its futures or a
    broker's CFD; spot WTI is not WTI futures; a token is not the metal; spot BTC is not the
    perpetual future. Different products are different instruments (US500 vs US500.CFD,
    XAUUSD vs PAXGUSD, BTCUSD vs BTCUSD.PERP).
  * Every instrument lists its feeds in priority order. A feed belongs to that instrument only;
    when all fail, the instrument is UNAVAILABLE — nothing from another instrument is substituted.
  * A feed that delivers a stand-in (a crypto exchange's EUR/USD book, a daily reference fixing)
    is labelled per feed (see FEED_IDENTITY in app/data/bars.py) with what it really is.

Feeds (provider, symbol):
  mt5       the user's broker terminal on this PC (official MetaTrader5 Python API), off until enabled
  oanda     OANDA v20 REST (broker quotes), off until the user adds a token
  kraken    Kraken spot exchange (crypto; FX pairs there are a crypto exchange's book → proxy)
  ecb       ECB euro reference rates (one fixing a day)
  fred      FRED daily series (official index closes)
  eia       EIA daily spot prices
  cboe      CBOE daily index history
  nbp       NBP daily gold price → USD/oz (reference price)
  treasury  US Treasury daily yield curves
"""

from __future__ import annotations

from dataclasses import dataclass, field

TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1")
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440, "W1": 10080, "MN1": 43200}

ITYPE_CS = {
    "spot_fx": "spotový měnový pár (OTC)",
    "spot_metal": "spotový drahý kov (OTC)",
    "cash_index": "akciový index (hotovostní, oficiální výpočet)",
    "cfd": "CFD brokera",
    "spot_commodity": "spotová cena komodity",
    "monthly_price": "měsíční průměrná cena",
    "crypto_spot": "kryptoměna (spot na burze)",
    "token": "tokenizované aktivum",
    "perpetual_futures": "perpetuální futures (bez expirace)",
    "calculated_index": "vypočtený index",
    "volatility_index": "index volatility",
    "yield": "výnos dluhopisu",
}

# what the numbers of one FEED are (app/data/bars.py feed_identity)
KIND_CS = {
    "broker_quote": "kotace brokera",
    "delayed_bank_quote": "kotace švýcarské banky Dukascopy (bid) se zpožděním ~1 h",
    "cfd": "CFD brokera",
    "exchange_quote": "kotace burzy",
    "crypto_fx_quote": "kotace měnového páru na kryptoburze (proxy)",
    "token": "tokenizované aktivum",
    "reference_daily": "denní referenční cena",
    "fixing_daily": "denní referenční kurz (fixing)",
    "index_daily": "oficiální denní hodnota indexu",
    "spot_daily": "denní spotová cena",
    "official_daily": "oficiální denní hodnota",
    "calculated": "vypočtená hodnota",
    "monthly_avg": "měsíční průměrná cena",
    "unavailable": "zdroj není připojen",
}


@dataclass(frozen=True)
class Instrument:
    code: str
    symbol: str  # display symbol
    name: str  # Czech name
    asset: str  # forex | index | commodity | crypto | rates | reference
    itype: str  # real product type, see ITYPE_CS
    unit: str  # what one quote means
    quote_ccy: str
    base_ccy: str | None
    digits: int
    pip: float  # one pip / point in price units (risk calculator)
    contract: float  # units per 1 lot, typical (risk calculator; the broker's spec wins when known)
    feeds: tuple[tuple[str, str], ...] = ()
    proxy: bool = False  # the instrument itself stands in for something else (token, calculated index)
    proxy_note: str = ""
    underlying: str | None = None  # code of what a CFD / token / future refers to
    venue: str = ""  # where the price is formed
    expiry: str | None = None  # futures expiry ("perpetual" for perpetual futures)
    currencies: tuple[str, ...] = ()  # calendar currencies that move it
    cot: str | None = None  # CFTC market (futures positioning — a different product, always labelled)
    cot_report: str | None = None  # tff | disaggregated
    fundamental: str | None = None  # model in app/market/markets.py: gold | fx | oil
    news: str = ""  # regex of headlines about it
    session: str = "fx"  # fx (Sun 17:00 – Fri 17:00 New York) | crypto (24/7) | index | daily
    notes: tuple[str, ...] = field(default_factory=tuple)


_GOLD_NEWS = r"\bgold\b|\bbullion\b|\bxau\b|\bzlat"
FX_NEWS = {
    "EUR": r"\beuro\b|\becb\b|\blagarde\b|\beurozone\b|\beuro area\b|\beur/usd\b|\beurusd\b|\beurozón",
    "GBP": r"\bpound\b|\bsterling\b|\bboe\b|\bbank of england\b|\bbailey\b|\bgbp\b|\blibr",
    "JPY": r"\byen\b|\bboj\b|\bbank of japan\b|\bueda\b|\bjpy\b|\bjaponsk",
    "CHF": r"\bfranc\b|\bsnb\b|\bswiss\b|\bchf\b|\bšvýcar",
    "CAD": r"\bloonie\b|\bbank of canada\b|\bboc\b|\bcanad|\bcad\b|\bkanad",
    "AUD": r"\baussie\b|\brba\b|\baustral|\baud\b",
    "NZD": r"\bkiwi\b|\brbnz\b|\bnew zealand\b|\bnzd\b|\bnový zéland",
}
COT_FX = {
    "EUR": "EURO FX - CHICAGO MERCANTILE EXCHANGE", "GBP": "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE",
    "JPY": "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE", "CHF": "SWISS FRANC - CHICAGO MERCANTILE EXCHANGE",
    "CAD": "CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE", "AUD": "AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
    "NZD": "NZ DOLLAR - CHICAGO MERCANTILE EXCHANGE",
}
KRAKEN_FX = {"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "EURJPY", "EURGBP", "AUDJPY", "EURAUD", "EURCAD", "EURCHF"}


def _fx(code: str, digits: int, fundamental: str | None = "fx") -> Instrument:
    base, quote = code[:3], code[3:]
    feeds: list[tuple[str, str]] = [("mt5", code), ("oanda", f"{base}_{quote}")]
    if code in KRAKEN_FX:
        feeds.append(("kraken", code))
    feeds.append(("ecb", f"{base}/{quote}"))
    foreign = base if base != "USD" else quote
    news = "|".join(x for x in (FX_NEWS.get(base), FX_NEWS.get(quote)) if x)
    return Instrument(code, f"{base}/{quote}", f"{base}/{quote}", "forex", "spot_fx", f"{quote} za 1 {base}", quote, base, digits,
                      0.01 if quote == "JPY" else 0.0001, 100_000, tuple(feeds), venue="mezibankovní forex (OTC)",
                      currencies=(base, quote), cot=COT_FX.get(foreign) if "USD" in (base, quote) else None,
                      cot_report="tff" if "USD" in (base, quote) and foreign in COT_FX else None, fundamental=fundamental, news=news)


def _cfd(code: str, underlying: str, name: str, quote: str, unit: str, digits: int, oanda: str, news: str = "",
         currencies: tuple[str, ...] = ("USD",), cot: str | None = None, cot_report: str | None = None, note: str = "") -> Instrument:
    return Instrument(code, f"{underlying} (CFD)", f"{name} — CFD brokera", "index" if "index" in note or underlying.startswith(("US", "GER", "UK", "JP")) and "OIL" not in underlying else "commodity",
                      "cfd", unit, quote, None, digits, 10 ** -digits if digits else 1, 1, (("mt5", underlying), ("oanda", oanda)),
                      underlying=underlying, venue="broker (OTC)", currencies=currencies, cot=cot, cot_report=cot_report, news=news,
                      session="index", notes=((note,) if note else ()) + (
                          "CFD je smlouva s brokerem: cena se odvozuje od futures (u indexů a ropy) nebo spotu, liší se o úpravu "
                          "fair value, spread a financování. Není to totéž co hotovostní index ani burzovní futures.",))


INSTRUMENTS: list[Instrument] = [
    # --- Gold & silver: spot metal (OTC) is separate from the token -----------------------------
    Instrument("XAUUSD", "XAU/USD", "Zlato (spot)", "commodity", "spot_metal", "USD za trojskou unci", "USD", "XAU", 2, 0.01, 100,
               feeds=(("mt5", "XAUUSD"), ("oanda", "XAU_USD"), ("dukascopy", "XAUUSD")),
               venue="spotový trh se zlatem (OTC, Londýn)", currencies=("USD",),
               cot="GOLD - COMMODITY EXCHANGE INC.", cot_report="disaggregated", fundamental="gold", news=_GOLD_NEWS,
               notes=("Spotové zlato se obchoduje mimo burzu (OTC): každá živá kotace je kotace konkrétního brokera nebo banky. "
                      "Bez brokera (MT5 / OANDA) bere FTI zpožděné kotace banky Dukascopy (ověřeno 1. 11. 2026 proti "
                      "Purple XAUUSD_ecn: medián rozdílu 0,10 USD, časy shodné na minutu), a když nedodává, orientační cenu "
                      "gold-api.com bez času kotace. Denní cena NBP se jako cena "
                      "XAUUSD nepoužívá: ověřeno 1. 11. 2026, že se zpožďuje o 1–2 obchodní dny (NBP 30. 10. = 4 051,59 USD, "
                      "skutečný páteční závěr ~3 880 USD). Slouží jen pro dlouhodobou sezónnost.",)),
    Instrument("PAXGUSD", "PAXG/USD", "PAX Gold (token)", "crypto", "token", "USD za 1 token (≈ 1 trojská unce)", "USD", "PAXG",
               2, 0.01, 1, feeds=(("kraken", "PAXGUSD"),), proxy=True, underlying="XAUUSD",
               proxy_note="PAXG je token společnosti Paxos krytý zlatem, obchoduje se 24/7 na kryptoburze. Není to XAU/USD: "
                          "o víkendu se hýbe, když je spot zavřený, a cena se od spotu odchyluje o desetiny procenta.",
               venue="Kraken", session="crypto", news=_GOLD_NEWS),
    Instrument("XAGUSD", "XAG/USD", "Stříbro (spot)", "commodity", "spot_metal", "USD za trojskou unci", "USD", "XAG", 3, 0.001,
               5000, feeds=(("mt5", "XAGUSD"), ("oanda", "XAG_USD")), venue="spotový trh se stříbrem (OTC)", currencies=("USD",),
               cot="SILVER - COMMODITY EXCHANGE INC.", cot_report="disaggregated", news=r"\bsilver\b|\bstříbr",
               notes=("Spotové stříbro nemá bezplatný zdroj bez registrace — data přinese až připojený broker (MT5 nebo OANDA).",)),
    # --- Forex (spot, OTC) -------------------------------------------------------------------------
    _fx("EURUSD", 5), _fx("GBPUSD", 5), _fx("USDJPY", 3), _fx("USDCHF", 5), _fx("USDCAD", 5), _fx("AUDUSD", 5), _fx("NZDUSD", 5),
    _fx("EURJPY", 3), _fx("GBPJPY", 3), _fx("EURGBP", 5), _fx("AUDJPY", 3), _fx("CADJPY", 3), _fx("EURAUD", 5), _fx("GBPCAD", 5),
    _fx("NZDJPY", 3), _fx("EURCHF", 5), _fx("EURCAD", 5),
    # --- Cash indices: official daily closes (FRED). Broker CFDs are separate instruments below ----
    Instrument("US500", "SPX", "S&P 500 (index)", "index", "cash_index", "body indexu", "USD", None, 2, 0.01, 1,
               feeds=(("fred", "SP500"),), venue="S&P Dow Jones Indices (oficiální denní závěr)", currencies=("USD",),
               cot="E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE", cot_report="tff", session="daily",
               news=r"\bs&p\b|\bs&p 500\b|\bwall street\b|\bstocks?\b|\bequit",
               notes=("Hotovostní index — jen denní závěry (FRED, licenční omezení: 10 let historie). "
                      "Intradenní graf má CFD brokera (US500.CFD) nebo futures ES, ne index sám.",)),
    Instrument("US100", "NDX", "Nasdaq-100 (index)", "index", "cash_index", "body indexu", "USD", None, 2, 0.01, 1,
               feeds=(("fred", "NASDAQ100"),), venue="Nasdaq (oficiální denní závěr)", currencies=("USD",),
               cot="NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE", cot_report="tff", session="daily",
               news=r"\bnasdaq\b|\btech stocks\b|\bnvidia\b|\bapple\b|\bmicrosoft\b"),
    Instrument("US30", "DJIA", "Dow Jones (index)", "index", "cash_index", "body indexu", "USD", None, 2, 0.01, 1,
               feeds=(("fred", "DJIA"),), venue="S&P Dow Jones Indices (oficiální denní závěr)", currencies=("USD",),
               cot="DJIA Consolidated - CHICAGO BOARD OF TRADE", cot_report="tff", session="daily", news=r"\bdow\b|\bdow jones\b|\bdjia\b"),
    Instrument("JP225", "N225", "Nikkei 225 (index)", "index", "cash_index", "body indexu", "JPY", None, 0, 1, 1,
               feeds=(("fred", "NIKKEI225"),), venue="Nikkei Inc. (oficiální denní závěr)", currencies=("JPY",),
               cot="NIKKEI STOCK AVERAGE YEN DENOM - CHICAGO MERCANTILE EXCHANGE", cot_report="tff", session="daily",
               news=r"\bnikkei\b|\btokyo stocks\b"),
    Instrument("GER40", "DAX", "DAX (index)", "index", "cash_index", "body indexu", "EUR", None, 2, 0.01, 1, feeds=(),
               venue="Deutsche Börse", currencies=("EUR",), session="daily", news=r"\bdax\b|\bgerman stocks\b|\bfrankfurt\b",
               notes=("Pro DAX není bezplatný oficiální zdroj bez registrace — index je nedostupný. CFD brokera je GER40.CFD.",)),
    Instrument("UK100", "UKX", "FTSE 100 (index)", "index", "cash_index", "body indexu", "GBP", None, 2, 0.01, 1, feeds=(),
               venue="FTSE Russell", currencies=("GBP",), session="daily", news=r"\bftse\b|\blondon stocks\b",
               notes=("Pro FTSE 100 není bezplatný oficiální zdroj bez registrace — index je nedostupný. CFD brokera je UK100.CFD.",)),
    _cfd("US500.CFD", "US500", "S&P 500", "USD", "body indexu", 2, "SPX500_USD", news=r"\bs&p\b|\bwall street\b",
         cot="E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE", cot_report="tff", note="index"),
    _cfd("US100.CFD", "US100", "Nasdaq-100", "USD", "body indexu", 2, "NAS100_USD", news=r"\bnasdaq\b",
         cot="NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE", cot_report="tff", note="index"),
    _cfd("US30.CFD", "US30", "Dow Jones", "USD", "body indexu", 2, "US30_USD", news=r"\bdow\b", note="index"),
    _cfd("GER40.CFD", "GER40", "DAX", "EUR", "body indexu", 2, "DE30_EUR", news=r"\bdax\b", currencies=("EUR",), note="index"),
    _cfd("UK100.CFD", "UK100", "FTSE 100", "GBP", "body indexu", 2, "UK100_GBP", news=r"\bftse\b", currencies=("GBP",), note="index"),
    _cfd("JP225.CFD", "JP225", "Nikkei 225", "JPY", "body indexu", 0, "JP225_USD", news=r"\bnikkei\b", currencies=("JPY",), note="index"),
    # --- Energy & copper: spot prices (EIA) / monthly averages; CFDs separate ----------------------
    Instrument("USOIL", "WTI", "Ropa WTI (spot Cushing)", "commodity", "spot_commodity", "USD za barel", "USD", None, 2, 0.01, 1000,
               feeds=(("eia", "RWTC"), ("fred", "DCOILWTICO")), venue="WTI Cushing, Oklahoma (EIA, denní spot)", currencies=("USD",),
               cot="CRUDE OIL, LIGHT SWEET-WTI - ICE FUTURES EUROPE", cot_report="disaggregated", fundamental="oil", session="daily",
               news=r"\boil\b|\bcrude\b|\bopec\b|\bwti\b|\bropa\b|\bropy\b",
               notes=("Spotová cena WTI z EIA, denně se zpožděním. Není to cena futures CL ani CFD USOIL (ty jsou samostatně).",)),
    Instrument("UKOIL", "Brent", "Ropa Brent (spot)", "commodity", "spot_commodity", "USD za barel", "USD", None, 2, 0.01, 1000,
               feeds=(("eia", "RBRTE"), ("fred", "DCOILBRENTEU")), venue="Europe Brent Spot FOB (EIA, denní spot)",
               currencies=("USD",), cot="BRENT LAST DAY - NEW YORK MERCANTILE EXCHANGE", cot_report="disaggregated", session="daily",
               news=r"\bbrent\b|\bopec\b|\boil\b"),
    Instrument("NATGAS", "NG", "Zemní plyn (spot Henry Hub)", "commodity", "spot_commodity", "USD za MMBtu", "USD", None, 3, 0.001,
               10000, feeds=(("eia", "RNGWHHD"), ("fred", "DHHNGSP")), venue="Henry Hub, Louisiana (EIA, denní spot)",
               currencies=("USD",), cot="NAT GAS NYME - NEW YORK MERCANTILE EXCHANGE", cot_report="disaggregated", session="daily",
               news=r"\bnatural gas\b|\blng\b|\bplyn"),
    Instrument("COPPER", "Copper", "Měď (měsíční průměr)", "commodity", "monthly_price", "USD za tunu", "USD", None, 0, 1, 1,
               feeds=(("fred", "PCOPPUSDM"),), venue="IMF / Světová banka (měsíční průměr přes FRED)", currencies=("USD",),
               cot="COPPER- #1 - COMMODITY EXCHANGE INC.", cot_report="disaggregated", session="daily", news=r"\bcopper\b|\bměď",
               notes=("Jen měsíční průměrné ceny — vhodné na dlouhodobý výhled, ne na technickou analýzu.",)),
    _cfd("USOIL.CFD", "USOIL", "Ropa WTI", "USD", "USD za barel", 2, "WTICO_USD", news=r"\bwti\b|\bcrude\b",
         cot="CRUDE OIL, LIGHT SWEET-WTI - ICE FUTURES EUROPE", cot_report="disaggregated"),
    _cfd("UKOIL.CFD", "UKOIL", "Ropa Brent", "USD", "USD za barel", 2, "BCO_USD", news=r"\bbrent\b"),
    _cfd("NATGAS.CFD", "NATGAS", "Zemní plyn", "USD", "USD za MMBtu", 3, "NATGAS_USD", news=r"\bnatural gas\b"),
    _cfd("COPPER.CFD", "COPPER", "Měď", "USD", "USD za libru", 4, "XCU_USD", news=r"\bcopper\b"),
    # --- Crypto: spot vs perpetual futures ---------------------------------------------------------
    Instrument("BTCUSD", "BTC/USD", "Bitcoin (spot)", "crypto", "crypto_spot", "USD za 1 BTC", "USD", "BTC", 1, 1, 1,
               feeds=(("kraken", "XBTUSD"),), venue="Kraken (spot)", session="crypto",
               cot="BITCOIN - CHICAGO MERCANTILE EXCHANGE", cot_report="tff", news=r"\bbitcoin\b|\bbtc\b|\bcrypto"),
    Instrument("ETHUSD", "ETH/USD", "Ethereum (spot)", "crypto", "crypto_spot", "USD za 1 ETH", "USD", "ETH", 2, 0.01, 1,
               feeds=(("kraken", "ETHUSD"),), venue="Kraken (spot)", session="crypto",
               cot="ETHER CASH SETTLED - CHICAGO MERCANTILE EXCHANGE", cot_report="tff", news=r"\bether(eum)?\b|\beth\b"),
    Instrument("SOLUSD", "SOL/USD", "Solana (spot)", "crypto", "crypto_spot", "USD za 1 SOL", "USD", "SOL", 2, 0.01, 1,
               feeds=(("kraken", "SOLUSD"),), venue="Kraken (spot)", session="crypto", news=r"\bsolana\b"),
    Instrument("BTCUSD.PERP", "PF_XBTUSD", "Bitcoin perpetual futures", "crypto", "perpetual_futures", "USD za 1 BTC", "USD", "BTC",
               1, 1, 1, feeds=(), underlying="BTCUSD", venue="Kraken Futures", expiry="perpetual", session="crypto",
               notes=("Perpetuální futures bez expirace. FTI z nich bere funding rate a open interest (data jedné burzy), "
                      "cenový graf se kreslí ze spotu BTCUSD.",)),
    Instrument("ETHUSD.PERP", "PF_ETHUSD", "Ethereum perpetual futures", "crypto", "perpetual_futures", "USD za 1 ETH", "USD", "ETH",
               2, 0.01, 1, feeds=(), underlying="ETHUSD", venue="Kraken Futures", expiry="perpetual", session="crypto",
               notes=("Funding rate a open interest z Kraken Futures (data jedné burzy).",)),
    # --- Reference series for intermarket analysis -------------------------------------------------
    Instrument("DXY", "DXY*", "Dolarový index (přepočet)", "reference", "calculated_index", "body indexu", "USD", None, 3, 0.001, 1,
               feeds=(), proxy=True, venue="výpočet FTI podle vzorce ICE",
               proxy_note="Vypočteno z kurzů EUR, JPY, GBP, CAD, SEK a CHF vzorcem ICE — ne kotace futures DXY na ICE.",
               currencies=("USD",), cot="USD INDEX - ICE FUTURES U.S.", cot_report="tff"),
    Instrument("VIX", "VIX", "Index volatility VIX", "reference", "volatility_index", "body indexu", "USD", None, 2, 0.01, 1,
               feeds=(("cboe", "VIX"), ("fred", "VIXCLS")), venue="CBOE (oficiální denní hodnoty)", currencies=("USD",), session="daily"),
    Instrument("US02Y", "US 2Y", "Výnos 2letých dluhopisů USA", "rates", "yield", "% p. a.", "USD", None, 2, 0.01, 1,
               feeds=(("treasury", "DGS2"), ("fred", "DGS2")), venue="US Treasury (denní par yield curve)", currencies=("USD",),
               session="daily"),
    Instrument("US10Y", "US 10Y", "Výnos 10letých dluhopisů USA", "rates", "yield", "% p. a.", "USD", None, 2, 0.01, 1,
               feeds=(("treasury", "DGS10"), ("fred", "DGS10")), venue="US Treasury (denní par yield curve)", currencies=("USD",),
               session="daily"),
    Instrument("US10YR", "US 10Y real", "Reálný výnos 10letých dluhopisů USA (TIPS)", "rates", "yield", "% p. a.", "USD", None, 2,
               0.01, 1, feeds=(("treasury", "DFII10"), ("fred", "DFII10")), venue="US Treasury (denní real yield curve)",
               currencies=("USD",), session="daily"),
]

BY_CODE: dict[str, Instrument] = {i.code: i for i in INSTRUMENTS}


def get(code: str) -> Instrument | None:
    return BY_CODE.get(code.upper())


def identity(inst: Instrument) -> dict:
    """What the UI shows about an instrument (without its live data status)."""
    return {
        "code": inst.code, "symbol": inst.symbol, "name": inst.name, "asset": inst.asset, "itype": inst.itype,
        "itype_cs": ITYPE_CS.get(inst.itype, inst.itype), "unit": inst.unit, "quote_ccy": inst.quote_ccy, "digits": inst.digits,
        "proxy": inst.proxy, "proxy_note": inst.proxy_note or None, "underlying": inst.underlying, "venue": inst.venue or None,
        "expiry": inst.expiry, "timezone": "časy ukládány v UTC, zobrazeny v čase Prahy (SEČ/SELČ)",
        "feeds": [p for p, _ in inst.feeds], "cot_market": inst.cot,
        "cot_note": "COT = týdenní pozice ve futures na americké burze (jiný produkt než tento instrument), zveřejněné s 3denním zpožděním."
        if inst.cot else None,
        "notes": list(inst.notes),
    }
