"""Group stored news items into *events* for display.

The ingestion layer already marks near-duplicates (NewsItem.duplicate_of_id,
see dedupe.py) so scoring never double-counts. The UI needs the same truth:
three outlets reporting one Fed decision is ONE event with three reports,
not three independent confirmations. Pure function, tested in
tests/test_grouping.py.
"""

from __future__ import annotations

from app.models import NewsItem
from app.news import translate

IMPACT_THRESHOLD = 0.1  # same threshold as PillarResult.impact


def _impact(score: float) -> str:
    if score > IMPACT_THRESHOLD:
        return "bullish"
    if score < -IMPACT_THRESHOLD:
        return "bearish"
    return "neutral"


def _czech(item: NewsItem) -> tuple[str, bool]:
    """(headline to show, is it a machine translation) — a translation that changed a number is not shown."""
    title, translated, _ = translate.shown_title(item.title, item.title_cs, item.language)
    return title, translated


def _translation_failed(item: NewsItem) -> bool:
    return translate.shown_title(item.title, item.title_cs, item.language)[2]


def _report(item: NewsItem) -> dict:
    title, translated = _czech(item)
    return {
        "id": item.id,
        "title": title,
        "title_original": item.title,
        "translated": translated,
        "translation_failed": _translation_failed(item),
        "source": item.source,
        "url": item.url or None,
        "published_at": item.published_at, "time_basis": item.time_basis,
    }


def group_into_events(items: list[NewsItem], factor_to_pillar: dict[str, str], instrument: str) -> list[dict]:
    """Return events, newest first. Only items relevant to `instrument`
    (tagged with the instrument, or carrying a factor that feeds one of its
    pillars) are included; an event is kept if its ORIGINAL is relevant.
    """
    originals = {i.id: i for i in items if i.duplicate_of_id is None}
    duplicates_by_original: dict[int, list[NewsItem]] = {}
    for item in items:
        if item.duplicate_of_id is not None and item.duplicate_of_id in originals:
            duplicates_by_original.setdefault(item.duplicate_of_id, []).append(item)

    events = []
    for original in originals.values():
        relevant_factors = [f for f in original.factor_tags if f in factor_to_pillar]
        if not relevant_factors and instrument not in original.instrument_tags:
            continue
        scores = [original.sentiment_scores.get(f, 0.0) for f in relevant_factors]
        net = sum(scores) / len(scores) if scores else 0.0
        reports = [original, *sorted(duplicates_by_original.get(original.id, []), key=lambda n: n.published_at)]
        headline, translated = _czech(original)
        events.append(
            {
                "event_id": original.id,
                "headline": headline,
                "headline_original": original.title,
                "translated": translated,
                "translation_failed": _translation_failed(original),
                "language": original.language,
                "source": original.source,
                "url": original.url or None,
                "published_at": original.published_at, "time_basis": original.time_basis,
                "instrument_tags": original.instrument_tags,
                "factors": [{"factor": f, "pillar": factor_to_pillar[f], "sentiment": original.sentiment_scores.get(f, 0.0)} for f in relevant_factors],
                "impact": _impact(net),
                "report_count": len(reports),
                "reports": [_report(r) for r in reports],
            }
        )
    # known times newest first; items with only FTI's fetch time (no publication time) after them
    events.sort(key=lambda e: (e.get("time_basis") != "fetched", e["published_at"]), reverse=True)
    return events
