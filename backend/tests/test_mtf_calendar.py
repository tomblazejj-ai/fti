import datetime as dt

import httpx

from app.connectors import calendar_ics, kraken
from app.connectors.calendar_ics import fetch_all as real_calendar_fetch_all
from app.connectors.kraken import Candle
from app.connectors.kraken import fetch_all as real_kraken_fetch_all

# conftest stubs both fetch_all functions for every test; these are the real ones.
from app.market import econ_calendar, mtf
from app.scoring.xauusd import MacroPoint

UTC = dt.timezone.utc


def _candles(n, start=2000.0, step=1.0, minutes=60, wiggle=3.0):
    t0 = dt.datetime(2026, 9, 1, tzinfo=UTC)
    out = []
    for i in range(n):
        base = start + step * i + (wiggle if i % 4 == 0 else -wiggle if i % 4 == 2 else 0)
        out.append(Candle(t0 + dt.timedelta(minutes=minutes * i), base, base + 2, base - 2, base))
    return out


def test_weekend_break_of_spot_gold_is_detected():
    assert kraken.spot_market_closed(dt.datetime(2026, 10, 3, 12, tzinfo=UTC))  # Saturday
    assert kraken.spot_market_closed(dt.datetime(2026, 10, 2, 21, 30, tzinfo=UTC))  # Fri 17:30 New York
    assert not kraken.spot_market_closed(dt.datetime(2026, 10, 4, 22, 30, tzinfo=UTC))  # Sun 18:30 New York
    assert not kraken.spot_market_closed(dt.datetime(2026, 10, 1, 12, tzinfo=UTC))  # Thursday


def test_parse_ohlc_drops_weekend_candles_and_reports_api_errors():
    sat = int(dt.datetime(2026, 10, 3, 12, tzinfo=UTC).timestamp())
    thu = int(dt.datetime(2026, 10, 1, 12, tzinfo=UTC).timestamp())
    payload = {"error": [], "result": {"PAXGUSD": [[thu, "1", "2", "0.5", "1.5", "1", "1", 1], [sat, "1", "2", "0.5", "1.5", "1", "1", 1]], "last": sat}}
    candles = kraken.parse_ohlc(payload, 60)
    assert [c.time.weekday() for c in candles] == [3]
    try:
        kraken.parse_ohlc({"error": ["EQuery:Unknown asset pair"]}, 60)
        assert False
    except kraken.KrakenUnavailableError:
        pass


def test_fetch_all_keeps_going_when_one_timeframe_fails():
    def handler(request):
        if request.url.params["interval"] == "15":
            return httpx.Response(500)
        return httpx.Response(200, json={"error": [], "result": {"PAXGUSD": []}})

    out, errors = real_kraken_fetch_all(client=httpx.Client(transport=httpx.MockTransport(handler)), sleep_fn=lambda s: None)
    assert "M15" not in out and set(out) == {"H1", "H4", "D1", "W1"}
    assert len(errors) == 1 and "M15" in errors[0]


def test_trend_per_timeframe_and_overall_blends():
    up, down = _candles(120, step=1.0), _candles(120, start=3000, step=-1.0)
    res = mtf.analyze_all({"M15": down, "H1": down, "H4": down, "D1": up, "W1": up})
    by_tf = {t["tf"]: t for t in res["timeframes"]}
    assert by_tf["D1"]["direction"] == "up" and by_tf["M15"]["direction"] == "down"
    assert res["intraday"]["direction"] == "down"
    assert res["swing"]["word"] in ("Nahoru", "Spíše nahoru")
    assert "korekc" in res["advice"]
    assert res["price_text"].endswith("$")


def test_too_few_candles_are_left_out_not_guessed():
    res = mtf.analyze_all({"H1": _candles(20)})
    assert res["timeframes"] == [] and res["overall"] is None and res["price"] is None


BEA_ICS = r"""BEGIN:VCALENDAR
X-WR-TIMEZONE:America/New_York
BEGIN:VEVENT
SUMMARY:GDP (Advance Estimate)\, 3rd Quarter 2026
DTSTART:20261029T123000Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:Personal Income and Outlays\, September 2026
DTSTART:20261029T123000Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:Services Supplied Through Affiliates\, 2024
DTSTART:20261006T140000Z
END:VEVENT
END:VCALENDAR
"""

BLS_ICS = r"""BEGIN:VCALENDAR
X-WR-TIMEZONE:US-Eastern
BEGIN:VEVENT
DTSTART;TZID=US-Eastern:20261015T083000
SUMMARY:Consumer Price Index for September 2026 with a long title that is
  folded
END:VEVENT
END:VCALENDAR
"""


def test_ics_parsing_handles_utc_local_time_and_folded_lines():
    bea = calendar_ics.parse_ics(BEA_ICS, "BEA")
    assert bea[0].summary == "GDP (Advance Estimate), 3rd Quarter 2026"
    assert bea[0].start == dt.datetime(2026, 10, 29, 12, 30, tzinfo=UTC)
    bls = calendar_ics.parse_ics(BLS_ICS, "BLS")
    assert bls[0].start == dt.datetime(2026, 10, 15, 12, 30, tzinfo=UTC)  # 8:30 New York (EDT)
    assert bls[0].summary.endswith("title that is folded")


def test_calendar_keeps_gold_relevant_releases_in_prague_time_with_previous_value():
    events = calendar_ics.parse_ics(BEA_ICS, "BEA") + calendar_ics.parse_ics(BLS_ICS, "BLS")
    macro = {"core_pce": MacroPoint(actual=2.91, previous=2.8, period="2026-08-01")}
    now = dt.datetime(2026, 10, 2, 9, tzinfo=UTC)
    cal = econ_calendar.build(events, ["2026-10-28"], macro, now, [])
    names = [e["name"] for e in cal["events"]]
    assert not any("Affiliates" in e["original"] for e in cal["events"])
    assert names[0] == "Inflace CPI (USA)" and cal["events"][0]["time"] == "14:30"
    pce = next(e for e in cal["events"] if "PCE" in e["name"])
    assert pce["previous"] == "jádrová inflace PCE 2,9 % r/r (za 8/2026)"
    assert pce["forecast"] is None
    assert cal["next_high"]["name"] == "Inflace CPI (USA)"
    assert any("FOMC" in n for n in names)
    assert any("Prognózy" in n for n in cal["notes"])


def test_only_bea_is_called_and_no_personal_data_is_sent():
    calls, user_agents = [], []

    def handler(request):
        calls.append(request.url.host)
        user_agents.append(request.headers["user-agent"])
        return httpx.Response(200, text=BEA_ICS)

    events, notes = real_calendar_fetch_all(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert calls == ["www.bea.gov"]
    assert "@" not in user_agents[0]
    assert len(events) == 3 and notes == []
