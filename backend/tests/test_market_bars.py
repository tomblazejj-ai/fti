"""ETAPA 1: every provider keeps its own bar history (market_bars). The same bar from two providers is kept twice,
updating one never touches the other, the one-time migration copies the legacy table without changing or deleting it,
a row without a recorded source becomes "unknown", gaps are reported and never filled, and the preferred provider
only changes the order of feeds — never the stored history."""

import datetime as dt

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.data import bars, market_hours, migrations, settings_store, store, universe
from app.db import Base
from app.models import MarketBar, PriceBar

UTC = dt.timezone.utc
T0 = int(dt.datetime(2026, 10, 27, 10, 0, tzinfo=UTC).timestamp())  # a Tuesday, FX open


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(store, "SessionLocal", Session)
    monkeypatch.setattr(store, "save_bars", REAL_SAVE)  # conftest stubs it out for all other tests
    return engine, Session


REAL_SAVE = store.save_bars


def _rows(Session, provider=None):
    with Session() as s:
        q = s.query(MarketBar).order_by(MarketBar.provider, MarketBar.t)
        if provider:
            q = q.filter(MarketBar.provider == provider)
        return [(r.provider, r.t, r.o, r.h, r.l, r.c, r.origin) for r in q]


def test_the_same_bar_from_two_providers_is_kept_twice(db):
    _, Session = db
    store.save_bars("EURUSD", "H1", [(T0, 1.10, 1.11, 1.09, 1.105, 50.0)], "kraken", meta={"feed_symbol": "EURUSD"})
    store.save_bars("EURUSD", "H1", [(T0, 1.1002, 1.1101, 1.0901, 1.1049, 900.0)], "mt5", meta={"feed_symbol": "EURUSD_ecn"})
    rows = _rows(Session)
    assert [(r[0], r[1]) for r in rows] == [("kraken", T0), ("mt5", T0)]
    assert store.bar_sources("EURUSD", "H1") == ["kraken", "mt5"]


def test_updating_one_provider_never_changes_the_other(db):
    _, Session = db
    store.save_bars("EURUSD", "H1", [(T0, 1.10, 1.11, 1.09, 1.105, 50.0)], "kraken")
    store.save_bars("EURUSD", "H1", [(T0, 1.1002, 1.1101, 1.0901, 1.1049, 900.0)], "mt5")
    kraken_before = _rows(Session, "kraken")
    for i in range(5):  # MT5 rewrites its forming bar again and again
        store.save_bars("EURUSD", "H1", [(T0, 1.2 + i, 1.3, 1.1, 1.25, 1.0)], "mt5")
    assert _rows(Session, "kraken") == kraken_before
    store.save_bars("EURUSD", "H1", [(T0, 9.0, 9.0, 9.0, 9.0, 1.0)], "kraken")  # and the other way round
    assert _rows(Session, "mt5")[0][2] == 1.2 + 4


def test_metadata_volume_meaning_and_closed_flag(db):
    _, Session = db
    now = dt.datetime.now(UTC)
    forming = int(now.timestamp()) - int(now.timestamp()) % 3600
    store.save_bars("XAUUSD", "H1", [(forming - 3600, 1, 1, 1, 1, 7.0), (forming, 2, 2, 2, 2, 8.0)], "dukascopy",
                    meta={"feed_symbol": "XAUUSD", "quality": "DELAYED", "origin": "Dukascopy Bank"})
    store.save_bars("XAUUSD", "H1", [(forming, 2, 2, 2, 2, 120.0)], "mt5", meta={"quality": "LIVE", "origin": "Purple Trading / PurpleTrading-Demo"})
    meta = {r["origin"]: r for r in store.load_bars("XAUUSD", "H1", "dukascopy", with_meta=True)}
    d = meta["Dukascopy Bank"]
    assert d["price_type"] == "bid" and d["delay_s"] == 3600 and d["volume_kind"] is None and d["v"] is None  # no fake volume
    assert [b["closed"] for b in store.load_bars("XAUUSD", "H1", "dukascopy", with_meta=True)] == [True, False]
    m = store.load_bars("XAUUSD", "H1", "mt5", with_meta=True)[0]
    assert m["volume_kind"] == "tick" and m["v"] == 120.0 and m["quality"] == "LIVE" and m["received_at"]


def test_backtest_reads_exactly_one_chosen_provider(db):
    store.save_bars("EURUSD", "H1", [(T0, 1.10, 1.11, 1.09, 1.105, 50.0)], "kraken")
    store.save_bars("EURUSD", "H1", [(T0, 1.1002, 1.1101, 1.0901, 1.1049, 900.0)], "mt5")
    assert store.load_bars("EURUSD", "H1", "mt5") == [(T0, 1.1002, 1.1101, 1.0901, 1.1049, 900.0)]
    assert store.load_bars("EURUSD", "H1", "kraken")[0][4] == 1.105


