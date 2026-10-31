import httpx
import pytest

from app.connectors import fred


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_keyless_csv_path_parses_and_drops_missing_values(monkeypatch):
    monkeypatch.setattr(fred.settings, "fred_api_key", "")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, text="observation_date,DFII10\n2026-09-22,2.63\n2026-09-23,\n2026-09-24,2.85\n")

    result = fred.fetch_observations("DFII10", client=_client(handler), sleep_fn=lambda s: None)

    assert "fredgraph.csv" in seen["url"] and "api_key" not in seen["url"]
    assert result == [{"date": "2026-09-22", "value": 2.63}, {"date": "2026-09-24", "value": 2.85}]


def test_csv_with_unexpected_header_is_unavailable_not_guessed(monkeypatch):
    monkeypatch.setattr(fred.settings, "fred_api_key", "")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    with pytest.raises(fred.FredUnavailableError):
        fred.fetch_observations("DFII10", client=_client(handler), sleep_fn=lambda s: None)


def test_csv_requests_respect_crawl_delay(monkeypatch):
    monkeypatch.setattr(fred.settings, "fred_api_key", "")
    monkeypatch.setattr(fred, "_last_csv_request_at", None)
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        series = request.url.params["id"]
        return httpx.Response(200, text=f"observation_date,{series}\n2026-09-01,1\n2026-09-02,2\n")

    client = _client(handler)
    fred.fetch_observations("DFII10", client=client, sleep_fn=sleeps.append)
    fred.fetch_observations("UNRATE", client=client, sleep_fn=sleeps.append)

    assert len(sleeps) == 1 and 0 < sleeps[0] <= fred.CSV_MIN_SECONDS_BETWEEN_REQUESTS


def test_api_path_used_when_key_present(monkeypatch):
    monkeypatch.setattr(fred.settings, "fred_api_key", "dummy-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.stlouisfed.org" in str(request.url)
        return httpx.Response(
            200,
            json={"observations": [{"date": "2026-08-01", "value": "1.900"}, {"date": "2026-07-01", "value": "."}, {"date": "2026-06-01", "value": "1.850"}]},
        )

    result = fred.fetch_observations("DFII10", client=_client(handler))

    assert result == [{"date": "2026-06-01", "value": 1.85}, {"date": "2026-08-01", "value": 1.9}]


def test_http_error_is_unavailable(monkeypatch):
    monkeypatch.setattr(fred.settings, "fred_api_key", "")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(fred.FredUnavailableError):
        fred.fetch_observations("DFII10", client=_client(handler), sleep_fn=lambda s: None)
