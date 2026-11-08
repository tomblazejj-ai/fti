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

Times: the DOC API gives no publication time, only "seendate" — when GDELT first saw the article.
That is what FTI stores, labelled time_basis="gdelt_seen" ("zachyceno GDELT"), never as the
publication time; an article without seendate is left out (never stamped with the current time).

Relevance (finding C, 2026-11-07): GDELT matches the query against machine translations of whole articles
in ~65 languages, so a bare "gold" returned ~15–20 gold-market articles out of 250 (medals, a Greek island,
a choir …). The gold query therefore asks for gold together with a market word, and FTI keeps only titles
about gold as a market (app/news/relevance.py — about twenty languages; nothing is limited to English).
How many were left out is kept in the state ("filtered").

Requests (ETAPA 2, 2026-11-07: of 152 requests 63 = 41 % were refused with HTTP 429 at 5 s spacing):
the queries take turns (QUERIES_PER_CYCLE per cycle, 10 s apart), each asks only for articles
since its last success (plus an overlap), a refusal pauses GDELT for 15 → 30 → 60 min (kept in
series_cache "gdelt:state", so a restart does not hammer it again), a short outage is retried once.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass

import httpx

from app.news import relevance

DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
MIN_SECONDS_BETWEEN_REQUESTS = 10.0  # GDELT asks for at least 5 s; at 5 s 41 % of FTI's requests were still refused
QUERIES_PER_CYCLE = 2
PAUSES = (15 * 60, 30 * 60, 60 * 60)  # seconds GDELT is left alone after consecutive refusals
OVERLAP = dt.timedelta(minutes=15)  # each query asks again for the last 15 min before its last success
MAX_LOOKBACK = dt.timedelta(days=3)
MAX_RECORDS = 75
STATE_KEY = "gdelt:state"

# Fixed, small query set — keeps us well inside the rate limit per ingestion
# cycle and maps directly to the factor tags the XAUUSD engine cares about.
QUERIES: dict[str, str] = {
    # GDELT requires OR'd terms grouped in parentheses — an ungrouped
    # "a OR b OR c" is a syntax error (verified live: returns a plain-text
    # "must be surrounded by ()" error instead of JSON, which the connector
    # would otherwise report as a generic GdeltUnavailableError).
    # gold AND a market word — GDELT applies both to the translated text, so this works in every language
    "gold": ("(gold OR bullion OR \"XAU/USD\") (price OR prices OR ounce OR futures OR \"central bank\" OR "
             "\"central banks\" OR mining OR miners OR commodity OR commodities OR \"precious metals\" OR inflation "
             "OR investors OR reserves)"),
    "fed_tone": "\"Federal Reserve\" (rate OR hawkish OR dovish OR FOMC)",
    "geopolitics": "(war OR sanctions OR ceasefire OR \"trade war\" OR tariffs)",
}


class GdeltUnavailableError(RuntimeError):
    pass


class GdeltRateLimitedError(GdeltUnavailableError):
    """GDELT asked us to slow down — the remaining queries would fail too."""


class GdeltQueryRejectedError(GdeltUnavailableError):
    """GDELT answered with a text that is no rate-limit notice (e.g. it does not accept the query's form):
    reported for this query only — no pause for the others and no retry of the same query."""


@dataclass
class RawNewsEntry:
    source: str
    title: str
    url: str
    published_at: dt.datetime
    snippet: str
    language: str = "en"  # "en" | "cs" | "other" — only English gets machine-translated
    time_basis: str = "gdelt_seen"  # GDELT gives no publication time, only when it first saw the article
    source_language: str = ""  # GDELT's own language name ("English", "Slovak", "Chinese" …)


def _language(raw: str | None) -> str:
    raw = (raw or "").lower()
    return "en" if raw in ("", "english") else "cs" if raw == "czech" else "other"


def _parse_seendate(raw: str) -> dt.datetime:
    # GDELT format: "20260927T140000Z"
    return dt.datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)