def test_gaps_are_reported_and_never_filled(db):
    hours = [T0 + i * 3600 for i in range(6)]
    store.save_bars("EURUSD", "H1", [(t, 1, 1, 1, 1, 1.0) for i, t in enumerate(hours) if i not in (2, 3)], "kraken")
    assert store.gaps("EURUSD", "kraken", "H1", hours[0], hours[-1]) == [(hours[2], 2)]
    assert len(store.load_bars("EURUSD", "H1", "kraken")) == 4  # nothing invented


def test_migration_copies_legacy_rows_once_without_touching_them(db):
    engine, Session = db
    with Session() as s:
        s.add_all([PriceBar(code="EURUSD", tf="H1", t=T0, o=1, h=2, l=0.5, c=1.5, v=10.0, source="kraken"),
                   PriceBar(code="XAUUSD", tf="D1", t=T0, o=4000, h=4010, l=3990, c=4005, v=5.0, source="mt5"),
                   PriceBar(code="US500", tf="D1", t=T0, o=6000, h=6000, l=6000, c=6000, v=None, source="")])
        s.commit()
    assert "2026-11-01_split_price_bars_by_provider" in migrations.apply_all(engine)
    assert migrations.apply_all(engine) == []  # recorded: runs exactly once
    rows = _rows(Session)
    assert {r[0] for r in rows} == {"kraken", "mt5", "unknown"}  # no source recorded → "unknown", never guessed
    with Session() as s:
        assert s.query(PriceBar).count() == 3  # the legacy table is left exactly as it was
        k = s.query(MarketBar).filter_by(provider="kraken").one()
        # the only (= newest) legacy bar of its series is not provably closed
        assert (k.price_type, k.volume_kind, k.feed_symbol, k.closed) == ("trade", "exchange", "EURUSD", False)
        assert s.query(MarketBar).filter_by(provider="mt5").one().volume_kind == "tick"
    with engine.begin() as c:  # a second run of the copy itself inserts nothing either
        migrations.split_price_bars_by_provider(c)
        assert c.execute(text("SELECT COUNT(*) FROM market_bars")).scalar() == 3


def test_preferred_provider_only_changes_the_order(monkeypatch):
    inst = universe.get("XAUUSD")
    cfg = {"preferred_feeds": {"XAUUSD": "dukascopy"}}
    monkeypatch.setattr(settings_store, "get", lambda path, default=None: cfg.get(path, default))
    assert [p for p, _ in bars._ordered_feeds(inst, "H1")][0] == "dukascopy"
    assert {p for p, _ in bars._ordered_feeds(inst, "H1")} == {p for p, _ in inst.feeds}  # the others stay as fallbacks


def test_bars_store_passes_provider_metadata(monkeypatch):
    seen = {}
    monkeypatch.setattr(store, "save_bars", lambda code, tf, b, source, session=None, meta=None: seen.update(code=code, source=source, meta=meta))
    bs = bars.BarSet("XAUUSD", "H1", [(T0, 1, 1, 1, 1, 1.0)], "mt5", "XAUUSD_ecn", "MT5", "broker_quote", False, False,
                     {"status": "LIVE"}, [], [], {"broker": "Purple Trading", "server": "PurpleTrading-Demo"}, {}, {})
    bars._store(bs)
    assert seen["source"] == "mt5" and seen["meta"] == {"feed_symbol": "XAUUSD_ecn", "quality": "LIVE",
                                                        "origin": "Purple Trading / PurpleTrading-Demo"}


def test_a_closed_bar_delivered_again_keeps_its_provenance(db):
    _, Session = db
    store.save_bars("BTCUSD", "H1", [(T0, 1, 2, 0.5, 1.5, 3.0)], "kraken", meta={"origin": "první příjem"})
    store.save_bars("BTCUSD", "H1", [(T0, 1, 2, 0.5, 1.5, 3.0)], "kraken", meta={"origin": "znovu"})
    assert _rows(Session, "kraken")[0][6] == "první příjem"  # same closed bar again: origin and receipt time stay
    store.save_bars("BTCUSD", "H1", [(T0, 1, 2.5, 0.5, 1.5, 3.0)], "kraken", meta={"origin": "oprava zdroje"})
    assert _rows(Session, "kraken")[0][3] == 2.5 and _rows(Session, "kraken")[0][6] == "oprava zdroje"  # a real revision is taken


def test_the_newest_legacy_bar_is_not_claimed_closed(db):
    engine, Session = db
    with Session() as s:
        s.add_all([PriceBar(code="BTCUSD", tf="H1", t=T0, o=1, h=1, l=1, c=1, v=1.0, source="kraken"),
                   PriceBar(code="BTCUSD", tf="H1", t=T0 + 3600, o=2, h=2, l=2, c=2, v=1.0, source="kraken")])
        s.commit()
    migrations.apply_all(engine)
    with Session() as s:
        assert [r.closed for r in s.query(MarketBar).order_by(MarketBar.t)] == [True, False]
