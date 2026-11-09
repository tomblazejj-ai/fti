"""Market state of every instrument: OPEN, CLOSED, PRE_MARKET, POST_MARKET, TRADING_BREAK,
HOLIDAY or UNKNOWN — from the trading calendar of the market the instrument really trades on
(exchange hours in the exchange's own time zone, so summer/winter time is handled by tzdata),
public holidays computed by each exchange's published rules, and for crypto the exchange's
live system status.

Calendars (sessions in local exchange time):
  fx         spot FX (OTC): Sun 17:00 – Fri 17:00 New York; 25 Dec and 1 Jan closed
  metal      spot gold/silver (OTC, as quoted by brokers/CME): Sun 18:00 – Fri 17:00 New York,
             daily break 17:00–18:00; Good Friday, 25 Dec and 1 Jan closed
  us_cash    NYSE / Nasdaq cash session 09:30–16:00 ET, pre-market 04:00, post-market to 20:00;
             NYSE holidays and 13:00 early closes
  cme        CME Globex (index futures, index & energy CFDs): Sun 18:00 – Fri 17:00 ET, daily break
             17:00–18:00 ET; closed on NYSE full holidays (CME often trades a shortened session — the
             state then says HOLIDAY and the source's own data decide)
  us_bonds   US Treasury market (SIFMA): NYSE holidays + Columbus Day + Veterans Day
  xetra      Frankfurt 09:00–17:30 CET/CEST; Xetra holidays
  lse        London 08:00–16:30 UK time; LSE holidays (bank holidays)
  tse        Tokyo 09:00–11:30, break, 12:30–15:30 JST; Japanese public holidays (by law) + 31 Dec – 3 Jan
  crypto     24/7; Kraken SystemStatus (maintenance → TRADING_BREAK)
Where a rule could be wrong (e.g. a one-off closure), the source's own data still decide
freshness: an OPEN market without new quotes is reported as STALE, never as live.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
FRANKFURT = ZoneInfo("Europe/Berlin")
LONDON = ZoneInfo("Europe/London")
TOKYO = ZoneInfo("Asia/Tokyo")
PRAGUE = ZoneInfo("Europe/Prague")

OPEN, CLOSED, PRE, POST, BREAK, HOLIDAY, UNKNOWN = ("OPEN", "CLOSED", "PRE_MARKET", "POST_MARKET", "TRADING_BREAK",
                                                    "HOLIDAY", "UNKNOWN")
LABELS_CS = {OPEN: "trh otevřen", CLOSED: "trh zavřen", PRE: "předobchodní fáze", POST: "poobchodní fáze",
             BREAK: "přestávka v obchodování", HOLIDAY: "svátek — zavřeno", UNKNOWN: "stav nelze ověřit"}


# --- trading day of gold and forex ----------------------------------------------------------------
# The day runs from 17:00 New York to 17:00 New York and is named by its second date — the broker's daily candle
# (MT5 server time = New York + 7 h, so the candle starts at 00:00 server time). Five daily candles a week, no Sunday
# stub. A daily bar that starts at 00:00 UTC (ECB, FRED, NBP …) keeps its own UTC date under the same rule.

def trading_date(t: int | float | dt.datetime) -> dt.date:
    when = t if isinstance(t, dt.datetime) else dt.datetime.fromtimestamp(t, dt.timezone.utc)
    return (when.astimezone(NY).replace(tzinfo=None) + dt.timedelta(hours=7)).date()


_day_start: dict[int, int] = {}


def trading_day_start(t: int) -> int:
    """Unix start (17:00 New York the evening before) of the trading day that contains t. New York's offset is whole
    hours, so every UTC hour lies in one trading day — memoised per hour."""
    h = int(t) - int(t) % 3600
    s = _day_start.get(h)
    if s is None:
        d = trading_date(h)
        s = int((dt.datetime(d.year, d.month, d.day, tzinfo=NY) - dt.timedelta(hours=7)).timestamp())
        _day_start[h] = s
    return s


def trading_week_start(t: int) -> int:
    """Unix start of the trading week that contains t: Saturday 17:00 New York (Sunday 00:00 server time, the broker's
    weekly candle); its first trading day is Monday."""
    d = trading_date(trading_day_start(t))
    # Saturday 17:00 → Sunday 17:00 has the trading date Sunday and already belongs to the NEXT week's Monday
    monday = d + dt.timedelta(days=1) if d.weekday() == 6 else d - dt.timedelta(days=d.weekday())
    return int((dt.datetime(monday.year, monday.month, monday.day, tzinfo=NY) - dt.timedelta(days=1, hours=7)).timestamp())


# --- holiday rules -----------------------------------------------------------------------------
def easter(year: int) -> dt.date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = (h + m - 7 * n + 114) % 31 + 1
    return dt.date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(weekday - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> dt.date:
    d = dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: dt.date, saturday_to_friday: bool = True) -> dt.date | None:
    if d.weekday() == 6:
        return d + dt.timedelta(days=1)
    if d.weekday() == 5:
        return d - dt.timedelta(days=1) if saturday_to_friday else None
    return d


@lru_cache(maxsize=64)
def nyse_holidays(year: int) -> frozenset[dt.date]:
    days = [
        _observed(dt.date(year, 1, 1), saturday_to_friday=False),  # NYSE does not close Fri 31 Dec for a Saturday New Year
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        easter(year) - dt.timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed(dt.date(year, 6, 19)) if year >= 2022 else None,  # Juneteenth
        _observed(dt.date(year, 7, 4)),  # Independence Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(dt.date(year, 12, 25)),  # Christmas
    ]
    return frozenset(d for d in days if d)


@lru_cache(maxsize=64)
def nyse_early_closes(year: int) -> frozenset[dt.date]:
    """13:00 ET closes: the day before Independence Day, the day after Thanksgiving, Christmas Eve."""
    out = {_nth_weekday(year, 11, 3, 4) + dt.timedelta(days=1)}
    jul3, dec24 = dt.date(year, 7, 3), dt.date(year, 12, 24)
    hol = nyse_holidays(year)
    for d in (jul3, dec24):
        if d.weekday() < 5 and d not in hol:
            out.add(d)
    return frozenset(out)


@lru_cache(maxsize=64)
def bond_holidays(year: int) -> frozenset[dt.date]:
    extra = {_nth_weekday(year, 10, 0, 2), _observed(dt.date(year, 11, 11))}  # Columbus Day, Veterans Day
    return frozenset(set(nyse_holidays(year)) | {d for d in extra if d})


@lru_cache(maxsize=64)
def xetra_holidays(year: int) -> frozenset[dt.date]:
    e = easter(year)
    return frozenset({dt.date(year, 1, 1), e - dt.timedelta(days=2), e + dt.timedelta(days=1), dt.date(year, 5, 1),
                      dt.date(year, 12, 24), dt.date(year, 12, 25), dt.date(year, 12, 26), dt.date(year, 12, 31)})


@lru_cache(maxsize=64)
def lse_holidays(year: int) -> frozenset[dt.date]:
    e = easter(year)
    days = {e - dt.timedelta(days=2), e + dt.timedelta(days=1), _nth_weekday(year, 5, 0, 1), _last_weekday(year, 5, 0),
            _last_weekday(year, 8, 0)}
    ny = dt.date(year, 1, 1)
    days.add(ny if ny.weekday() < 5 else ny + dt.timedelta(days=7 - ny.weekday()))
    xmas, boxing = dt.date(year, 12, 25), dt.date(year, 12, 26)
    if xmas.weekday() == 5:
        days |= {dt.date(year, 12, 27), dt.date(year, 12, 28)}
    elif xmas.weekday() == 6:
        days |= {dt.date(year, 12, 26), dt.date(year, 12, 27)}
    elif boxing.weekday() == 5:
        days |= {xmas, dt.date(year, 12, 28)}
    else:
        days |= {xmas, boxing}
    return frozenset(days)


def _equinox(year: int, spring: bool) -> dt.date:
    """Japanese vernal/autumnal equinox day (formula used by the National Astronomical Observatory, 1980–2099)."""
    base = 20.8431 if spring else 23.2488
    day = int(base + 0.242194 * (year - 1980) - int((year - 1980) / 4))
    return dt.date(year, 3 if spring else 9, day)


@lru_cache(maxsize=64)
def tse_holidays(year: int) -> frozenset[dt.date]:
    base = {dt.date(year, 1, 1), dt.date(year, 1, 2), dt.date(year, 1, 3), _nth_weekday(year, 1, 0, 2),
            dt.date(year, 2, 11), dt.date(year, 2, 23), _equinox(year, True), dt.date(year, 4, 29), dt.date(year, 5, 3),
            dt.date(year, 5, 4), dt.date(year, 5, 5), _nth_weekday(year, 7, 0, 3), dt.date(year, 8, 11),
            _nth_weekday(year, 9, 0, 3), _equinox(year, False), _nth_weekday(year, 10, 0, 2), dt.date(year, 11, 3),
            dt.date(year, 11, 23), dt.date(year, 12, 31)}
    days = set(base)
    for d in sorted(base):  # a holiday on Sunday moves to the next working day
        if d.weekday() == 6:
            nxt = d + dt.timedelta(days=1)
            while nxt in days:
                nxt += dt.timedelta(days=1)
            days.add(nxt)
    for d in sorted(base):  # a weekday squeezed between two holidays is a holiday
        mid = d + dt.timedelta(days=1)
        if (mid + dt.timedelta(days=1)) in base and mid.weekday() < 5:
            days.add(mid)
    return frozenset(days)


# --- calendars ---------------------------------------------------------------------------------
def _result(state: str, reason: str, tz: ZoneInfo, next_change: dt.datetime | None = None, calendar: str = "") -> dict:
    return {"state": state, "label": LABELS_CS[state], "reason": reason, "calendar": calendar, "exchange_tz": str(tz),
            "next_change": next_change.isoformat() if next_change else None}


def _fx(now: dt.datetime) -> dict:
    t = now.astimezone(NY)
    d, wd, mins = t.date(), t.weekday(), t.hour * 60 + t.minute
    if (d.month, d.day) in ((12, 25), (1, 1)):
        return _result(HOLIDAY, "Vánoce / Nový rok — mezibankovní forex prakticky stojí.", NY, calendar="fx")
    if wd == 5 or (wd == 6 and mins < 17 * 60) or (wd == 4 and mins >= 17 * 60):
        return _result(CLOSED, "Víkend: forex obchoduje od neděle 17:00 do pátku 17:00 newyorského času.", NY, calendar="fx")
    return _result(OPEN, "Forex obchoduje nepřetržitě v pracovní dny.", NY, calendar="fx")


def _globex(now: dt.datetime, calendar: str, holidays) -> dict:
    t = now.astimezone(NY)
    d, wd, mins = t.date(), t.weekday(), t.hour * 60 + t.minute
    if d in holidays(d.year) or (calendar == "metal" and (d.month, d.day) in ((12, 25), (1, 1))):
        return _result(HOLIDAY, "Svátek — obchodování zavřené nebo zkrácené.", NY, calendar=calendar)
    if wd == 5 or (wd == 6 and mins < 18 * 60) or (wd == 4 and mins >= 17 * 60):
        return _result(CLOSED, "Víkend: obchoduje se od neděle 18:00 do pátku 17:00 newyorského času.", NY, calendar=calendar)
    if 17 * 60 <= mins < 18 * 60:
        return _result(BREAK, "Denní přestávka 17:00–18:00 newyorského času.", NY, calendar=calendar)
    return _result(OPEN, "Elektronické obchodování běží.", NY, calendar=calendar)


def _metal_holidays(year: int) -> frozenset[dt.date]:
    return frozenset({easter(year) - dt.timedelta(days=2)})


def _session(now: dt.datetime, tz: ZoneInfo, open_t: tuple[int, int], close_t: tuple[int, int], holidays, calendar: str,
             pre: tuple[int, int] | None = None, post: tuple[int, int] | None = None, lunch: tuple[tuple[int, int], tuple[int, int]] | None = None,
             early_close=None) -> dict:
    t = now.astimezone(tz)
    d, mins = t.date(), t.hour * 60 + t.minute
    if t.weekday() >= 5:
        return _result(CLOSED, "Víkend — burza je zavřená.", tz, calendar=calendar)
    if d in holidays(d.year):
        return _result(HOLIDAY, "Svátek podle kalendáře burzy.", tz, calendar=calendar)
    o, c = open_t[0] * 60 + open_t[1], close_t[0] * 60 + close_t[1]
    if early_close and d in early_close(d.year):
        c = 13 * 60
    if lunch and lunch[0][0] * 60 + lunch[0][1] <= mins < lunch[1][0] * 60 + lunch[1][1]:
        return _result(BREAK, "Polední přestávka burzy.", tz, calendar=calendar)
    if o <= mins < c:
        return _result(OPEN, "Hlavní obchodní seance.", tz, calendar=calendar)
    if pre and pre[0] * 60 + pre[1] <= mins < o:
        return _result(PRE, "Předobchodní fáze — hlavní seance ještě nezačala.", tz, calendar=calendar)
    if post and c <= mins < post[0] * 60 + post[1]:
        return _result(POST, "Poobchodní fáze — hlavní seance skončila.", tz, calendar=calendar)
    return _result(CLOSED, "Mimo obchodní hodiny burzy.", tz, calendar=calendar)


_crypto_status: dict = {"at": None, "status": None}


def _crypto(now: dt.datetime, status_fn=None) -> dict:
    status = _kraken_status(now, status_fn)
    if status is None:
        return _result(OPEN, "Kryptoměny se obchodují nepřetržitě (stav burzy se nepodařilo ověřit).", dt.timezone.utc,
                       calendar="crypto") | {"state": UNKNOWN, "label": LABELS_CS[UNKNOWN]}
    if status == "online":
        return _result(OPEN, "Burza Kraken je online, obchoduje se 24/7.", dt.timezone.utc, calendar="crypto")
    return _result(BREAK, f"Burza Kraken hlásí stav „{status}“ (údržba nebo omezený režim).", dt.timezone.utc, calendar="crypto")


def _kraken_status(now: dt.datetime, status_fn=None) -> str | None:
    if status_fn is not None:
        return status_fn()
    at = _crypto_status["at"]
    if at and (now - at).total_seconds() < 300:
        return _crypto_status["status"]
    try:
        import httpx

        r = httpx.get("https://api.kraken.com/0/public/SystemStatus", timeout=8.0)
        status = (r.json().get("result") or {}).get("status")
    except Exception:  # noqa: BLE001 — unknown, not open
        status = None
    _crypto_status.update({"at": now, "status": status})
    return status


CALENDAR_OF_ITYPE = {
    "spot_fx": "fx", "spot_metal": "metal", "cash_index": None, "cfd": "cme", "spot_commodity": "cme", "monthly_price": "monthly",
    "crypto_spot": "crypto", "token": "crypto", "perpetual_futures": "crypto", "calculated_index": "fx",
    "volatility_index": "us_cash", "yield": "us_bonds",
}
CASH_INDEX_CALENDAR = {"US500": "us_cash", "US100": "us_cash", "US30": "us_cash", "GER40": "xetra", "UK100": "lse", "JP225": "tse"}


def calendar_for(inst) -> str:
    if inst.itype == "cash_index":
        return CASH_INDEX_CALENDAR.get(inst.code, "us_cash")
    if inst.itype == "cfd" and inst.underlying in ("GER40",):
        return "cme"
    return CALENDAR_OF_ITYPE.get(inst.itype, "unknown")


def state(inst, now: dt.datetime | None = None, crypto_status_fn=None) -> dict:
    """Market state of one instrument now (dict with state, label, reason, calendar, exchange_tz)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    cal = calendar_for(inst)
    if cal == "fx":
        return _fx(now)
    if cal == "metal":
        return _globex(now, "metal", _metal_holidays)
    if cal == "cme":
        return _globex(now, "cme", nyse_holidays)
    if cal == "us_cash":
        return _session(now, NY, (9, 30), (16, 0), nyse_holidays, "us_cash", pre=(4, 0), post=(20, 0), early_close=nyse_early_closes)
    if cal == "us_bonds":
        return _session(now, NY, (8, 0), (17, 0), bond_holidays, "us_bonds")
    if cal == "xetra":
        return _session(now, FRANKFURT, (9, 0), (17, 30), xetra_holidays, "xetra")
    if cal == "lse":
        return _session(now, LONDON, (8, 0), (16, 30), lse_holidays, "lse")
    if cal == "tse":
        return _session(now, TOKYO, (9, 0), (15, 30), tse_holidays, "tse", lunch=((11, 30), (12, 30)))
    if cal == "crypto":
        return _crypto(now, crypto_status_fn)
    if cal == "monthly":
        return _result(UNKNOWN, "Měsíční průměrná cena — stav trhu se nesleduje.", dt.timezone.utc, calendar="monthly")
    return _result(UNKNOWN, "Pro tento instrument není kalendář obchodování.", dt.timezone.utc, calendar=cal)


def is_trading(st: dict) -> bool:
    return st.get("state") == OPEN


def prague(t: dt.datetime) -> str:
    """'pá 30. 10. 2026 22:58 SEČ' — the time shown to the user."""
    p = t.astimezone(PRAGUE)
    day = ["po", "út", "st", "čt", "pá", "so", "ne"][p.weekday()]
    zone = "SELČ" if p.dst() else "SEČ"
    return f"{day} {p.day}. {p.month}. {p.year} {p:%H:%M} {zone}"
