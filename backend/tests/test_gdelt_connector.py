import datetime as dt

import httpx

from app.connectors import gdelt

NOW = dt.datetime(2026, 11, 7, 12, 0, tzinfo=dt.timezone.utc)


def _ok(articles=()):
    return httpx.Response(200, json={"articles": list(articles)})


def test_fetch_query_parses_articles():
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok([{"url": "https://example.com/a", "title": "Gold rallies as Fed turns dovish",
                     "seendate": "20260927T140000Z", "domain": "example.com"}])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    entries = gdelt.fetch_query("gold", "gold", client=client)

    assert len(entries) == 1
    assert entries[0].source == "gdelt:example.com"
    assert entries[0].title == "Gold rallies as Fed turns dovish"
    assert entries[0].published_at == dt.datetime(2026, 9, 27, 14, 0, tzinfo=dt.timezone.utc)
    assert entries[0].time_basis == "gdelt_seen"  # when GDELT saw it — never passed off as the publication time


def test_an_article_without_any_time_is_left_out_never_stamped_with_now():
    def handler(request):
        return _ok([{"url": "u1", "title": "No time", "domain": "a.com"},
                    {"url": "u2", "title": "With time", "seendate": "20261107T110000Z", "domain": "b.com"}])

    # a query without the gold relevance check (that one is tested in test_news_findings.py)
    entries = gdelt.fetch_query("geopolitics", "war", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert [e.title for e in entries] == ["With time"]


def test_fetch_query_raises_gdelt_unavailable_on_rate_limit_text_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Please limit requests to one every 5 seconds")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        gdelt.fetch_query("gold", "gold", client=client)
        assert False, "expected GdeltUnavailableError"
    except gdelt.GdeltUnavailableError:
        pass


def test_the_queries_take_turns_two_per_cycle():
    asked = []

    def handler(request):
        asked.append(request.url.params["query"])
        return _ok()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    labels = list(gdelt.QUERIES)
    gdelt.fetch_all_queries(client=client, sleep_fn=lambda s: None, now=NOW)
    gdelt.fetch_all_queries(client=client, sleep_fn=lambda s: None, now=NOW + dt.timedelta(minutes=30))
    assert asked == [gdelt.QUERIES[labels[0]], gdelt.QUERIES[labels[1]], gdelt.QUERIES[labels[2]], gdelt.QUERIES[labels[0]]]


def test_a_query_asks_only_for_news_since_its_last_success():
    params = []

    def handler(request):
        params.append(dict(request.url.params))
        return _ok()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    for k in range(3):  # three cycles: every query has had one turn, the first one twice
        gdelt.fetch_all_queries(client=client, sleep_fn=lambda s: None, now=NOW + dt.timedelta(minutes=30 * k))
    assert params[0].get("timespan") == "1d" and "startdatetime" not in params[0]  # nothing known yet: the last day
    later = [p for p in params if p["query"] == params[0]["query"]][1]
    assert later["startdatetime"] == (NOW - gdelt.OVERLAP).strftime("%Y%m%d%H%M%S")  # since the last success, 15 min overlap


def test_a_short_outage_is_tried_once_more_and_reported():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, text="temporarily down") if calls["n"] <= 2 else _ok()

    sleeps = []
    entries, errors = gdelt.fetch_all_queries(client=httpx.Client(transport=httpx.MockTransport(handler)),
                                              sleep_fn=sleeps.append, now=NOW)
    assert entries == [] and len(errors) == 1  # first query: failed twice → reported; second query: fine
    assert calls["n"] == 3
    assert sleeps == [gdelt.MIN_SECONDS_BETWEEN_REQUESTS] * 2  # the retry and the next query, both spaced


def test_a_refusal_pauses_gdelt_longer_each_time_and_a_success_ends_it():
    calls = []
    answer = {"code": 429}

    def handler(request):
        calls.append(request)
        return httpx.Response(429, text="Please limit requests to one every 5 seconds") if answer["code"] == 429 else _ok()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    entries, errors = gdelt.fetch_all_queries(client=client, sleep_fn=lambda s: None, now=NOW)
    assert entries == [] and len(calls) == 1 and "429" in errors[0] and "15 min" in errors[0]
    _, errors = gdelt.fetch_all_queries(client=client, sleep_fn=lambda s: None, now=NOW + dt.timedelta(minutes=5))
    assert len(calls) == 1 and "odpočívá" in errors[0]  # paused: nothing is sent at all
    _, errors = gdelt.fetch_all_queries(client=client, sleep_fn=lambda s: None, now=NOW + dt.timedelta(minutes=16))
    assert len(calls) == 2 and "30 min" in errors[0]  # refused again: a longer pause
    answer["code"] = 200
    _, errors = gdelt.fetch_all_queries(client=client, sleep_fn=lambda s: None, now=NOW + dt.timedelta(minutes=50))
    assert errors == [] and len(calls) == 4  # fine again: both queries of the turn asked, the pause is over


def test_article_language_is_kept_so_only_english_gets_translated():
    def handler(request):
        return _ok([
            {"url": "u1", "title": "Gold falls", "seendate": "20260930T100000Z", "domain": "a.com", "language": "English"},
            {"url": "u2", "title": "Goldpreis bricht ein", "seendate": "20260930T100000Z", "domain": "b.de", "language": "German"},
        ])

    entries = gdelt.fetch_query("gold", "gold", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert [e.language for e in entries] == ["en", "other"]
