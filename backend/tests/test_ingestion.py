import datetime as dt

from app.connectors import nbp, cot, fred, gdelt, rss_news
from app.ingestion import run_ingest
from app.models import MacroObservation, NewsItem, ScoreHistoryEntry, ScoreSnapshot
from app.scoring.xauusd import SUPPORTED_HORIZONS

NOW = dt.datetime.now(dt.timezone.utc)


def _fake_fred_observations(series_id, client=None, sleep_fn=None, **kwargs):
    # Enough history for every transform (daily 90-obs lookback, monthly
    # YoY, quarterly growth). Pillar directions are covered in
    # test_scoring.py — this test is about wiring/traceability.
    daily = ("DFII10", "DTWEXBGS", "DFEDTARU", "NASDAQQGLDI", "GVZCLS", "DGS10", "DEXUSEU", "SP500", "DCOILWTICO", "VIXCLS", "CBBTCUSD")
    if series_id in daily:
        start = dt.date(2025, 8, 1)
        wobble = (sum(map(ord, series_id)) % 7) + 1  # different, deterministic shape per series
        return [
            {"date": (start + dt.timedelta(days=i)).isoformat(), "value": 100.0 + i * 0.05 + ((i * wobble) % 5) * 0.3}
            for i in range(400)
        ]
    if series_id == "GDPC1":
        return [{"date": f"2025-{m:02d}-01", "value": 100.0 + i} for i, m in enumerate((1, 4, 7, 10))]
    months = []
    for i in range(24):
        total = 2024 * 12 + 9 + i
        months.append({"date": f"{total // 12:04d}-{total % 12 + 1:02d}-01", "value": 300.0 + i})
    return months


def _fake_cot_reports(client=None):
    return [
        {"date": "2026-09-15", "net_noncommercial_long": 200000.0},
        {"date": "2026-09-22", "net_noncommercial_long": 210000.0},
    ]


def _fake_rss_feeds(client=None):
    return [
        rss_news.RawNewsEntry(
            source="Fed",
            title="Fed cuts rates by 25bps, signals dovish path",
            url="https://federalreserve.gov/a",
            published_at=NOW,
            snippet="The Fed cut rates.",
        )
    ]


def _fake_gdelt_queries(client=None, sleep_fn=None):
    # Same real-world event as the RSS entry above, different headline/source —
    # must be recognized as a duplicate, not double-counted.
    return (
        [
            gdelt.RawNewsEntry(
                source="gdelt:reuters.com",
                title="Federal Reserve cuts interest rates 25bps in dovish move",
                url="https://reuters.com/b",
                published_at=NOW + dt.timedelta(hours=1),
                snippet="Federal Reserve cuts interest rates 25bps in dovish move",
            )
        ],
        [],
    )


def _patch_all_connectors(monkeypatch):
    monkeypatch.setattr(fred.secrets, "get", lambda name: "dummy-key" if name == "FRED_API_KEY" else "")
    monkeypatch.setattr(fred, "fetch_observations", _fake_fred_observations)
    monkeypatch.setattr(cot, "fetch_latest_two_gold_reports", _fake_cot_reports)
    monkeypatch.setattr(cot, "fetch_gold_history", _fake_cot_history)
    monkeypatch.setattr(rss_news, "fetch_all_feeds", _fake_rss_feeds)
    monkeypatch.setattr(gdelt, "fetch_all_queries", _fake_gdelt_queries)
    monkeypatch.setattr(nbp, "fetch_gold_usd", _fake_gold_daily)


def _fake_gold_daily(now, client=None, sleep_fn=None, cache_file=None):
    """XAUUSD daily reference prices (the NBP feed of XAUUSD) — 500 business days, rising with waves."""
    import math

    out, day, i = {}, dt.date(2024, 11, 1), 0
    while len(out) < 500:
        if day.weekday() < 5:
            out[day.isoformat()] = round(2500 + i * 2.5 + 40 * math.sin(i / 9), 2)
            i += 1
        day += dt.timedelta(days=1)
    return out


def _fake_cot_history(weeks=160, client=None):
    start = dt.date(2023, 9, 5)
    return [
        {"date": (start + dt.timedelta(weeks=i)).isoformat(), "open_interest": 400000.0,
         "spec_long": 250000.0 + (i % 13) * 1000, "spec_short": 30000.0, "spec_net": 220000.0 + (i % 13) * 1000,
         "comm_net": -260000.0, "small_net": 30000.0}
        for i in range(weeks)
    ]


