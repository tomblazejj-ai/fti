"""Official actuals for Forex Factory events — the release-day value from ALFRED/FRED, checked at the publisher (BLS),
never a guess and never called verified without the publisher's numbers.

The release-day vintages below are the real ALFRED answers of 8. 11. 2026 (shortened); the earlier vintages and the
BLS answers are shaped like the real ones."""

import datetime as dt

import httpx
import pytest

from app.data import secrets
from app.market import actuals

NOW = dt.datetime(2026, 11, 8, 15, 0, tzinfo=dt.timezone.utc)
VINTAGES = {
    ("PAYEMS", "2026-11-06"): [("2026-08-01", "159068"), ("2026-09-01", "159128"), ("2026-10-01", "159293")],
    ("PAYEMS", "2026-10-02"): [("2026-08-01", "159070"), ("2026-09-01", "159099")],
    ("UNRATE", "2026-11-06"): [("2026-09-01", "4.2"), ("2026-10-01", "4.1")],
    ("UNRATE", "2026-10-02"): [("2026-08-01", "4.1"), ("2026-09-01", "4.2")],
    ("CES0500000003", "2026-11-06"): [("2026-08-01", "37.76"), ("2026-09-01", "37.86"), ("2026-10-01", "38")],
    ("CES0500000003", "2026-10-02"): [("2026-08-01", "37.80"), ("2026-09-01", "37.84")],
    ("ICSA", "2026-11-05"): [("2026-10-24", "195000"), ("2026-10-31", "189000")],
    ("ICSA", "2026-10-29"): [("2026-10-17", "195000"), ("2026-10-24", "194000")],
    ("JTSJOL", "2026-11-03"): [("2026-08-01", "7190"), ("2026-09-01", "7523")],
    ("JTSJOL", "2026-09-29"): [("2026-07-01", "7300"), ("2026-08-01", "7080")],
    ("BOPGSTB", "2026-11-04"): [("2026-08-01", "-105737.0"), ("2026-09-01", "-105047.0")],
    ("BOPGSTB", "2026-10-06"): [("2026-07-01", "-92800.0"), ("2026-08-01", "-105600.0")],
}
BLS = {"CES0000000001": {"M10": "159293", "M09": "159128"}, "LNS14000000": {"M10": "4.1", "M09": "4.2"},
       "CES0500000003": {"M10": "38.00", "M09": "37.86"}, "JTS000000000000000JOL": {"M09": "7523", "M08": "7190"}}


def ev(title, when, forecast=None, previous=None):
    return {"datetime": when, "currency": "USD", "title_en": title, "impact": 3, "forecast": forecast, "previous": previous,
            "source": "ForexFactory"}


