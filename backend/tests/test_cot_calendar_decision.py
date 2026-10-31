import datetime as dt

import httpx

from app.connectors import fred_calendar
from app.connectors.calendar_ics import IcsEvent
from app.connectors.cot import fetch_gold_disaggregated as real_disaggregated
from app.connectors.fred_calendar import fetch as real_fred_fetch
from app.market import decision, econ_calendar
from app.market.cot_analysis import analyze, schedule

UTC = dt.timezone.utc

# trimmed copy of the real FRED page structure (2026-10-02)
FRED_HTML = """
<tr class="odd"><td colspan="2"><span style="font-weight: bold;">Wednesday October 14, 2026</span>     </td></tr>
<tr><td nowrap style="width:5%; text-align:right">
          7:30 am      </td>
<td><a href="/release?rid=10">Consumer Price Index</a></td></tr>
<tr class="odd"><td colspan="2"><span style="font-weight: bold;">Friday November 06, 2026</span></td></tr>
<tr><td nowrap>   </td><td><a href="/release?rid=10">Consumer Price Index</a></td></tr>
"""


def test_fred_calendar_reads_dates_and_central_time():
    rows = fred_calendar.parse(FRED_HTML)
    assert rows[0][:2] == (10, "Consumer Price Index")
    assert rows[0][2] == dt.datetime(2026, 10, 14, 12, 30, tzinfo=UTC)  # 7:30 CDT = 14:30 Praha
    assert rows[1][2] == dt.datetime(2026, 11, 6, tzinfo=UTC)  # no time given → date only


def test_fred_calendar_fetch_respects_crawl_delay_and_sends_no_personal_data(monkeypatch):
    monkeypatch.setattr(fred_calendar, "_cache", {"at": None, "events": []})
    seen, sleeps = [], []

    def handler(request):
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, text=FRED_HTML if request.url.params["rid"] == "10" else "<html></html>")

    events, notes = real_fred_fetch(dt.datetime(2026, 10, 2, tzinfo=UTC), client=httpx.Client(transport=httpx.MockTransport(handler)),
                                    sleep_fn=sleeps.append)
    assert len(events) == 2 and events[0].summary.startswith("fred:cpi|")
    assert all(s >= 1.0 for s in sleeps) and len(sleeps) == len(fred_calendar.RELEASES) - 1
    assert not any("@" in ua for ua in seen) and not any("Mozilla" in ua for ua in seen)


def test_calendar_merges_fred_and_bea_and_tells_how_each_result_moves_gold():
    now = dt.datetime(2026, 10, 2, 9, tzinfo=UTC)
    events = [
        IcsEvent("fred:cpi|Consumer Price Index", dt.datetime(2026, 10, 14, 12, 30, tzinfo=UTC), "FRED"),
        IcsEvent("fred:gdp|Gross Domestic Product", dt.datetime(2026, 10, 29, 12, 30, tzinfo=UTC), "FRED"),
        IcsEvent("GDP (Advance Estimate), 3rd Quarter 2026", dt.datetime(2026, 10, 29, 12, 30, tzinfo=UTC), "BEA"),
        IcsEvent("fred:claims|Unemployment Insurance Weekly Claims Report", dt.datetime(2026, 10, 8, 12, 30, tzinfo=UTC), "FRED"),
    ]
    cal = econ_calendar.build(events, [], {}, now, [])
    names = [e["name"] for e in cal["events"]]
    assert names.count("HDP – první odhad (USA)") == 1 and "HDP (USA)" not in names  # BEA wins, no duplicate
    cpi = next(e for e in cal["events"] if e["key"] == "cpi")
    assert cpi["time"] == "14:30" and cpi["up_if"] == "inflace zpomalí"
    assert cal["instrument"] == "XAUUSD"


