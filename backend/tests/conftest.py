import os

os.environ["FTI_DISABLE_SCHEDULER"] = "1"  # tests must never trigger real network ingestion

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402,F401 — registers models on Base.metadata
from app.db import Base  # noqa: E402


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
    from app.connectors import fred, official_alt
    from app.data import bars, health, secrets, store

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
    monkeypatch.setattr(secrets, "get", lambda name: "")


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