@pytest.fixture()
def alfred(monkeypatch):
    calls = []
    bls = {k: dict(v) for k, v in BLS.items()}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "api.bls.gov":
            import json

            ids = json.loads(req.content)["seriesid"]
            calls.append(("BLS", tuple(ids)))
            return httpx.Response(200, json={"status": "REQUEST_SUCCEEDED", "Results": {"series": [
                {"seriesID": i, "data": [{"year": "2026", "period": p, "value": v} for p, v in bls.get(i, {}).items()]} for i in ids]}})
        sid = req.url.params["series_id"]
        if req.url.path.endswith("vintagedates"):
            calls.append((sid, "vintagedates"))
            days = sorted({d for s, d in VINTAGES if s == sid}, reverse=True)
            return httpx.Response(200, json={"vintage_dates": days})
        day = req.url.params["realtime_start"]
        calls.append((sid, day))
        assert req.url.params["realtime_end"] == day  # the value as known ON the release day
        rows = VINTAGES.get((sid, day), [])
        return httpx.Response(200, json={"observations": [{"date": d, "value": v, "realtime_start": day} for d, v in rows]})

    monkeypatch.setattr(actuals, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(secrets, "get", lambda name: "x" * 32 if name == "FRED_API_KEY" else "")
    actuals._pending.clear()
    actuals._bls_failed.clear()
    return {"calls": calls, "bls": bls}


def store_in(d):
    return {"get": d.get, "put": d.__setitem__}


LAST_WEEK = [("Non-Farm Employment Change", "2026-11-06T13:30:00+00:00", "65K", "29K"),
             ("Unemployment Rate", "2026-11-06T13:30:00+00:00", "4.2%", "4.2%"),
             ("Average Hourly Earnings m/m", "2026-11-06T13:30:00+00:00", "0.3%", "0.1%"),
             ("Unemployment Claims", "2026-11-05T13:30:00+00:00", "197K", "194K"),
             ("JOLTS Job Openings", "2026-11-03T15:00:00+00:00", "7.15M", "7.08M"),
             ("Trade Balance", "2026-11-04T13:30:00+00:00", "-107.9B", "-105.6B")]


def test_last_weeks_releases_get_official_actuals_in_ff_format(alfred):
    events = [ev(*x) for x in LAST_WEEK]
    db: dict = {}
    s = actuals.enrich(events, NOW, **store_in(db))
    got = {e["title_en"]: e["actual"] for e in events}
    assert got == {"Non-Farm Employment Change": "165K", "Unemployment Rate": "4.1%", "Average Hourly Earnings m/m": "0.4%",
                   "Unemployment Claims": "189K", "JOLTS Job Openings": "7.52M", "Trade Balance": "-105.0B"}
    nfp = events[0]
    assert nfp["previous_revised"] == "60K" and nfp["surprise"] == 100.0 and nfp["actual_period"] == "2026-10-01"
    assert "BLS" in nfp["actual_source"] and "2026-11-06" in nfp["actual_source"]
    assert "previous_revised" not in events[1]  # 4.2 % stayed 4.2 %
    assert s["filled"] == 6 and len(db) == 6


def test_record_keeps_publisher_period_unit_and_both_previous_values(alfred):
    db: dict = {}
    actuals.enrich([ev(*LAST_WEEK[0])], NOW, **store_in(db))
    rec = db["actual:Non-Farm Employment Change:2026-11-06T13:30"]
    assert rec["v"] == actuals.RECORD_VERSION and rec["period_label"] == "říjen 2026" and "tisíce" in rec["unit"]
    assert (rec["previous_ff"], rec["previous_published"], rec["previous_published_day"], rec["previous_revised"]) == \
        ("29K", "29K", "2026-10-02", "60K")
    assert rec["publisher_kind"] == "oficiální vládní zdroj" and "Bureau of Labor Statistics" in rec["publisher_name"]
    assert "ALFRED" in rec["via"] and "sekundární" in rec["secondary"] and rec["release_time_utc"] == "2026-11-06T13:30:00+00:00"


def test_bls_values_are_verified_at_the_publisher_in_one_request_others_are_not_called_verified(alfred):
    events = [ev(*x) for x in LAST_WEEK]
    db: dict = {}
    s = actuals.enrich(events, NOW, **store_in(db))
    bls_calls = [c for c in alfred["calls"] if c[0] == "BLS"]
    assert len(bls_calls) == 1  # one request for all BLS series (BLS allows 25 a day without a key)
    status = {e["title_en"]: e["actual_status"] for e in events}
    assert status["Non-Farm Employment Change"] == status["Unemployment Rate"] == status["JOLTS Job Openings"] == "ověřeno u vydavatele"
    assert status["Unemployment Claims"] == status["Trade Balance"] == "neověřeno u vydavatele"
    assert "403" in db["actual:Unemployment Claims:2026-11-05T13:30"]["verification"]["reason"]
    assert s["verified_at_publisher"] == 4
    alfred["calls"].clear()
    actuals.enrich([ev(*x) for x in LAST_WEEK], NOW, **store_in(db))
    assert not [c for c in alfred["calls"] if c[0] == "BLS"]  # verified records are not asked again


def test_a_disagreement_with_the_publisher_is_shown_not_hidden(alfred):
    alfred["bls"]["CES0000000001"]["M10"] = "159200"
    e = [ev(*LAST_WEEK[0])]
    actuals.enrich(e, NOW, **store_in({}))
    assert e[0]["actual_status"] == "ROZPOR s vydavatelem" and "ROZPOR" in e[0]["actual_source"]


def test_old_record_is_upgraded_with_its_history_kept(alfred):
    old = {"actual": "165K", "actual_value": 165.0, "period": "2026-10-01", "previous_revised": "60K", "series": "PAYEMS",
           "publisher": "BLS", "release_day": "2026-11-06", "source": "BLS přes ALFRED/FRED", "found_at": "2026-11-08T15:58:21+00:00"}
    db = {"actual:Non-Farm Employment Change:2026-11-06T13:30": dict(old)}
    s = actuals.enrich([ev(*LAST_WEEK[0])], NOW, **store_in(db))
    rec = db["actual:Non-Farm Employment Change:2026-11-06T13:30"]
    assert s["upgraded"] == 1 and rec["v"] == 2 and rec["history"] == [old] and rec["found_at"] == old["found_at"]
    assert rec["verification"]["status"] == "ověřeno u vydavatele"


def test_stored_actual_is_reused_without_a_request(alfred):
    db: dict = {}
    actuals.enrich([ev(*LAST_WEEK[1])], NOW, **store_in(db))
    alfred["calls"].clear()
    e2 = [ev(*LAST_WEEK[1])]
    s = actuals.enrich(e2, NOW, **store_in(db))
    assert e2[0]["actual"] == "4.1%" and s["from_cache"] == 1 and alfred["calls"] == []


def test_no_actual_before_fred_has_the_release_day(alfred):
    e = [ev("CPI m/m", "2026-11-10T13:30:00+00:00", "0.3%", "0.6%")]
    s = actuals.enrich(e, dt.datetime(2026, 11, 10, 14, 0, tzinfo=dt.timezone.utc), **store_in({}))
    assert "actual" not in e[0] and e[0]["actual_note"] == "Skutečnost: čeká na oficiální data." and s["pending"] == 1
    s = actuals.enrich(e, dt.datetime(2026, 11, 10, 14, 5, tzinfo=dt.timezone.utc), **store_in({}))
    assert s["requests"] == 0  # asked again only after PENDING_RETRY_S


def test_an_old_vintage_is_never_taken_for_the_new_release(alfred, monkeypatch):
    """FRED answers with the last value it knows; if that value started before the release day, it is LAST month's."""
    def handler(req):
        return httpx.Response(200, json={"observations": [{"date": "2026-09-01", "value": "4.2", "realtime_start": "2026-10-02"}]})

    monkeypatch.setattr(actuals, "_transport", httpx.MockTransport(handler))
    e = [ev("Unemployment Rate", "2026-11-06T13:30:00+00:00", "4.2%", "4.2%")]
    actuals.enrich(e, NOW, **store_in({}))
    assert "actual" not in e[0]


def test_not_yet_released_and_too_soon_are_not_asked(alfred):
    e = [ev("Core CPI m/m", "2026-11-10T13:30:00+00:00"), ev("Unemployment Rate", "2026-11-08T14:55:00+00:00")]
    actuals.enrich(e, NOW, **store_in({}))
    assert alfred["calls"] == [] and all("actual" not in x for x in e)


def test_private_surveys_say_why_there_is_no_actual(alfred):
    e = [ev("ISM Manufacturing PMI", "2026-11-02T15:00:00+00:00", "54.5", "54.5")]
    s = actuals.enrich(e, NOW, **store_in({}))
    assert "ISM" in e[0]["actual_note"] and s["no_official"] == 1 and alfred["calls"] == []


def test_ff_previous_of_the_next_release_checks_the_actual(alfred):
    e = [ev("Unemployment Claims", "2026-11-05T13:30:00+00:00", "197K", "194K"),
         ev("Unemployment Claims", "2026-11-12T13:30:00+00:00", "194K", "189K")]
    s = actuals.enrich(e, NOW, **store_in({}))
    assert e[0]["actual_check"] == {"ff_next_previous": "189K", "agrees": True}
    assert s["checked"] == [{"title": "Unemployment Claims", "fti": "189K", "ff_next_previous": "189K", "agrees": True}]


def test_forex_factory_stays_the_calendar(alfred):
    """Only FF's own USD events get an actual — FTI adds a value, never an event."""
    e = [{**ev("Unemployment Rate", "2026-11-06T13:30:00+00:00"), "source": "FRED"},
         {**ev("Unemployment Rate", "2026-11-06T13:30:00+00:00"), "currency": "EUR"}]
    actuals.enrich(e, NOW, **store_in({}))
    assert alfred["calls"] == [] and all("actual" not in x for x in e)


def test_calendar_keeps_released_events_with_an_actual_for_7_days():
    """User's decision 8. 11.: released events WITH an official actual stay 7 days; everything else as before
    (2 days back, 21 days ahead, same currencies)."""
    from app.market import service

    now = dt.datetime(2026, 11, 8, 17, 0, tzinfo=dt.timezone.utc)

    def e(when, title, actual=None, ccy="USD"):
        return {"datetime": when, "currency": ccy, "title_en": title, "title_cs": title, "impact": 3, "source": "ForexFactory",
                **({"actual": actual} if actual else {})}

    events = [e("2026-11-02T15:00:00+00:00", "ISM Manufacturing PMI"),  # 6 days, no actual -> hidden as before
              e("2026-11-03T15:00:00+00:00", "JOLTS Job Openings", "7.52M"),  # 5 days, actual -> shown
              e("2026-11-06T13:30:00+00:00", "Non-Farm Employment Change", "165K"),  # 2 d 3 h, actual -> shown
              e("2026-10-31T13:30:00+00:00", "Old with actual", "1.0%"),  # 8 days -> hidden
              e("2026-11-06T18:00:00+00:00", "FOMC Member Daly Speaks"),  # inside the 2 days -> shown as before
              e("2026-11-05T13:30:00+00:00", "CAD event", "1.0%", "CAD"),  # other currency -> hidden as before
              e("2026-11-10T13:30:00+00:00", "CPI m/m"),  # future -> shown as before
              e("2026-12-05T13:30:00+00:00", "Too far ahead")]  # beyond 21 days -> hidden as before
    shown = [x["title_en"] for x in service._calendar_payload(events, now)["events"]]
    assert shown == ["JOLTS Job Openings", "Non-Farm Employment Change", "FOMC Member Daly Speaks", "CPI m/m"]


def test_new_release_appears_in_the_calendar_once_fred_has_it(alfred):
    """CPI on 10. 11.: before FRED has the release day the calendar says it waits; after, it shows the actual."""
    from app.market import service

    VINTAGES[("CPIAUCSL", "2026-11-10")] = [("2026-09-01", "330.0"), ("2026-10-01", "331.0")]
    try:
        cpi = ev("CPI m/m", "2026-11-10T13:30:00+00:00", "0.3%", "0.6%")
        alfred_rows = VINTAGES.pop(("CPIAUCSL", "2026-11-10"))
        early = dt.datetime(2026, 11, 10, 13, 45, tzinfo=dt.timezone.utc)
        e1 = [dict(cpi)]
        actuals.enrich(e1, early, **store_in({}))
        shown = service._calendar_payload(e1, early)["events"][0]
        assert "actual" not in shown and shown["actual_note"] == "Skutečnost: čeká na oficiální data."
        VINTAGES[("CPIAUCSL", "2026-11-10")] = alfred_rows
        actuals._pending.clear()
        later = dt.datetime(2026, 11, 10, 15, 0, tzinfo=dt.timezone.utc)
        e2 = [dict(cpi)]
        actuals.enrich(e2, later, **store_in({}))
        shown = service._calendar_payload(e2, later)["events"][0]
        assert shown["actual"] == "0.3%" and shown["surprise"] == 0.0 and "2026-11-10" in shown["actual_source"]
        week_later = dt.datetime(2026, 11, 16, 12, 0, tzinfo=dt.timezone.utc)  # still listed 6 days later
        assert service._calendar_payload(e2, week_later)["events"][0]["actual"] == "0.3%"
    finally:
        VINTAGES.pop(("CPIAUCSL", "2026-11-10"), None)
