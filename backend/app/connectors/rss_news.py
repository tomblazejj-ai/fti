"""Free, public RSS feeds — official central bank press releases.

All feeds below are official publications intended for syndication (RSS is
built for exactly this), not scraped HTML. No ToS violation, no cost.
BoJ has no stable public RSS at the time of writing — left out until
verified; do not silently scrape their site instead (see docs/DECISIONS.md
policy on scraping).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import feedparser
import httpx

FEEDS: dict[str, str] = {
    "Fed": "https://www.federalreserve.gov/feeds/press_all.xml",
    "ECB": "https://www.ecb.europa.eu/rss/press.html",
    "BoE": "https://www.bankofengland.co.uk/rss/news",
}


@dataclass
class RawNewsEntry:
    source: str
    title: str
    url: str
    published_at: dt.datetime
    snippet: str
    time_basis: str = "published"  # "fetched" when the feed gives no time (FTI's fetch time stands in)


def fetch_feed(source: str, url: str, client: httpx.Client | None = None) -> list[RawNewsEntry]:
    owns_client = client is None
    client = client or httpx.Client(timeout=15.0, follow_redirects=True)
    try:
        resp = client.get(url, headers={"User-Agent": "fundamental-trading-intelligence/0.1 (personal use)"})
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    finally:
        if owns_client:
            client.close()

    entries = []
    for entry in parsed.entries:
        title = entry.get("title", "")
        link = entry.get("link", "")
        if not link or title.upper().startswith("ERROR"):
            # Observed occasionally on BoE's feed: a transient CMS error
            # served instead of a real item. Skip rather than store garbage.
            continue
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        published_at = (
            dt.datetime(*published[:6], tzinfo=dt.timezone.utc)
            if published
            else dt.datetime.now(dt.timezone.utc)
        )
        entries.append(
            RawNewsEntry(
                source=source,
                title=entry.get("title", ""),
                url=entry.get("link", ""),
                published_at=published_at,
                snippet=entry.get("summary", ""),
                time_basis="published" if published else "fetched",
            )
        )
    return entries


def fetch_all_feeds(client: httpx.Client | None = None) -> list[RawNewsEntry]:
    owns_client = client is None
    client = client or httpx.Client(timeout=15.0, follow_redirects=True)
    try:
        out: list[RawNewsEntry] = []
        for source, url in FEEDS.items():
            out.extend(fetch_feed(source, url, client=client))
        return out
    finally:
        if owns_client:
            client.close()
