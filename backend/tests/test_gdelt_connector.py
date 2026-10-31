import httpx

from app.connectors import gdelt


def test_fetch_query_parses_articles():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "url": "https://example.com/a",
                        "title": "Gold rallies as Fed turns dovish",
                        "seendate": "20260927T140000Z",
                        "domain": "example.com",
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    entries = gdelt.fetch_query("gold", "gold", client=client)

    assert len(entries) == 1
    assert entries[0].source == "gdelt:example.com"
    assert entries[0].title == "Gold rallies as Fed turns dovish"
    assert entries[0].published_at.year == 2026


def test_fetch_query_raises_gdelt_unavailable_on_rate_limit_text_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Please limit requests to one every 5 seconds")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        gdelt.fetch_query("gold", "gold", client=client)
        assert False, "expected GdeltUnavailableError"
    except gdelt.GdeltUnavailableError:
        pass


def test_fetch_all_queries_skips_failed_query_and_reports_error_not_crash():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(503, text="temporarily down")
        return httpx.Response(200, json={"articles": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps = []
    entries, errors = gdelt.fetch_all_queries(client=client, sleep_fn=sleeps.append)

    assert entries == []
    assert len(errors) == 1
    assert len(sleeps) == len(gdelt.QUERIES) - 1  # sleeps between calls, not before the first


def test_rate_limit_stops_remaining_queries_so_the_cycle_is_not_delayed():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, text="Please limit requests to one every 5 seconds")

    entries, errors = gdelt.fetch_all_queries(client=httpx.Client(transport=httpx.MockTransport(handler)), sleep_fn=lambda s: None)

    assert entries == []
    assert len(calls) == 1
    assert len(errors) == 1 and "429" in errors[0]


def test_article_language_is_kept_so_only_english_gets_translated():
    def handler(request):
        return httpx.Response(200, json={"articles": [
            {"url": "u1", "title": "Gold falls", "seendate": "20260930T100000Z", "domain": "a.com", "language": "English"},
            {"url": "u2", "title": "Gold bricht ein", "seendate": "20260930T100000Z", "domain": "b.de", "language": "German"},
        ]})

    entries = gdelt.fetch_query("gold", "gold", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert [e.language for e in entries] == ["en", "other"]
