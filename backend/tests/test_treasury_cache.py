"""Data audit speed (ETAPA 2, task 3): the audit spent 92 % of its time on US Treasury, whose server answers each yearly
file in ~18 s — and the same file was downloaded again for every series in it. Now one download per curve and year,
finished years kept on disk, the same values; two audits at once are computed once."""

import datetime as dt
import os
import threading
import time

import pytest

from app.api import routes_fti
from app.connectors import official_alt

REAL_TREASURY = official_alt.treasury  # conftest replaces it for all other tests
THIS = dt.date.today().year
CSV = "Date,3 Mo,2 Yr,10 Yr\n" + "".join(f"{m:02d}/{d:02d}/{{y}},4.1{d % 10},3.5{d % 10},4.0{d % 10}\n"
                                         for m in range(1, 13) for d in (3, 10, 17, 24))


@pytest.fixture()
def treasury(monkeypatch, tmp_path):
    monkeypatch.setattr(official_alt, "treasury", REAL_TREASURY)
    monkeypatch.setattr(official_alt, "TREASURY_CACHE", tmp_path)
    monkeypatch.setattr(official_alt, "_cache", {})
    monkeypatch.setattr(official_alt, "_year_locks", {})
    seen = []

    class R:
        def __init__(self, text):
            self.text = text

    def fake_get(url, params=None, **kw):
        seen.append((params["type"], params["field_tdr_date_value"]))
        time.sleep(0.05)
        return R(CSV.format(y=params["field_tdr_date_value"]))

    monkeypatch.setattr(official_alt, "_get", fake_get)
    return seen


def test_one_download_per_curve_and_year_for_all_its_series(treasury):
    two = official_alt.treasury("DGS2", years=6)
    ten = official_alt.treasury("DGS10", years=6)
    assert sorted(treasury) == sorted(("daily_treasury_yield_curve", y) for y in range(THIS - 5, THIS + 1))  # 6, not 12
    assert two[f"{THIS}-01-03"] == pytest.approx(3.53) and ten[f"{THIS}-01-03"] == pytest.approx(4.03)  # values as in the file


def test_finished_years_come_from_disk_after_a_restart(treasury, monkeypatch):
    first = official_alt.treasury("DGS10", years=6)
    monkeypatch.setattr(official_alt, "_cache", {})  # a restart: nothing in memory
    treasury.clear()
    again = official_alt.treasury("DGS10", years=6)
    assert treasury == [("daily_treasury_yield_curve", THIS)]  # only the running year is asked for again
    assert again == first  # the same values


def test_a_finished_year_is_checked_again_after_a_month(treasury, monkeypatch):
    official_alt.treasury("DGS2", years=2)
    old = official_alt.TREASURY_CACHE / f"daily_treasury_yield_curve_{THIS - 1}.csv"
    t = time.time() - 31 * 86400
    os.utime(old, (t, t))
    monkeypatch.setattr(official_alt, "_cache", {})
    treasury.clear()
    official_alt.treasury("DGS2", years=2)
    assert ("daily_treasury_yield_curve", THIS - 1) in treasury


def test_callers_at_the_same_time_download_a_file_once(treasury):
    threads = [threading.Thread(target=official_alt.treasury, args=(s, 3)) for s in ("DGS2", "DGS10", "DGS3MO", "DGS2")]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(treasury) == len(set(treasury)) == 3


def test_two_audits_at_once_are_computed_once(monkeypatch):
    calls = []

    def row(inst):
        calls.append(inst.code)
        time.sleep(0.002)
        return {"code": inst.code}

    monkeypatch.setattr(routes_fti, "_audit_row", row)
    monkeypatch.setattr(routes_fti, "_audit_cache", {})
    results = []
    threads = [threading.Thread(target=lambda: results.append(routes_fti.data_audit(refresh=True))) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(calls) == len(routes_fti.universe.INSTRUMENTS)  # once, not twice
    assert results[0] is results[1]


def test_bars_served_again_from_memory_are_not_written_again(monkeypatch):
    from app.data import bars

    t0 = int(dt.datetime(2026, 10, 27, tzinfo=dt.timezone.utc).timestamp())
    writes = []
    monkeypatch.setattr(bars, "_store", lambda bs: writes.append(bs.tf))
    monkeypatch.setattr(bars, "_fetch", lambda p, s, tf, inst, now=None: ([(t0, 6000.0, 6000.0, 6000.0, 6000.0, None)], {}))
    bars.get_bars("US500", "D1")
    bars.get_bars("US500", "D1")
    assert writes == ["D1"]  # the second answer came from memory: already in the database
    bars.clear_cache()
    bars.get_bars("US500", "D1")
    assert writes == ["D1", "D1"]  # a new answer of the source is stored again