def test_ingestion_computes_a_snapshot_per_horizon_from_one_data_fetch(monkeypatch, db_session):
    _patch_all_connectors(monkeypatch)

    snapshot = run_ingest.compute_and_store_score(db_session, horizon="1-10d")

    assert isinstance(snapshot, ScoreSnapshot)
    assert snapshot.horizon == "1-10d"
    all_snapshots = db_session.query(ScoreSnapshot).all()
    assert {s.horizon for s in all_snapshots} == set(SUPPORTED_HORIZONS)
    assert len(all_snapshots) == len(SUPPORTED_HORIZONS)

    # macro/news must be fetched exactly once per cycle, not once per horizon
    assert db_session.query(MacroObservation).count() == len(run_ingest.FRED_SERIES) + 1  # +1 CFTC


def test_ingestion_dedupes_same_event_across_sources_and_records_traceable_history(monkeypatch, db_session):
    _patch_all_connectors(monkeypatch)

    run_ingest.compute_and_store_score(db_session, horizon="1-10d")

    news_items = db_session.query(NewsItem).all()
    assert len(news_items) == 2  # both stored, for full audit trail
    duplicates = [n for n in news_items if n.duplicate_of_id is not None]
    originals = [n for n in news_items if n.duplicate_of_id is None]
    assert len(duplicates) == 1
    assert len(originals) == 1
    assert duplicates[0].duplicate_of_id == originals[0].id
    assert originals[0].sentiment_scores.get("fed_tone", 0) > 0  # dovish -> bullish for gold

    # scoring must only count the fed_tone signal once, not twice
    fed_signal = run_ingest._news_signal(db_session, "fed_tone")
    assert fed_signal.item_count == 1
    assert fed_signal.item_ids == [originals[0].id]

    history = db_session.query(ScoreHistoryEntry).all()
    assert len(history) == len(SUPPORTED_HORIZONS)  # first snapshot ever, on every horizon -> always logged
    entry = history[0]
    assert originals[0].id in entry.related_news_ids
    assert len(entry.related_observation_ids) > 0  # FRED + CFTC observations feeding this snapshot
    assert isinstance(entry.pillar_deltas, dict)


def test_ingestion_is_idempotent_on_second_run_with_unchanged_inputs(monkeypatch, db_session):
    monkeypatch.setattr(fred.secrets, "get", lambda name: "dummy-key" if name == "FRED_API_KEY" else "")
    monkeypatch.setattr(fred, "fetch_observations", _fake_fred_observations)
    monkeypatch.setattr(cot, "fetch_latest_two_gold_reports", _fake_cot_reports)
    monkeypatch.setattr(cot, "fetch_gold_history", _fake_cot_history)
    monkeypatch.setattr(rss_news, "fetch_all_feeds", lambda client=None: [])
    monkeypatch.setattr(gdelt, "fetch_all_queries", lambda client=None, sleep_fn=None: ([], []))

    run_ingest.compute_and_store_score(db_session, horizon="1-10d")
    run_ingest.compute_and_store_score(db_session, horizon="1-10d")

    # same inputs both times -> same score per horizon -> no second history entry
    assert db_session.query(ScoreHistoryEntry).count() == len(SUPPORTED_HORIZONS)
    # observations are upserted, not duplicated, across two ingestion cycles
    assert db_session.query(MacroObservation).count() == len(run_ingest.FRED_SERIES) + 1  # +1 for CFTC
    assert db_session.query(ScoreSnapshot).count() == len(SUPPORTED_HORIZONS) * 2  # a new snapshot IS stored every cycle


def test_stale_news_is_reclassified_with_the_current_classifier(db_session):
    from app.news.classifier import CLASSIFIER_VERSION

    item = NewsItem(
        source="gdelt:example.com", dedup_hash="x", title="Fed announces rate hike", url="https://example.com",
        published_at=NOW, raw_snippet="", instrument_tags=[], relevance_score=0.0, sentiment="bullish",
        sentiment_scores={"fed_tone": 1.0}, factor_tags=["fed_tone"], classifier_version=CLASSIFIER_VERSION - 1,
    )
    db_session.add(item)
    db_session.commit()

    assert run_ingest.reclassify_stale_news(db_session) == 1
    db_session.refresh(item)
    assert item.sentiment_scores["fed_tone"] < 0  # hawkish, as the fixed classifier reads it
    assert item.classifier_version == CLASSIFIER_VERSION
    assert run_ingest.reclassify_stale_news(db_session) == 0


