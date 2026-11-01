"""Fundamental score, momentum, calendar details, COT, DXY, seasonality."""

import datetime as dt
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.connectors import worldbank
from app.connectors.calendar_ics import IcsEvent
from app.connectors.kraken import Candle
from app.db import get_session
from app.ingestion import run_ingest
from app.main import app
from app.market import cot_analysis, dxy, econ_calendar, headline_risk, momentum, seasonality, tra
from app.models import TraScorePoint

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 6, 20, 0, tzinfo=UTC)


def monthly(start: str, values: list[float], skip: set[str] = frozenset()) -> dict[str, float]:
    y, m = int(start[:4]), int(start[5:7])
    out = {}
    for v in values:
        key = f"{y:04d}-{m:02d}-01"
        if key[:7] not in skip:
            out[key] = v
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


# --- score engine ----------------------------------------------------------------------

def test_yoy_bridges_the_missing_shutdown_month():
    # CPI index rising 0.25 % a month; October 2025 missing like in the real FRED series
    series = monthly("2024-01", [300 * 1.0025 ** i for i in range(34)], skip={"2025-10"})
    values = sorted(series.items())
    k = tra.AsOf(series, tra.FRED_SPECS["CPILFESL"]).known(dt.date(2027, 1, 1))
    assert values == k
    expected = (1.0025 ** 12 - 1) * 100
    assert tra._yoy(values) == pytest.approx(expected, rel=1e-6)  # Oct 2026 vs. bridged Oct 2025
    assert tra._yoy(values, 3) == pytest.approx(expected, rel=1e-6)  # "3 months back" is by date, not by position
    assert econ_calendar.history(series, econ_calendar.DETAILS["cpi"])[-1]["value"] == round(expected, 1)


def test_rates_read_expectations_from_the_two_year_yield():
    days = [(dt.date(2026, 8, 1) + dt.timedelta(days=i)).isoformat() for i in range(66)]
    k = {"DGS2": tra.AsOf({d: 4.8 for d in days}, tra.FRED_SPECS["DGS2"]),
         "DFF": tra.AsOf({d: 3.88 for d in days}, tra.FRED_SPECS["DFF"])}
    score, text, _ = tra.usd_rates(k, dt.date(2026, 10, 6))
    assert score == 2 and "ZVYŠOVÁNÍ" in text


def _inputs() -> tra.TraInputs:
    fred = {
        "GDPC1": {"2026-01-01": 100.0, "2026-04-01": 101.0},  # ~4 % annualized → strong
        "CPILFESL": monthly("2024-06", [300 * 1.0035 ** i for i in range(27)]),  # ~4.3 % y/y → high
        "PAYEMS": monthly("2026-03", [158000, 158250, 158500, 158750, 159000, 159250]),  # +250k a month
        "UNRATE": monthly("2026-03", [4.0] * 6),
    }
    return tra.TraInputs(fred=fred)


def test_compute_sums_categories_and_flips_the_dollar_macro_for_gold():
    res = tra.compute(_inputs(), NOW, live=True)
    xau, usd = res["xau"], res["usd"]
    by = {c["key"]: c for c in xau["components"]}
    assert by["gdp"]["usd_score"] > 0 and by["gdp"]["score"] == -by["gdp"]["usd_score"]
    assert by["inflation"]["score"] < 0  # high US inflation = stronger dollar = bad for XAU/USD
    assert xau["total"] == sum(c["score"] or 0 for c in xau["components"])
    assert usd["total"] == sum(c["score"] or 0 for c in usd["components"])
    assert "COT bias" in xau["missing"] and "Trend" in xau["missing"]  # never filled in
    assert xau["max"] == 25 and xau["word"] in ("Býčí", "Medvědí", "Neutrální")


