import datetime as dt

from app.models import NewsItem
from app.news.dedupe import find_duplicate

NOW = dt.datetime(2026, 9, 27, 12, 0, tzinfo=dt.timezone.utc)


def _add_news(session, title, published_at, factor_tags, instrument_tags, source="Fed"):
    item = NewsItem(
        source=source,
        dedup_hash=f"hash-{title}",
        title=title,
        url=f"https://example.com/{title}",
        published_at=published_at,
        raw_snippet=title,
        instrument_tags=instrument_tags,
        factor_tags=factor_tags,
        relevance_score=0.5,
        sentiment="neutral",
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def test_same_event_different_headline_is_flagged_as_duplicate(db_session):
    original = _add_news(
        db_session, "Fed cuts rates by 25bps, signals dovish path", NOW, ["fed_tone"], [],
    )
    dup = find_duplicate(
        db_session,
        title="Federal Reserve cuts interest rates 25bps in dovish move",
        published_at=NOW + dt.timedelta(hours=2),
        factor_tags=["fed_tone"],
        instrument_tags=[],
    )
    assert dup is not None
    assert dup.id == original.id


def test_unrelated_headline_sharing_no_tag_is_not_a_duplicate(db_session):
    _add_news(db_session, "Fed cuts rates by 25bps", NOW, ["fed_tone"], [])
    dup = find_duplicate(
        db_session,
        title="Gold rallies as bullion demand rises",
        published_at=NOW + dt.timedelta(hours=1),
        factor_tags=["cb_gold_buying"],
        instrument_tags=["XAUUSD"],
    )
    assert dup is None


def test_similar_words_but_no_shared_tag_is_not_a_duplicate(db_session):
    _add_news(db_session, "War escalates in region", NOW, ["geopolitics"], [])
    dup = find_duplicate(
        db_session,
        title="War movie premieres in region to strong reviews",
        published_at=NOW + dt.timedelta(hours=1),
        factor_tags=[],  # no factor tag matched by classifier -> never compared
        instrument_tags=[],
    )
    assert dup is None


def test_outside_lookback_window_is_not_a_duplicate(db_session):
    _add_news(db_session, "Fed cuts rates by 25bps, signals dovish path", NOW, ["fed_tone"], [])
    dup = find_duplicate(
        db_session,
        title="Fed cuts rates by 25bps, signals dovish path",
        published_at=NOW + dt.timedelta(days=10),
        factor_tags=["fed_tone"],
        instrument_tags=[],
        lookback_days=5,
    )
    assert dup is None


def test_does_not_match_against_an_item_that_is_itself_already_a_duplicate(db_session):
    original = _add_news(db_session, "Fed cuts rates by 25bps", NOW, ["fed_tone"], [])
    already_dup = _add_news(
        db_session, "Federal Reserve cuts rates 25bps", NOW + dt.timedelta(hours=1), ["fed_tone"], []
    )
    already_dup.duplicate_of_id = original.id
    db_session.commit()

    dup = find_duplicate(
        db_session,
        title="Fed lowers rates by 25 basis points",
        published_at=NOW + dt.timedelta(hours=2),
        factor_tags=["fed_tone"],
        instrument_tags=[],
    )
    assert dup is not None
    assert dup.id == original.id  # chains back to the original, not the intermediate duplicate
