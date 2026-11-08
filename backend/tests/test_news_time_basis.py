"""Where a news item's time comes from (ETAPA 2, 2026-11-07): the source's publication time, GDELT's first sighting,
or FTI's fetch time when the source gives none — always recorded and labelled, never passed off as a publication
time. Old rows get it by a fixed rule; their times are never changed."""

import datetime as dt

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.connectors import portals, rss_news
from app.data import migrations
from app.db import Base

UTC = dt.timezone.utc
RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Dated</title><link>https://x/1</link><pubDate>Fri, 06 Nov 2026 14:30:00 GMT</pubDate></item>
<item><title>Undated</title><link>https://x/2</link></item></channel></rss>"""


def test_rss_and_portals_label_a_missing_time_instead_of_hiding_it():
    import httpx

    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=RSS)))
    by_title = {e.title: e for e in rss_news.fetch_feed("Test", "https://x/feed", client=client)}
    assert by_title["Dated"].time_basis == "published"
    assert by_title["Dated"].published_at == dt.datetime(2026, 11, 6, 14, 30, tzinfo=UTC)
    assert by_title["Undated"].time_basis == "fetched"  # FTI's fetch time stands in — and says so
    feed = portals.FEEDS[0]
    got = {e.title: e.time_basis for e in portals.parse_feed(feed, RSS)}
    assert got == {"Dated": "published", "Undated": "fetched"}


def test_old_rows_are_classified_once_and_their_times_stay():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    with engine.begin() as c:
        c.execute(text("ALTER TABLE news_items DROP COLUMN time_basis"))  # a database from before the column
    rows = [  # (source, published_at, fetched_at)
        ("gdelt:reuters.com", "2026-11-01 10:15:00.000000", "2026-11-01 10:40:12.123456"),
        ("CNBC", "2026-11-01 10:31:26.000000", "2026-11-01 10:32:44.286329"),  # feed time, fetched 78 s later
        ("Investing.com technika", "2026-10-31 20:17:00.198218", "2026-10-31 20:17:00.528114"),  # stamped by FTI
    ]
    with engine.begin() as c:
        for i, (src, pub, fet) in enumerate(rows):
            c.execute(text("INSERT INTO news_items (source, dedup_hash, title, url, published_at, fetched_at, raw_snippet, "
                           "instrument_tags, relevance_score, sentiment, sentiment_scores, factor_tags, classifier_version, "
                           "language) VALUES (:s, :h, 't', 'u', :p, :f, '', '[]', 0, 'neutral', '{}', '[]', 0, 'en')"),
                      {"s": src, "h": f"h{i}", "p": pub, "f": fet})
    assert "2026-11-07_news_time_basis" in migrations.apply_all(engine)
    assert migrations.apply_all(engine) == []  # recorded: runs once
    with engine.connect() as c:
        got = c.execute(text("SELECT source, published_at, time_basis FROM news_items ORDER BY id")).fetchall()
    assert [g[2] for g in got] == ["gdelt_seen", "published", "fetched"]
    assert [g[1] for g in got] == [r[1] for r in rows]  # the times themselves are untouched


def test_the_stored_item_keeps_where_its_time_comes_from():
    from app.connectors.gdelt import RawNewsEntry
    from app.ingestion import run_ingest
    from app.models import NewsItem

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        run_ingest._store_news_entries(s, [RawNewsEntry("gdelt:a.com", "Gold up", "https://a/1",
                                                        dt.datetime(2026, 11, 7, 9, 0, tzinfo=UTC), "Gold up")])
        assert s.query(NewsItem).one().time_basis == "gdelt_seen"
