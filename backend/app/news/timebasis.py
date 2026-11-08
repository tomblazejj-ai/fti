"""Where a news item's time comes from (news_items.time_basis), in one place.

  published   the source's own publication time
  gdelt_seen  when GDELT first saw the article; GDELT gives no publication time. The article was published
              at that moment at the latest. Measured on 42 GDELT articles with a date in their URL
              (2026-11-07): 37 seen the same day, 3 the next day, 2 two or three days later.
  fetched     the source gives no time; FTI's fetch time stands in. The item could have been published at
              any time before that, so its real age is unknown.

Nothing here invents a substitute time. An item whose real age is unknown never counts as fresh: it is
left out of every freshness-based calculation (headline risk, news mood, news weight in the score, oil
supply risk), each of which reports how many items it left out. Lists only show it, after the items with a
known time and with its origin labelled.
"""

from __future__ import annotations

PUBLISHED, GDELT_SEEN, FETCHED = "published", "gdelt_seen", "fetched"

# what the AI is told about the time "k" of a news fact
ORIGIN_AI = {
    PUBLISHED: "čas publikace uvedený zdrojem",
    GDELT_SEEN: ("čas, kdy článek zachytil GDELT — zdroj čas publikace neuvádí; článek vyšel nejpozději v tuto dobu, "
                 "obvykle týž den"),
    FETCHED: ("čas, kdy zprávu stáhlo FTI — zdroj čas publikace neuvádí; zpráva mohla vyjít kdykoli dříve, "
              "skutečné stáří je neznámé"),
}
ORIGIN_UNKNOWN_AI = "původ času neznámý — nepovažuj ho za čas publikace"


def age_known(time_basis: str | None) -> bool:
    """False when the item's real age is unknown (only FTI's fetch time is known)."""
    return time_basis != FETCHED


def origin_ai(time_basis: str | None) -> str:
    return ORIGIN_AI.get(time_basis or "", ORIGIN_UNKNOWN_AI)


def unknown_age_note(count: int) -> str:
    """One sentence for a calculation that left items of unknown age out."""
    if not count:
        return ""
    word = "zpráva" if count == 1 else "zprávy" if count < 5 else "zpráv"
    return f"{count} {word} bez času publikace (stáří neznámé) nezapočteno."
