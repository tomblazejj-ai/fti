"""Near-duplicate detection — "is this really new, or just another article

about an event we already stored?" (zadání section 5, point 3 + 9).

Exact-hash dedup (classifier.dedup_hash) only catches byte-identical
(source, title, url) — useless when Reuters and a central bank RSS both
report the same rate decision with different headlines. This module adds a
cheap, explainable second layer: token-overlap similarity within a lookback
window, restricted to items that already share a factor/instrument tag (so
we never merge two unrelated stories that happen to share common words).

The similarity threshold (0.25) is deliberately low: real headlines about
the same event from different outlets ("Fed cuts rates" vs "Federal Reserve
lowers interest rates") often share under a third of their tokens. This is
safe to keep loose because a false-positive match only removes one data
point from the scoring aggregation (see run_ingest._aggregate_news_signal)
— it never fabricates data, and the duplicate row stays in the DB with its
own source/timestamp for audit, it is just excluded from double-counting.
"""

from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NewsItem

STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "at",
    "by", "with", "as", "its", "it", "says", "said", "after", "over",
}


def _tokenize(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def find_duplicate(
    session: Session,
    title: str,
    published_at: dt.datetime,
    factor_tags: list[str],
    instrument_tags: list[str],
    lookback_days: int = 5,
    similarity_threshold: float = 0.25,
) -> NewsItem | None:
    """Return the earliest existing NewsItem this candidate is a near-duplicate
    of, or None if it looks like genuinely new information.

    Only compares against items sharing at least one factor or instrument
    tag — a title-similarity match across unrelated topics is a coincidence,
    not a duplicate event.
    """
    if not factor_tags and not instrument_tags:
        return None  # nothing to match on; exact-hash dedup already covers byte-identical cases

    cutoff = published_at - dt.timedelta(days=lookback_days)
    candidates = session.scalars(
        select(NewsItem)
        .where(NewsItem.published_at >= cutoff, NewsItem.published_at <= published_at)
        .order_by(NewsItem.published_at.asc())
    ).all()

    candidate_tokens = _tokenize(title)
    for existing in candidates:
        if existing.duplicate_of_id is not None:
            continue  # compare only against originals, not other duplicates
        shares_tag = bool(set(existing.factor_tags) & set(factor_tags)) or bool(
            set(existing.instrument_tags) & set(instrument_tags)
        )
        if not shares_tag:
            continue
        if _jaccard(candidate_tokens, _tokenize(existing.title)) >= similarity_threshold:
            return existing
    return None