def _rows(n=60):
    out = []
    for i in range(n):
        d = dt.date(2025, 9, 2) + dt.timedelta(weeks=i)
        mm_long, mm_short = 150000 - i * 300, 10000 + i * 50
        out.append({"date": d.isoformat(), "open_interest": 400000, "spec_long": mm_long, "spec_short": mm_short,
                    "spec_net": mm_long - mm_short, "swap_net": -200000 + i * 100, "prod_net": -30000, "other_net": 90000,
                    "small_net": 30000, "comm_net": -230000 + i * 100})
    return out


def test_disaggregated_cot_names_groups_and_report_schedule():
    rows = _rows()
    res = analyze(rows, now=dt.datetime(2026, 10, 30, tzinfo=UTC), source="disaggregated")
    assert [g["label"] for g in res["groups"]][0] == "Hedgeové fondy (managed money)"
    assert res["groups"][0]["change_1w"] == -350
    assert res["long_short_ratio"] is not None and "managed money" in res["source_label"]
    sched = res["schedule"]
    last_tuesday = dt.date.fromisoformat(rows[-1]["date"])
    assert sched["next_data_date"] == (last_tuesday + dt.timedelta(days=7)).isoformat()


def test_cot_schedule_is_friday_1530_new_york_and_flags_a_late_report():
    s = schedule("2026-09-22", dt.datetime(2026, 10, 2, 9, tzinfo=UTC))
    assert s["published"] == "2026-09-25T19:30:00+00:00"  # Fri 15:30 EDT = 21:30 Praha
    assert s["next_release"] == "2026-10-02T19:30:00+00:00"
    assert not s["late"]
    assert schedule("2026-09-08", dt.datetime(2026, 10, 2, tzinfo=UTC))["late"]


def test_disaggregated_connector_maps_managed_money(monkeypatch):
    row = {"report_date_as_yyyy_mm_dd": "2026-09-22T00:00:00.000", "open_interest_all": "412800",
           "m_money_positions_long_all": "135699", "m_money_positions_short_all": "8310",
           "swap_positions_long_all": "14626", "swap__positions_short_all": "250752",
           "prod_merc_positions_long": "17719", "prod_merc_positions_short": "44496",
           "other_rept_positions_long": "118283", "other_rept_positions_short": "19819",
           "nonrept_positions_long_all": "52437", "nonrept_positions_short_all": "15387"}
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[row] * 40)))
    out = real_disaggregated(client=client)
    assert out[-1]["spec_net"] == 135699 - 8310
    assert out[-1]["swap_net"] == 14626 - 250752


def test_decision_lists_conditions_for_both_sides_and_marks_what_holds_now():
    technical = {"last_price": 4189.0, "sma200_pct": 2.0,
                 "resistances": [{"label": "Cenová zóna", "pct": 2.0, "price": 4273.0}],
                 "supports": [{"label": "Roční minimum", "pct": -1.6, "price": 4122.0}]}
    mtf = {"timeframes": [{"tf": "H4", "close": 4189.0, "swing_high": 4196.0, "swing_low": 4147.0}],
           "swing": {"word": "Dolů", "lean": "down"}}
    cot = {"change_4w": -17481}
    pillars = {"real_yields": {"points": -20.0, "weight": 20, "data_quality": "ok"},
               "usd": {"points": -8.0, "weight": 15, "data_quality": "ok"}}
    cal = {"events": [{"name": "Inflace CPI (USA)", "date": "2026-10-14", "time": "14:30", "importance": 3, "past": False,
                       "up_if": "inflace zpomalí", "down_if": "inflace bude vyšší"}]}
    d = decision.build({}, technical, mtf, cal, cot, pillars, dt.datetime(2026, 10, 2, tzinfo=UTC))
    assert d["bull"][0]["title"] == "Průraz nad 4 273 $"
    assert any(i["title"].startswith("Reálné výnosy: reálné výnosy rostou") and i["active"] for i in d["bear"])
    assert any(i["kind"] == "cot" and i["active"] for i in d["bear"])
    assert d["active_bear"] > d["active_bull"]
    assert d["events"][0]["up_if"] == "inflace zpomalí"
    assert "Inflace CPI (USA) (14. 10.)" in d["headline"]
