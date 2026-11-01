"""Official RSS feeds of large financial news portals — free, no key.

Only the portals' own RSS endpoints are used (RSS exists precisely to be
subscribed to; robots.txt of every site below allows these paths — checked
live 2026-09-29). No HTML pages are scraped. One request per feed per
ingestion cycle (default every 30 min).

Language: fxstreet.cz is Czech; the others are English and get a local
machine translation into Czech (app/news/translate.py).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import feedparser
import httpx

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) fundamental-trading-intelligence/0.5 (personal RSS reader)"


@dataclass(frozen=True)
class Feed:
    source: str  # shown to the user
    url: str
    language: str  # "cs" | "en"


FEEDS: list[Feed] = [
    Feed("fxstreet.cz", "https://www.fxstreet.cz/kratke-zpravy.rss", "cs"),
    Feed("FXStreet", "https://www.fxstreet.com/rss/news", "en"),
    Feed("FXStreet analýzy", "https://www.fxstreet.com/rss/analysis", "en"),
    Feed("Investing.com", "https://www.investing.com/rss/news.rss", "en"),
    Feed("Investing.com komodity", "https://www.investing.com/rss/news_11.rss", "en"),
    Feed("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "en"),
    Feed("CNBC ekonomika", "https://www.cnbc.com/id/20910258/device/rss/rss.html", "en"),
    Feed("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "en"),
    # technical outlooks published by the portals themselves (checked 2026-10-31)
    Feed("Investing.com technika", "https://www.investing.com/rss/forex_Technical.rss", "en"),
    Feed("Investing.com technika komodit", "https://www.investing.com/rss/commodities_Technical.rss", "en"),
    Feed("Investing.com technika trhů", "https://www.investing.com/rss/market_overview_Technical.rss", "en"),
    Feed("FXEmpire prognózy", "https://www.fxempire.com/api/v1/en/articles/rss/forecasts", "en"),
]
TECHNICAL_SOURCES = {"FXStreet analýzy", "Investing.com technika", "Investing.com technika komodit", "Investing.com technika trhů",
                     "FXEmpire prognózy"}

MAX_ITEMS_PER_FEED = 60


@dataclass
class PortalEntry:
    source: str
    title: str
    url: str
    published_at: dt.datetime
    snippet: str
    language: str


def parse_feed(feed: Feed, content: bytes) -> list[PortalEntry]:
    parsed = feedparser.parse(content)
    out = []
    for e in parsed.entries[:MAX_ITEMS_PER_FEED]:
        title = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()
        if not title or not link:
            continue
        stamp = e.get("published_parsed") or e.get("updated_parsed")
        published = dt.datetime(*stamp[:6], tzinfo=dt.timezone.utc) if stamp else dt.datetime.now(dt.timezone.utc)
        out.append(PortalEntry(feed.source, title, link, published, e.get("summary", "") or "", feed.language))
    return out


def fetch_all(client: httpx.Client | None = None) -> tuple[list[PortalEntry], list[str]]:
    """Returns (entries, warnings). A failing portal never stops the others."""
    owns = client is None
    client = client or httpx.Client(timeout=20.0, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    entries: list[PortalEntry] = []
    warnings: list[str] = []
    try:
        for feed in FEEDS:
            try:
                resp = client.get(feed.url)
                resp.raise_for_status()
                entries.extend(parse_feed(feed, resp.content))
            except httpx.HTTPError as exc:
                warnings.append(f"Zprávy z {feed.source} nedostupné: {exc}")
        return entries, warnings
    finally:
        if owns:
            client.close()
