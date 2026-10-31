from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app.db import add_missing_columns, init_db


def test_new_columns_are_added_to_an_existing_database_without_losing_rows():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    init_db(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE news_items DROP COLUMN title_cs"))
        conn.execute(text("ALTER TABLE news_items DROP COLUMN language"))
        conn.execute(text(
            "INSERT INTO news_items (source, dedup_hash, title, url, published_at, fetched_at, raw_snippet, instrument_tags,"
            " relevance_score, sentiment, sentiment_scores, factor_tags, classifier_version)"
            " VALUES ('Fed', 'h1', 't', 'u', '2026-09-30 10:00:00', '2026-09-30 10:00:00', '', '[]', 0, 'neutral', '{}', '[]', 4)"
        ))

    added = add_missing_columns(engine)

    assert set(added) == {"news_items.language", "news_items.title_cs"}
    cols = {c["name"] for c in inspect(engine).get_columns("news_items")}
    assert {"language", "title_cs"} <= cols
    with engine.connect() as conn:
        assert conn.execute(text("SELECT language, title_cs FROM news_items")).one() == ("en", None)
    assert add_missing_columns(engine) == []  # idempotent
