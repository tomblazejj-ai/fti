import os

os.environ["FTI_DISABLE_SCHEDULER"] = "1"  # tests must never trigger real network ingestion
os.environ["FTI_DISABLE_LIVE"] = "1"  # tests must never start the LIVE engine (it would stream into the real fti.db)

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402,F401 — registers models on Base.metadata
from app.db import Base  # noqa: E402


@pytest.fixture(autouse=True)
def _own_settings_file(monkeypatch, tmp_path):
    """Every test gets its own (empty → default) settings file — never the user's fti_settings.json (9. 11. 2026: with
    LIVE switched on there, a test started the live engine)."""
    from app.data import settings_store

    monkeypatch.setattr(settings_store, "SETTINGS_FILE", tmp_path / "fti_settings.json")


@pytest.fixture(autouse=True)
def _no_portals_or_translation(monkeypatch):
    """Tests never hit the news portals or load the translation model;
    tests that need them patch these explicitly."""
    from app.connectors import calendar_ics, cot, ecb, fred_calendar, kraken, nbp, portals, worldbank
    from app.market import service

    service._slow.clear()  # caches must not leak stubbed data between tests
    service._failed.clear()
    service.LAST_TRA["inputs"] = None
    from app.news import translate

    monkeypatch.setattr(portals, "fetch_all", lambda client=None: ([], []))
    monkeypatch.setattr(translate, "translate", lambda text: None)
    monkeypatch.setattr(translate, "unavailable_reason", lambda: None)
    monkeypatch.setattr(kraken, "fetch_all", lambda client=None, sleep_fn=None: ({}, []))
    monkeypatch.setattr(calendar_ics, "fetch_all", lambda client=None: ([], []))
    monkeypatch.setattr(fred_calendar, "fetch", lambda now, client=None, sleep_fn=None: ([], []))

    def no_disaggregated(weeks=160, client=None):
        raise cot.CotUnavailableError("v testech se nestahuje")

    monkeypatch.setattr(cot, "fetch_gold_disaggregated", no_disaggregated)

    def no_usd_cot(weeks=160, client=None):
        raise cot.CotUnavailableError("v testech se nestahuje")

    monkeypatch.setattr(cot, "fetch_usd_index_tff", no_usd_cot)

    def no_worldbank(now, client=None):
        raise worldbank.WorldBankUnavailableError("v testech se nestahuje")

    monkeypatch.setattr(worldbank, "fetch_gold_monthly", no_worldbank)

    def no_nbp(now, client=None, sleep_fn=None, cache_file=None):
        raise nbp.NbpUnavailableError("v testech se nestahuje")

    monkeypatch.setattr(nbp, "fetch_gold_usd", no_nbp)

    from app.connectors import ffcal, intl_macro

    def no_macro(*args, **kwargs):
        raise intl_macro.MacroUnavailableError("v testech se nestahuje")

    for name in ("ecb_series", "ons_series", "mof_jgb_2y", "eia_weekly", "eurostat_hicp"):
        monkeypatch.setattr(intl_macro, name, no_macro)

    def no_ff(now, client=None, cache_file=None):
        raise ffcal.CalendarFeedUnavailableError("v testech se nestahuje")

    monkeypatch.setattr(ffcal, "fetch_week", no_ff)

    def no_tff(market, weeks=160, client=None):
        raise cot.CotUnavailableError("v testech se nestahuje")

    monkeypatch.setattr(cot, "fetch_tff", no_tff)
    monkeypatch.setattr(cot, "fetch_crude_disaggregated", lambda weeks=160, client=None: no_tff(""))
    monkeypatch.setattr(service, "_fx_trend", lambda pair, warnings: (None, None))
    service._fx_cache.clear()
    service._titles_cs.clear()

    def no_ecb(now, client=None):
        raise ecb.EcbUnavailableError("v testech se nestahuje")

    monkeypatch.setattr(ecb, "fetch_history", no_ecb)

    # FTI data layer: no retries, no official fallbacks, no broker feeds, no stored bars in tests
    from app.connectors import fred, gdelt, official_alt
    from app.data import bars, health, secrets, store

    gdelt.reset()  # whose turn it is and any pause after a refusal start fresh in every test

    monkeypatch.setattr(fred, "RETRIES", 0)
    monkeypatch.setattr(fred, "_official_fallback", lambda series_id, history_days: None)

    def no_official(*args, **kwargs):
        raise official_alt.OfficialUnavailable("v testech se nestahuje")

    for name in ("bls_all", "treasury", "cboe_history", "vix_closes", "eia_daily", "oecd", "boc", "snb_policy_rate", "kraken_perp"):
        monkeypatch.setattr(official_alt, name, no_official)
    monkeypatch.setattr(store, "save_bars", lambda *a, **k: 0)
    monkeypatch.setattr(store, "cache_put", lambda *a, **k: None)
    monkeypatch.setattr(store, "cache_get", lambda *a, **k: (None, None))
    bars.clear_cache()
    health.reset()

    def no_kraken_bars(symbol, tf, inst):
        raise bars.FeedError("v testech se nestahuje")

    monkeypatch.setattr(bars, "_kraken", no_kraken_bars)
    monkeypatch.setattr(bars, "kraken_last_trade", lambda symbol: None)  # tests set trade times explicitly
    from app.data import indicative

    indicative.clear()
    monkeypatch.setattr(indicative, "_fetch", lambda code: None)  # no gold-api.com in tests unless a test sets it
    from app.connectors import dukascopy

    dukascopy.reset()

    def no_dukascopy(symbol, sec, days, now=None, **kw):
        raise dukascopy.DukascopyUnavailable("v testech se nestahuje")

    monkeypatch.setattr(dukascopy, "bars", no_dukascopy)
    from app.data import mt5 as mt5_feed

    monkeypatch.setattr(mt5_feed, "terminal_running", lambda path: False)  # no process lookups in tests
    monkeypatch.setattr(secrets, "get", lambda name: "")
    import httpx

    from app.connectors import tickbase

    from app.market import actuals

    actuals._pending.clear()  # FRED/ALFRED never reached from tests either
    monkeypatch.setattr(actuals, "_transport", httpx.MockTransport(lambda req: httpx.Response(503)))
    from app.market import intermarket_data

    monkeypatch.setattr(intermarket_data, "update_recent", lambda *a, **k: {})  # no Dukascopy downloads in tests
    monkeypatch.setattr(intermarket_data, "backfill_h1", lambda *a, **k: {})
    monkeypatch.setattr(intermarket_data, "run", lambda *a, **k: {})
    monkeypatch.setattr(intermarket_data, "fxcm_run", lambda *a, **k: {})  # nor FXCM's archive
    monkeypatch.setattr(dukascopy, "_transport", httpx.MockTransport(lambda req: httpx.Response(503)))
    import tempfile
    from pathlib import Path

    from app.connectors import fxcm

    monkeypatch.setattr(fxcm, "_transport", httpx.MockTransport(lambda req: httpx.Response(503)))
    monkeypatch.setattr(fxcm, "CACHE_DIR", Path(tempfile.mkdtemp(prefix="fti-fxcm-test-")))  # never the real cache
    tickbase.clear()  # TickBase never reached from tests: every request answers 503 unless a test sets a transport
    monkeypatch.setattr(tickbase, "_transport", httpx.MockTransport(
        lambda req: httpx.Response(503, json={"error": {"code": "upstream_unavailable", "status": 503}})))


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
