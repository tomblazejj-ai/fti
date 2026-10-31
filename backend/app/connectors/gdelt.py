"""GDELT 2.0 DOC API — free, global, no API key, no ToS restriction on reuse
(GDELT states its datasets are free for unrestricted academic/commercial/
government use). This is an official documented API endpoint, not scraping.

Hard limitation, verified live on 2026-09-27 (see docs/DECISIONS.md): the
public endpoint enforces "one request per 5 seconds" and — from this
project's network — was rate-limited even at 20s spacing, returning a plain
text notice instead of JSON. The connector treats that as GdeltUnavailable,
never as empty-but-successful data, so the scoring engine can tell "no
geopolitical news happened" apart from "GDELT didn't answer".

The DOC API returns only article metadata (title, url, seendate, domain,
sourcecountry) — no per-article sentiment/tone. Tone would require pulling
the separate GKG 2.0 bulk CSV files (15-minute updates, much heavier), which
is out of scope for Modul 2; headline sentiment here goes through the same
rule-based lexicon as RSS (see app/news/classifier.py), not GDELT's own tone.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass

import httpx

DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
MIN_SECONDS_BETWEEN_REQUESTS = 5.0

# Fixed, small query set — keeps us well inside the rate limit per ingestion
# cycle and maps directly to the factor tags the XAUUSD engine cares about.
QUERIES: dict[str, str] = {
    # GDELT requires OR'd terms grouped in parentheses — an ungrouped
    # "a OR b OR c" is a syntax error (verified live: returns a plain-text
    # "must be surrounded by ()" error instead of JSON, which the connector
    # would otherwise report as a generic GdeltUnavailableError).
    "gold": "(gold OR bullion OR \"XAU/USD\")",
    "fed_tone": "\"Federal Reserve\" (rate OR hawkish OR dovish OR FOMC)",
    "geopolitics": "(war OR sanctions OR ceasefire OR \"trade war\" OR tariffs)",
}


class GdeltUnavailableError(RuntimeError):
    pass


class GdeltRateLimitedError(GdeltUnavailableError):
    """GDELT asked us to slow down — the remaining queries would fail too."""


@dataclass
class RawNewsEntry:
    source: str
    title: str
    url: str
    published_at: dt.datetime
    snippet: str
    language: str = "en"  # "en" | "cs" | "other" — only English gets machine-translated


def _language(raw: str | None) -> str:
    raw = (raw or "").lower()
    return "en" if raw in ("", "english") else "cs" if raw == "czech" else "other"


def _parse_seendate(raw: str) -> dt.datetime:
    # GDELT format: "20260927T140000Z"
    return dt.datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)


def fetch_query(query_label: str, query: str, client: httpx.Client | None = None) -> list[RawNewsEntry]:
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": 20,
        "sort": "datedesc",
    }
    owns_client = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        resp = client.get(DOC_API_URL, params=params)
        if resp.status_code == 429:
            raise GdeltRateLimitedError(f"GDELT DOC API omezuje počet dotazů (HTTP 429), dotaz '{query_label}' přeskočen")
        resp.raise_for_status()
        try:
            payload = resp.json()
        except ValueError as exc:
            raise GdeltRateLimitedError(
                f"GDELT nevrátil JSON pro dotaz '{query_label}' (pravděpodobně rate limit): {resp.text[:200]}"
            ) from exc
    except httpx.HTTPError as exc:
        raise GdeltUnavailableError(f"GDELT DOC API nedostupné pro dotaz '{query_label}': {exc}") from exc
    finally:
        if owns_client:
            client.close()

    entries = []
    for art in payload.get("articles", []):
        try:
            published_at = _parse_seendate(art["seendate"])
        except (KeyError, ValueError):
            published_at = dt.datetime.now(dt.timezone.utc)
        entries.append(
            RawNewsEntry(
                source=f"gdelt:{art.get('domain', 'unknown')}",
                title=art.get("title", ""),
                url=art.get("url", ""),
                published_at=published_at,
                snippet=art.get("title", ""),  # DOC API artlist has no body/snippet, only title
                language=_language(art.get("language")),
            )
        )
    return entries


def fetch_all_queries(client: httpx.Client | None = None, sleep_fn=time.sleep) -> tuple[list[RawNewsEntry], list[str]]:
    """Run all configured queries, respecting the rate limit between calls.

    Returns (entries, errors) — never raises. A query that fails is skipped
    and reported in `errors`; the caller decides whether "partial GDELT
    data" is acceptable (it is — better than nothing, and clearly logged).
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=15.0)
    entries: list[RawNewsEntry] = []
    errors: list[str] = []
    try:
        for i, (label, query) in enumerate(QUERIES.items()):
            if i > 0:
                sleep_fn(MIN_SECONDS_BETWEEN_REQUESTS)
            try:
                entries.extend(fetch_query(label, query, client=client))
            except GdeltRateLimitedError as exc:
                # A 429 answer itself takes ~15 s; asking again only delays the
                # whole cycle (and the fresh verdict) by that much per query.
                errors.append(f"{exc} — zbylé dotazy GDELT přeskočeny do příští aktualizace")
                break
            except GdeltUnavailableError as exc:
                errors.append(str(exc))
        return entries, errors
    finally:
        if owns_client:
            client.close()