def test_history_respects_publication_lag():
    inp = _inputs()
    # 3 July: the June CPI (published mid-July) is not known yet; live mode would already use it
    early = tra.compute(inp, dt.datetime(2026, 7, 3, 21, tzinfo=UTC))
    infl = next(c for c in early["usd"]["components"] if c["key"] == "inflation")
    assert infl["inputs"][0]["as_of"] == "2026-05-01"
    points = tra.backfill(inp, 14, NOW)
    assert points and all(p["t"].weekday() < 5 for p in points)


# --- momentum --------------------------------------------------------------------------

def _points(values: list[tuple[int, int]]) -> list[tuple[dt.datetime, int]]:
    return [(NOW - dt.timedelta(hours=h), v) for h, v in values]


def test_two_point_change_in_a_day_is_a_trade_idea():
    pts = _points([(24 * 20, 1), (30, 1), (2, -2)])
    m = momentum.analyze(pts, [], NOW)
    assert m["changes"]["24h"] == -3
    assert m["idea"]["direction"] == "down" and "−3" in m["idea"]["text"]


def test_model_situations_consolidation_and_divergence():
    prices = [(NOW - dt.timedelta(days=12 - i), 4000 + (i % 2) * 20) for i in range(12)]  # flat range
    m = momentum.analyze(_points([(24 * 10, -4), (24 * 3, 0), (1, 0)]), prices, NOW)
    assert any(s["key"] == "consolidation" for s in m["situations"])
    rising = [(NOW - dt.timedelta(days=12 - i), 4000 * (1 + 0.004 * i)) for i in range(12)]
    m2 = momentum.analyze(_points([(24 * 16, 4), (24 * 2, 1), (1, 1)]), rising, NOW)
    assert any(s["key"] == "divergence" for s in m2["situations"])


# --- news rules ------------------------------------------------------------------------

def test_fomc_statement_time_follows_both_daylight_saving_changes():
    cal = econ_calendar.build([], ["2026-10-28", "2026-12-09"], {}, dt.datetime(2026, 10, 27, tzinfo=UTC), [])
    times = {e["date"]: e["time"] for e in cal["events"]}
    assert times == {"2026-10-28": "19:00", "2026-12-09": "20:00"}  # US still on summer time on 28 October
    assert all(e["datetime"] for e in cal["events"])


def test_red_release_locks_entries_two_hours_before():
    start = dt.datetime(2026, 10, 14, 12, 30, tzinfo=UTC)
    ics = [IcsEvent("fred:cpi|Consumer Price Index", start, "FRED")]
    series = {"CPILFESL": monthly("2024-01", [300 + i for i in range(32)])}
    cal = econ_calendar.build(ics, [], {}, start - dt.timedelta(minutes=90), [], series)
    assert cal["lock"]["state"] == "lock" and cal["lock"]["minutes"] == 90
    detail = cal["events"][0]["detail"]
    assert detail["history"] and detail["series_url"].endswith("CPILFESL") and detail["why"]
    assert econ_calendar.news_lock(cal["events"], start + dt.timedelta(minutes=20))["state"] == "after"
    assert econ_calendar.news_lock(cal["events"], start - dt.timedelta(hours=5))["state"] == "clear"


def test_fed_rate_history_lists_each_change():
    series = {"2025-09-17": 4.5, "2025-09-18": 4.25, "2025-10-30": 4.0, "2025-10-31": 4.0, "2026-06-18": 4.25}
    hist = econ_calendar.history(series, econ_calendar.DETAILS["fomc"])
    assert [h["value"] for h in hist] == [4.5, 4.25, 4.0, 4.25]
    assert hist[-1]["period"] == "od 18. 6. 2026"


