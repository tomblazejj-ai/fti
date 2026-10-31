import datetime as dt

from app.instruments import XAUUSD_FACTOR_TO_PILLAR
from app.models import NewsItem
from app.news.grouping import group_into_events

NOW = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)


def _item(id_, title, factor_tags, sentiment_scores, published_at, duplicate_of_id=None, instrument_tags=None, source="Fed"):
    return NewsItem(
        id=id_, source=source, dedup_hash=f"h{id_}", title=title, url=f"https://example.com/{id_}",
        published_at=published_at, raw_snippet="", instrument_tags=instrument_tags or [],
        relevance_score=0.5, sentiment="neutral", sentiment_scores=sentiment_scores,
        factor_tags=factor_tags, duplicate_of_id=duplicate_of_id,
    )


def test_duplicates_are_folded_into_one_event_with_all_reports():
    items = [
        _item(1, "Fed cuts rates", ["fed_tone"], {"fed_tone": 1.0}, NOW),
        _item(2, "Federal Reserve lowers rates", ["fed_tone"], {"fed_tone": 1.0}, NOW + dt.timedelta(hours=1), duplicate_of_id=1, source="gdelt:reuters.com"),
        _item(3, "Fed rate cut explained", ["fed_tone"], {"fed_tone": 1.0}, NOW + dt.timedelta(hours=2), duplicate_of_id=1, source="gdelt:ft.com"),
    ]
    events = group_into_events(items, XAUUSD_FACTOR_TO_PILLAR, "XAUUSD")
    assert len(events) == 1
    assert events[0]["report_count"] == 3
    assert [r["id"] for r in events[0]["reports"]] == [1, 2, 3]
    assert events[0]["impact"] == "bullish"
    assert events[0]["factors"][0]["pillar"] == "fed"


def test_irrelevant_items_are_excluded():
    items = [_item(1, "Bank merger approved", [], {}, NOW)]
    assert group_into_events(items, XAUUSD_FACTOR_TO_PILLAR, "XAUUSD") == []


def test_events_are_newest_first_and_impact_follows_sentiment():
    items = [
        _item(1, "Ceasefire agreed", ["geopolitics"], {"geopolitics": -0.6}, NOW - dt.timedelta(days=1)),
        _item(2, "War escalates", ["geopolitics"], {"geopolitics": 0.9}, NOW),
    ]
    events = group_into_events(items, XAUUSD_FACTOR_TO_PILLAR, "XAUUSD")
    assert [e["event_id"] for e in events] == [2, 1]
    assert events[0]["impact"] == "bullish" and events[1]["impact"] == "bearish"


def test_gold_tagged_item_without_factor_is_kept_as_neutral():
    items = [_item(1, "Gold price steady", [], {}, NOW, instrument_tags=["XAUUSD"])]
    events = group_into_events(items, XAUUSD_FACTOR_TO_PILLAR, "XAUUSD")
    assert len(events) == 1 and events[0]["impact"] == "neutral" and events[0]["factors"] == []