def fetch_query(query_label: str, query: str, client: httpx.Client | None = None,
                since: dt.datetime | None = None) -> list[RawNewsEntry]:
    """Articles of one query: since `since` when given (incremental), else of the last day."""
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": MAX_RECORDS,
        "sort": "datedesc",
    }
    if since is not None:
        params["startdatetime"] = since.astimezone(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    else:
        params["timespan"] = "1d"
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
            notice = resp.text[:200]
            if not notice.strip() or "limit" in notice.lower():
                raise GdeltRateLimitedError(
                    f"GDELT nevrátil JSON pro dotaz '{query_label}' (pravděpodobně rate limit): {notice}"
                ) from exc
            raise GdeltQueryRejectedError(f"GDELT dotaz '{query_label}' nepřijal: {notice}") from exc
    except httpx.HTTPError as exc:
        raise GdeltUnavailableError(f"GDELT DOC API nedostupné pro dotaz '{query_label}': {exc}") from exc
    finally:
        if owns_client:
            client.close()

    entries = []
    for art in payload.get("articles", []):
        try:
            seen = _parse_seendate(art["seendate"])
        except (KeyError, ValueError):
            continue  # no time at all: left out rather than stamped with the current time
        entries.append(
            RawNewsEntry(
                source=f"gdelt:{art.get('domain', 'unknown')}",
                title=art.get("title", ""),
                url=art.get("url", ""),
                published_at=seen,
                snippet=art.get("title", ""),  # DOC API artlist has no body/snippet, only title
                language=_language(art.get("language")),
                source_language=art.get("language") or "",
            )
        )
    if query_label == "gold":
        kept = [e for e in entries if relevance.gold_market(e.title, e.source_language or None)[0]]
        last_filtered[query_label] = {"received": len(entries), "kept": len(kept)}
        return kept
    return entries


_memory: dict = {}  # the state when series_cache is not reachable (tests)
last_filtered: dict = {}  # per query: articles GDELT returned / kept by FTI's relevance check (last answer)


def _load_state() -> dict:
    from app.data import store

    payload, _ = store.cache_get(STATE_KEY)
    state = dict(payload) if isinstance(payload, dict) else dict(_memory)
    state.setdefault("next", 0)
    state.setdefault("fails", 0)
    state.setdefault("paused_until", None)
    state["last_ok"] = dict(state.get("last_ok") or {})
    return state


def _save_state(state: dict) -> None:
    from app.data import store

    _memory.clear()
    _memory.update(state)
    store.cache_put(STATE_KEY, state, source="FTI GDELT")


def reset() -> None:
    _memory.clear()


def fetch_all_queries(client: httpx.Client | None = None, sleep_fn=time.sleep,
                      now: dt.datetime | None = None) -> tuple[list[RawNewsEntry], list[str]]:
    """Ask the queries whose turn it is, gently. Returns (entries, errors) — never raises.

    A refused request pauses GDELT (15 → 30 → 60 min) and ends this cycle; a short outage is tried once more;
    each query asks only for what came since its last success. The caller decides whether partial GDELT data
    is acceptable (it is — better than nothing, and clearly logged)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    state = _load_state()
    if state["paused_until"] and dt.datetime.fromisoformat(state["paused_until"]) > now:
        return [], [f"GDELT po odmítnutí dotazů odpočívá do {state['paused_until'][11:16]} UTC — dotazy se teď neposílají"]
    labels = list(QUERIES)
    turn = [labels[(state["next"] + i) % len(labels)] for i in range(min(QUERIES_PER_CYCLE, len(labels)))]
    owns_client = client is None
    client = client or httpx.Client(timeout=15.0)
    entries: list[RawNewsEntry] = []
    errors: list[str] = []
    asked = 0
    try:
        for i, label in enumerate(turn):
            if i > 0:
                sleep_fn(MIN_SECONDS_BETWEEN_REQUESTS)
            last = state["last_ok"].get(label)
            since = max(dt.datetime.fromisoformat(last) - OVERLAP, now - MAX_LOOKBACK) if last else None
            try:
                try:
                    got = fetch_query(label, QUERIES[label], client=client, since=since)
                except (GdeltRateLimitedError, GdeltQueryRejectedError):
                    raise
                except GdeltUnavailableError:
                    sleep_fn(MIN_SECONDS_BETWEEN_REQUESTS)  # a short outage: one more try, then give up for this cycle
                    got = fetch_query(label, QUERIES[label], client=client, since=since)
            except GdeltRateLimitedError as exc:
                state["fails"] += 1
                pause = PAUSES[min(state["fails"], len(PAUSES)) - 1]
                state["paused_until"] = (now + dt.timedelta(seconds=pause)).isoformat()
                errors.append(f"{exc} — GDELT teď {pause // 60} min odpočívá, zbylé dotazy přeskočeny")
                break  # the refused query goes first next time
            except GdeltUnavailableError as exc:
                errors.append(str(exc))
                asked += 1
                continue
            entries.extend(got)
            if label in last_filtered:
                state.setdefault("filtered", {})[label] = {**last_filtered[label], "at": now.isoformat()}
            state["last_ok"][label] = now.isoformat()
            state["fails"] = 0
            state["paused_until"] = None
            asked += 1
        state["next"] = (state["next"] + asked) % len(labels)
        _save_state(state)
        return entries, errors
    finally:
        if owns_client:
            client.close()