def test_headline_risk_needs_a_cluster_or_a_spike_for_high():
    def h(title: str, minutes: int, source: str) -> dict:
        return {"title": title, "title_en": title, "source": source, "url": f"https://x/{title}{source}",
                "published_at": (NOW - dt.timedelta(minutes=minutes)).isoformat(), "translated": False}

    one = headline_risk.build([h("Trump threatens new tariffs on EU", 30, "CNBC"), h("Gold edges higher", 10, "FXStreet")], [], {"open": True}, NOW)
    assert one["level"] == 1 and [i["topic"] for i in one["items"]] == ["Cla a obchodní válka"]
    cluster = headline_risk.build([h("Missile strikes on oil port", 20, "CNBC"), h("Missile strikes on oil port", 25, "Investing.com"),
                                   h("Sanctions on Russian banks widened", 40, "FXStreet"), h("Army declares martial law", 50, "CNBC")],
                                  [], {"open": True}, NOW)
    assert cluster["level"] == 2 and len(cluster["items"]) == 3  # duplicate headline counted once
    assert headline_risk.classify("Justice Dept staff told to rename AI under Trump order") is None
    friday = dt.datetime(2026, 10, 9, 18, 0, tzinfo=UTC)  # 14:00 New York, close at 17:00
    wk = headline_risk.build([], [], {"open": True, "weekly_close": True, "closes_at": "2026-10-09T21:00:00+00:00"}, friday)
    assert wk["weekend"] and wk["level"] == 1


# --- COT, DXY, seasonality -------------------------------------------------------------------

def _cot_rows(longs: list[float], short_total: float = 100.0) -> list[dict]:
    start = dt.date(2025, 1, 7)
    return [{"date": (start + dt.timedelta(weeks=i)).isoformat(), "lev_long": v, "lev_short": short_total - v,
             "spec_long": v, "spec_short": short_total - v} for i, v in enumerate(longs)]


def test_long_short_flags_sharp_change_extreme_and_divergence():
    rows = _cot_rows([50.0] * 40 + [48, 47, 46, 45, 30])  # −15 pp in one report, lowest in the window
    prices = [(r["date"], 100 + i * 0.5) for i, r in enumerate(rows)]  # price keeps rising
    v = cot_analysis.long_short_view(rows, "lev_long", "lev_short", prices, asset="usd")
    kinds = {f["kind"] for f in v["flags"]}
    assert kinds == {"sharp", "extreme_short", "divergence"}
    assert v["long_pct"] == 30.0 and v["short_pct"] == 70.0 and v["change_1w"] == -15.0
    assert "p.b." in next(f["text"] for f in v["flags"] if f["kind"] == "sharp")


def test_usd_cot_reads_the_leveraged_funds():
    rows = [{**r, "am_long": 10, "am_short": 5, "dealer_long": 3, "dealer_short": 9, "small_long": 4, "small_short": 2,
             "open_interest": 200} for r in _cot_rows([65.0] * 30)]
    out = cot_analysis.analyze_usd(rows, None, NOW)
    assert out["leveraged"]["long_pct"] == 65.0 and "silnější dolar" in out["texts"][0]
    assert [g["key"] for g in out["groups"]] == ["lev", "am", "dealer", "small"]


def _tech(sup_pct: float, res_pct: float, price: float) -> dict:
    return {"supports": [{"label": "Cenová zóna", "pct": sup_pct, "price": price * (1 + sup_pct / 100)}],
            "resistances": [{"label": "Cenová zóna", "pct": res_pct, "price": price * (1 + res_pct / 100)}]}


def test_mirror_gold_at_resistance_while_dollar_sits_on_support():
    m = dxy.mirror(_tech(-3.0, 0.4, 4200), _tech(-0.1, 0.9, 101.5), -0.5)
    assert m["state"] == "short" and m["gold_at"] == "resistance" and m["dxy_at"] == "support"
    weak = dxy.mirror(_tech(-3.0, 0.4, 4200), _tech(-0.1, 0.9, 101.5), 0.1)
    assert "odpojilo" in weak["text"]
    assert dxy.mirror(_tech(-3.0, 3.0, 4200), _tech(-0.1, 0.9, 101.5), -0.5)["state"] == "none"
    assert sum(w["weight"] for w in dxy.WEIGHTS) == pytest.approx(100.0)


