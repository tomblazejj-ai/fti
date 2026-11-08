"""Monitoring (ETAPA 2, task 2): a source is judged only by what it offers. H1 asked from a daily source is "unsupported"
(noted, never an error), data failing FTI's quality check are "rejected" (apart from outages), and the status tells
ok / delayed / stale / outage / unavailable — a daily source's yesterday value is not "late"."""

import datetime as dt

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.data import bars, health, quality, store
from app.db import Base

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 3, 15, 30, tzinfo=UTC)  # Tuesday afternoon, markets open
D = int(dt.datetime(2026, 11, 2, tzinfo=UTC).timestamp())
REAL_PUT, REAL_GET = store.cache_put, store.cache_get  # conftest switches the cache off for other tests


def _row(key):
    return {r["key"]: r for r in health.snapshot()}.get(key)


def test_h1_from_a_daily_source_is_unsupported_not_an_error(monkeypatch):
    called = []
    monkeypatch.setattr(bars, "_fetch", lambda p, s, tf, inst, now=None: called.append((p, tf)) or ([], {}))
    bs = bars.get_bars("US500", "H1", now=NOW)  # US500 (cash index) has only FRED, daily
    assert called == []  # FRED is not even asked for H1
    r = _row("feed:fred")
    assert r["error_count"] == 0 and r["outage_count"] == 0 and r["unsupported_tfs"] == ["H1"]
    assert r["status"] == "unknown"  # nothing was really tried, nothing failed
    assert "má jen denní data, ne H1" in bs.notes[0]  # the user still reads why there is no H1


def test_a_real_outage_is_counted_and_shown(monkeypatch):
    def fail(p, s, tf, inst, now=None):
        raise bars.FeedError("CBOE: HTTP 503")

    monkeypatch.setattr(bars, "_fetch", fail)
    bars.get_bars("VIX", "D1", now=NOW)
    r = _row("feed:cboe")
    assert r["outage_count"] == 1 and r["status"] == "unavailable"  # never delivered yet
    monkeypatch.setattr(bars, "_fetch", lambda p, s, tf, inst, now=None: ([(D, 20, 21, 19, 20.5, None)], {}))
    bars.clear_cache()
    bars.get_bars("VIX", "D1", now=NOW)
    assert _row("feed:cboe")["status"] == "ok"  # a daily value of yesterday is what a daily source delivers
    monkeypatch.setattr(bars, "_fetch", fail)
    bars.clear_cache()
    bars.get_bars("VIX", "D1", now=NOW)
    r = _row("feed:cboe")
    assert r["status"] == "outage" and r["outage_count"] == 2


def test_rejected_data_are_apart_from_outages(monkeypatch):
    def reject(p, s, tf, inst, now=None):
        raise bars.FeedRejected("Kraken EURCAD: 54% posledních svíček bez jediného obchodu — kotace nespolehlivá.")

    health.record("feed:kraken", "Kraken", ok=True, quality=quality.LIVE, expected=quality.LIVE)
    monkeypatch.setattr(bars, "_fetch", reject)
    bars.get_bars("EURCAD", "H1", now=NOW)
    r = _row("feed:kraken")
    assert r["rejected_count"] == 1 and r["outage_count"] == 0
    assert r["status"] == "ok"  # Kraken itself works (crypto); one pair's quotes failed the check


def test_status_follows_what_the_source_normally_delivers():
    health.record("feed:mt5", "MT5", ok=True, quality=quality.DELAYED, expected=quality.LIVE)
    health.record("feed:dukascopy", "Dukascopy", ok=True, quality=quality.DELAYED, expected=quality.DELAYED)
    health.record("feed:kraken", "Kraken", ok=True, quality=quality.STALE, expected=quality.LIVE)
    assert _row("feed:mt5")["status"] == "delayed"  # a live broker feed that is late
    assert _row("feed:dukascopy")["status"] == "ok"  # ~1 h late is how Dukascopy works
    assert _row("feed:kraken")["status"] == "stale"


def test_stored_counters_and_old_false_errors_after_a_restart(monkeypatch):
    monkeypatch.setattr(store, "cache_put", REAL_PUT)
    monkeypatch.setattr(store, "cache_get", REAL_GET)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        # a row from before the fix: its last "error" was only a timeframe FRED does not have
        s.add(models.SourceHealth(key="feed:fred", name="FRED", ok_count=468, error_count=1418,
                                  last_ok=dt.datetime(2026, 11, 1, 19, 46, 47, tzinfo=UTC),
                                  last_error_at=dt.datetime(2026, 11, 1, 19, 46, 48, tzinfo=UTC),
                                  last_error="FRED (St. Louis Fed) má jen denní data, ne H1."))
        s.commit()
        health.load(s)
    r = _row("feed:fred")
    assert r["status"] == "ok" and r["error_count"] == 1418  # history kept, status not fooled by it
    health.unsupported("feed:fred", "FRED", "H1")
    health.record("feed:cboe", "CBOE", ok=False, error="HTTP 503")
    with Session() as s:
        health.persist(s)
    health.reset()
    with Session() as s:
        health.load(s)
        assert s.get(models.SourceHealth, "feed:fred").last_error_at is not None  # the table keeps its record as it was
    assert _row("feed:fred")["unsupported_tfs"] == ["H1"] and _row("feed:cboe")["outage_count"] == 1
    assert _row("feed:fred")["counting_since"]
