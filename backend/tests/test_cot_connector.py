import httpx
import pytest

from app.connectors import cot


def _mock_client(rows):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_latest_two_gold_reports_computes_net_positioning():
    rows = [
        {
            "report_date_as_yyyy_mm_dd": "2026-09-22T00:00:00.000",
            "noncomm_positions_long_all": "253982",
            "noncomm_positions_short_all": "28129",
        },
        {
            "report_date_as_yyyy_mm_dd": "2026-09-15T00:00:00.000",
            "noncomm_positions_long_all": "258000",
            "noncomm_positions_short_all": "27500",
        },
    ]
    client = _mock_client(rows)

    result = cot.fetch_latest_two_gold_reports(client=client)

    assert result == [
        {"date": "2026-09-15", "net_noncommercial_long": 230500.0},
        {"date": "2026-09-22", "net_noncommercial_long": 225853.0},
    ]


def test_fetch_latest_two_gold_reports_raises_on_too_few_rows():
    client = _mock_client([{"report_date_as_yyyy_mm_dd": "2026-09-22T00:00:00.000"}])
    with pytest.raises(cot.CotUnavailableError):
        cot.fetch_latest_two_gold_reports(client=client)


def test_fetch_latest_two_gold_reports_raises_on_malformed_row():
    rows = [
        {"report_date_as_yyyy_mm_dd": "2026-09-22T00:00:00.000", "noncomm_positions_long_all": "x"},
        {"report_date_as_yyyy_mm_dd": "2026-09-15T00:00:00.000", "noncomm_positions_long_all": "y"},
    ]
    client = _mock_client(rows)
    with pytest.raises(cot.CotUnavailableError):
        cot.fetch_latest_two_gold_reports(client=client)


def test_fetch_latest_two_gold_reports_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(cot.CotUnavailableError):
        cot.fetch_latest_two_gold_reports(client=client)