def test_same_article_returned_by_two_gdelt_queries_is_stored_once_and_cycle_survives(monkeypatch, db_session):
    """Live regression 2026-09-29: GDELT returned one article for two queries;
    the second copy hit the UNIQUE constraint and failed the whole cycle."""
    article = gdelt.RawNewsEntry(
        source="gdelt:akronnewsreporter.com",
        title="American view of the economy sinks to the lowest level since 2014",
        url="https://www.akronnewsreporter.com/2026/09/29/consumer-confidence-september/",
        published_at=NOW,
        snippet="American view of the economy sinks to the lowest level since 2014",
    )
    _patch_all_connectors(monkeypatch)
    monkeypatch.setattr(rss_news, "fetch_all_feeds", lambda client=None: [])
    monkeypatch.setattr(gdelt, "fetch_all_queries", lambda client=None, sleep_fn=None: ([article, article], []))

    run_ingest.compute_and_store_score(db_session)

    assert db_session.query(NewsItem).filter(NewsItem.url == article.url).count() == 1
    assert run_ingest.LAST_CYCLE["error"] is None


def test_near_duplicate_within_one_batch_is_detected(monkeypatch, db_session):
    _patch_all_connectors(monkeypatch)
    monkeypatch.setattr(rss_news, "fetch_all_feeds", lambda client=None: [])
    first = gdelt.RawNewsEntry("gdelt:a.com", "Fed cuts rates by 25bps, signals dovish path", "https://a.com/1", NOW, "")
    second = gdelt.RawNewsEntry("gdelt:b.com", "Federal Reserve cuts interest rates 25bps in dovish move", "https://b.com/2", NOW, "")
    monkeypatch.setattr(gdelt, "fetch_all_queries", lambda client=None, sleep_fn=None: ([first, second], []))

    run_ingest.compute_and_store_score(db_session)

    items = db_session.query(NewsItem).order_by(NewsItem.id).all()
    assert len(items) == 2 and items[1].duplicate_of_id == items[0].id


def test_portal_news_is_stored_with_language_and_czech_titles_are_kept(monkeypatch, db_session):
    from app.connectors import portals
    from app.news import translate

    _patch_all_connectors(monkeypatch)
    entries = [
        portals.PortalEntry("fxstreet.cz", "Fed zvažuje další zvýšení sazeb, zlato oslabuje", "https://www.fxstreet.cz/a", NOW, "", "cs"),
        portals.PortalEntry("FXStreet", "Gold slides as Fed rate hike bets build", "https://www.fxstreet.com/b", NOW, "", "en"),
    ]
    monkeypatch.setattr(portals, "fetch_all", lambda client=None: (entries, []))
    monkeypatch.setattr(translate, "translate", lambda text: "PŘELOŽENO: " + text)

    run_ingest.compute_and_store_score(db_session)

    cz = db_session.query(NewsItem).filter(NewsItem.source == "fxstreet.cz").one()
    en = db_session.query(NewsItem).filter(NewsItem.source == "FXStreet").one()
    assert cz.language == "cs" and cz.title_cs == cz.title
    assert "fed_tone" in cz.factor_tags and cz.sentiment_scores["fed_tone"] < 0  # Czech lexicon: hawkish
    assert "XAUUSD" in cz.instrument_tags
    assert en.language == "en" and en.title_cs.startswith("PŘELOŽENO: ")

    mood = run_ingest.news_mood(db_session, dt.datetime.now(dt.timezone.utc))
    assert mood["count"] >= 1 and mood["bearish"] >= 1


def test_market_refresh_recomputes_between_cycles_and_keeps_the_table_small(monkeypatch, db_session):
    from app.models import AnalysisSnapshot

    _patch_all_connectors(monkeypatch)
    monkeypatch.setattr(run_ingest, "KEEP_ANALYSIS_SNAPSHOTS", 3)
    run_ingest.compute_and_store_score(db_session)
    for _ in range(4):
        assert run_ingest.refresh_market(db_session) is True
    rows = db_session.query(AnalysisSnapshot).all()
    assert len(rows) == 3
    assert "sources_status" in rows[0].payload and "market" in rows[0].payload