def test_long_seasonality_has_5_10_15_year_lines_and_heatmap():
    prices = {}
    for y in range(2005, 2026):
        for m in range(1, 13):
            prices[f"{y}-{m:02d}"] = 1000 * (1.01 ** ((y - 2005) * 12 + m)) * (1.03 if m == 1 else 1.0)
    s = seasonality.analyze_long(prices, NOW)
    assert len(s["path"]["labels"]) == 13 and set(s["path"]["lines"]) == {"5", "10", "15"}
    assert len(s["heatmap"]) == 10 and s["heatmap"][-1]["year"] == 2025
    jan = s["months"][0]
    assert jan["avg10"] > s["months"][5]["avg10"]  # the January bump shows up
    assert s["score"] in (-2, -1, 0, 1, 2)


def _xlsx() -> bytes:
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    rows = ['<row r="1"><c r="A1" t="s"><v>0</v></c></row>', '<row r="5"><c r="B5" t="s"><v>1</v></c><c r="C5" t="s"><v>2</v></c></row>']
    r = 6
    for y in range(2010, 2021):
        for m in range(1, 13):
            rows.append(f'<row r="{r}"><c r="A{r}" t="inlineStr"><is><t>x</t></is></c></row>'.replace(
                f'<c r="A{r}" t="inlineStr"><is><t>x</t></is></c>', f'<c r="A{r}"><v>{y}M{m:02d}</v></c><c r="C{r}"><v>{1000 + r}</v></c>'))
            r += 1
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns} {rel}><sheets><sheet name="Monthly Prices" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", f'<sst {ns}><si><t>Updated on October 02, 2026</t></si><si><t>Crude oil</t></si><si><t>Gold</t></si></sst>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>{"".join(rows)}</sheetData></worksheet>')
    return buf.getvalue()


def test_world_bank_pink_sheet_parser():
    data = worldbank.parse_gold(_xlsx())
    assert data["updated"] == "2026-10-02"
    assert len(data["prices"]) == 132 and data["prices"]["2010-01"] == 1006.0


# --- stored history + API --------------------------------------------------------------------

def test_score_points_are_stored_on_change_and_served(db_session):
    pack = {"total": -6, "components": [{"key": "rates", "score": -2}]}
    now = dt.datetime.now(UTC) - dt.timedelta(hours=1)  # the API keeps every point of the last two days
    run_ingest.store_tra_points(db_session, {"xau": pack, "usd": {**pack, "total": 5}}, now)
    run_ingest.store_tra_points(db_session, {"xau": pack, "usd": {**pack, "total": 5}}, now + dt.timedelta(minutes=5))  # same → no new row
    run_ingest.store_tra_points(db_session, {"xau": {**pack, "total": -4}, "usd": {**pack, "total": 5}}, now + dt.timedelta(minutes=10))
    assert db_session.query(TraScorePoint).filter_by(instrument="XAUUSD").count() == 2
    assert db_session.query(TraScorePoint).filter_by(instrument="USD").count() == 1

    app.dependency_overrides[get_session] = lambda: db_session
    try:
        client = TestClient(app)
        body = client.get("/api/instruments/XAUUSD/tra-history?days=3650").json()
        assert [p["total"] for p in body["points"]] == [-6, -4]
        assert client.get("/api/instruments/DXY/tra-history").status_code == 200
        assert client.get("/api/instruments/EURUSD/tra-history").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_backfill_runs_once_then_only_fills_gaps(db_session):
    d1 = [Candle(NOW - dt.timedelta(days=300 - i), 4000, 4010, 3990, 4000 + i) for i in range(300)]
    inp = tra.TraInputs(gold_d1=d1, dxy_d1=d1)
    first = run_ingest.backfill_tra(db_session, inp, NOW)
    assert first > 200
    assert run_ingest.backfill_tra(db_session, inp, NOW + dt.timedelta(hours=1)) == 0
    later = NOW + dt.timedelta(days=5)
    assert 1 <= run_ingest.backfill_tra(db_session, inp, later) <= 5
