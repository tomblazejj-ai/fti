"""Long-term MT5 × Dukascopy cross-check (app/data/feedcheck.py): one finished day per step, identical
timestamps only, outages recorded, nothing compared twice, nothing without MT5."""

import datetime as dt

import pytest

from app.connectors import dukascopy
from app.data import feedcheck, mt5, store

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 4, 10, 0, tzinfo=UTC)  # Wednesday


@pytest.fixture()
def db(monkeypatch):
    saved = {}
    monkeypatch.setattr(store, "cache_get", lambda key, session=None: (saved.get(key), None))
    monkeypatch.setattr(store, "cache_put", lambda key, payload, source="", session=None: saved.__setitem__(key, payload))
    monkeypatch.setattr(mt5, "enabled", lambda: True)
    return saved


def _day(day, price, shift=0.0, drop=()):
    mins = sorted(dukascopy.expected_minutes("XAUUSD", day))
    return [(t, price + shift, price + shift + 0.5, price + shift - 0.5, price + shift + 0.1, 1.0)
            for i, t in enumerate(mins) if i not in drop]


def test_one_new_day_per_step_on_identical_timestamps(db):
    day = dt.date(2026, 11, 3)
    r = feedcheck.step(now=NOW, mt5_range=lambda c, tf, s, e: (_day(day, 4000.0), {}),
                       duka_day=lambda d: _day(d, 4000.0, shift=-0.05, drop=(5, 6)))
    assert r["day"] == "2026-11-03" and r["only_a"] == 2 and r["only_b"] == 0  # 2 Dukascopy minutes missing, not filled
    assert r["C"]["median"] == pytest.approx(0.05) and r["bias"] == pytest.approx(0.05)
    r2 = feedcheck.step(now=NOW, mt5_range=lambda c, tf, s, e: (_day(dt.date(2026, 11, 2), 4000.0), {}),
                        duka_day=lambda d: _day(d, 4000.0))
    assert r2["day"] == "2026-11-02"  # the next missing day, never the same one twice
    s = feedcheck.summary()
    assert s["days_compared"] == 2 and s["coverage_mt5_pct"] == 100.0 and s["coverage_dukascopy_pct"] < 100.0


def test_outages_are_recorded_and_the_day_stays_unchecked(db):
    def down(d):
        raise dukascopy.DukascopyUnavailable("503")

    assert feedcheck.step(now=NOW, mt5_range=lambda c, tf, s, e: ([], {}), duka_day=down) is None

    def closed(c, tf, s, e):
        raise mt5.Mt5Unavailable("Terminál MT5 neběží")

    assert feedcheck.step(now=NOW, mt5_range=closed, duka_day=lambda d: []) is None
    s = feedcheck.summary()
    assert s["days_compared"] == 0 and s["outages"] == {"MT5": 1, "Dukascopy": 1}


def test_without_mt5_nothing_runs(db, monkeypatch):
    monkeypatch.setattr(mt5, "enabled", lambda: False)
    assert feedcheck.step(now=NOW, mt5_range=lambda *a: ([], {}), duka_day=lambda d: []) is None
