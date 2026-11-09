"""Phase 2 (master spec): cTrader sign-in in the browser (OAuth, read-only scope) and history (trendbars, ticks) with
the provider's limits, a queue, retries with exponential backoff, decoding and paging — against a fake server: the app
is Submitted, nothing here claims the live service works."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.data import secrets
from app.live import ctrader_history as ch
from app.live import ctrader_oauth as oauth
from app.live.ctrader import CT, CTrader

KEYS = {"CTRADER_CLIENT_ID": "1234_abcdefgh", "CTRADER_CLIENT_SECRET": "very-secret-value", "CTRADER_ACCESS_TOKEN": "tok",
        "CTRADER_REFRESH_TOKEN": "ref"}
READ_ONLY = {CT["APP_AUTH"], CT["ACCOUNTS"], CT["REFRESH"], CT["ACCOUNT_AUTH"], CT["SYMBOLS"], ch.HIST["TRENDBARS"],
             ch.HIST["TICKDATA"], ch.HIST["SYMBOL_BY_ID"]}


@pytest.fixture()
def keys(monkeypatch):
    store = dict(KEYS)
    monkeypatch.setattr(secrets, "get", lambda name: store.get(name, ""))
    monkeypatch.setattr(secrets, "set_key", lambda name, value: store.__setitem__(name, value))
    monkeypatch.delenv("FTI_CTRADER_REDIRECT_URI", raising=False)
    oauth._states.clear()
    return store


# --- OAuth ------------------------------------------------------------------------------------------------------------

def test_sign_in_asks_only_for_the_read_only_scope_with_a_one_time_state(keys):
    url = oauth.start("https://fti.example.org")
    q = dict(httpx.URL(url).params)
    assert url.startswith("https://id.ctrader.com/my/settings/openapi/grantingaccess/")
    assert q["scope"] == "accounts" and "trading" not in url
    assert q["client_id"] == "1234_abcdefgh" and q["product"] == "web"
    assert q["redirect_uri"] == "https://fti.example.org/api/ctrader/oauth/callback"  # from the address, not a fixed host
    assert q["state"] in oauth._states
    assert "very-secret-value" not in url


def test_redirect_uri_comes_from_configuration_first(keys, monkeypatch):
    from app.data import settings_store

    settings_store.update({"ctrader": {"redirect_uri": "https://moje-domena.cz/api/ctrader/oauth/callback"}})
    assert oauth.redirect_uri("http://127.0.0.1:8000") == "https://moje-domena.cz/api/ctrader/oauth/callback"
    monkeypatch.setenv("FTI_CTRADER_REDIRECT_URI", "https://jina.cz/cb")
    assert oauth.redirect_uri("http://127.0.0.1:8000") == "https://jina.cz/cb"


def test_without_client_id_there_is_no_sign_in(keys):
    keys["CTRADER_CLIENT_ID"] = ""
    with pytest.raises(oauth.OAuthError, match="Client ID"):
        oauth.start("http://127.0.0.1:8000")


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_the_code_is_exchanged_and_the_tokens_are_stored_never_returned(keys):
    seen = {}

    def handler(req):
        seen.update(dict(req.url.params))
        return httpx.Response(200, json={"accessToken": "new-access", "tokenType": "bearer", "expiresIn": 2628000,
                                         "refreshToken": "new-refresh", "errorCode": None, "description": None})

    url = oauth.start("http://127.0.0.1:8000")
    state = dict(httpx.URL(url).params)["state"]
    r = oauth.finish("abc", state, "http://127.0.0.1:8000", client=_client(handler))
    assert r == {"ok": True, "expires_in_days": 30.4, "scope": "accounts"}
    assert seen["grant_type"] == "authorization_code" and seen["code"] == "abc"
    assert seen["redirect_uri"] == "http://127.0.0.1:8000/api/ctrader/oauth/callback"
    assert keys["CTRADER_ACCESS_TOKEN"] == "new-access" and keys["CTRADER_REFRESH_TOKEN"] == "new-refresh"
    with pytest.raises(oauth.OAuthError, match="vypršelo"):  # a state works once
        oauth.finish("abc", state, "http://127.0.0.1:8000", client=_client(handler))


def test_a_failed_exchange_never_shows_the_secret(keys):
    def boom(req):
        raise httpx.ConnectError(f"cannot reach {req.url}")  # the URL carries the client secret

    state = dict(httpx.URL(oauth.start("http://x.test")).params)["state"]
    with pytest.raises(oauth.OAuthError) as exc:
        oauth.finish("abc", state, "http://x.test", client=_client(boom))
    assert "very-secret-value" not in str(exc.value) and exc.value.__cause__ is None
    state = dict(httpx.URL(oauth.start("http://x.test")).params)["state"]
    refused = _client(lambda req: httpx.Response(200, json={"errorCode": "ACCESS_DENIED", "description": "app not active"}))
    with pytest.raises(oauth.OAuthError, match="ACCESS_DENIED app not active"):
        oauth.finish("abc", state, "http://x.test", client=refused)
    assert keys["CTRADER_ACCESS_TOKEN"] == "tok"  # nothing stored on a refusal


def test_status_and_callback_routes_show_only_yes_or_no(keys):
    from app.main import app

    with TestClient(app) as c:
        s = c.get("/api/ctrader/status").json()
        assert s["client_secret"] is True and s["scope"] == "accounts" and "Active" in s["note"]
        assert "very-secret-value" not in json.dumps(s) and "tok" not in json.dumps([v for k, v in s.items() if k != "note"])
        start = c.get("/api/ctrader/oauth/start", follow_redirects=False)
        assert start.status_code == 302 and "scope=accounts" in start.headers["location"]
        bad = c.get("/api/ctrader/oauth/callback?code=x&state=forged")
        assert bad.status_code == 400 and "nepochází z FTI" in bad.text
        denied = c.get("/api/ctrader/oauth/callback?error=access_denied")
        assert denied.status_code == 400 and "nepovolil" in denied.text


# --- limits, retries, decoding --------------------------------------------------------------------------------------

def test_the_limiter_never_lets_more_than_n_requests_into_one_second():
    t = [0.0]
    times = []

    async def sleep(s):
        t[0] += s

    async def run():
        lim = ch.RateLimiter(5, clock=lambda: t[0], sleep=sleep)
        for _ in range(12):
            await lim.acquire()
            times.append(t[0])

    asyncio.run(run())
    for i, x in enumerate(times):
        assert sum(1 for y in times if x <= y < x + 1.0) <= 5, i
    assert times[-1] >= 2.0  # 12 history requests at 5/s take more than two seconds


def test_limits_can_only_be_lowered(monkeypatch):
    from app.data import settings_store

    settings_store.update({"ctrader": {"limits": {"history": 2, "general": 500}}})
    assert ch.limits() == {"general": 50, "history": 2}


def test_backoff_doubles_up_to_a_minute_with_jitter():
    assert [ch.backoff(a, rnd=lambda: 0.5) for a in range(8)] == [1, 2, 4, 8, 16, 32, 60, 60]
    assert ch.backoff(0, rnd=lambda: 0.0) == 0.75 and ch.backoff(0, rnd=lambda: 1.0) == 1.25


def test_trendbars_and_ticks_are_decoded():
    tb = {"low": 409000000, "deltaOpen": 50000, "deltaHigh": 120000, "deltaClose": 80000, "volume": 321,
          "utcTimestampInMinutes": 29903400}
    assert ch.decode_trendbar(tb) == (29903400 * 60, 4090.5, 4091.2, 4090.0, 4090.8, 321.0)
    # newest first: absolute, then differences (back in time)
    rows = [{"timestamp": 1794200003000, "tick": 409012000}, {"timestamp": -1000, "tick": -500}, {"timestamp": -2000, "tick": 300}]
    assert ch.decode_ticks(rows) == [(1794200000000, 4090.118), (1794200002000, 4090.115), (1794200003000, 4090.12)]


# --- the history client against a fake server ----------------------------------------------------------------------

SYMBOLS = [{"symbolId": 41, "symbolName": "XAUUSD", "enabled": True}, {"symbolId": 1, "symbolName": "EURUSD", "enabled": True}]
END = 29903333 * 60000  # a whole minute (Unix ms)


class FakeServer:
    def __init__(self):
        self.sent, self.queue, self.trendbar_calls = [], [], 0

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        pt, p = msg["payloadType"], msg.get("payload") or {}
        ans = None
        if pt == CT["APP_AUTH"]:
            ans = (CT["APP_AUTH_RES"], {})
        elif pt == CT["ACCOUNTS"]:
            ans = (CT["ACCOUNTS_RES"], {"ctidTraderAccount": [{"ctidTraderAccountId": 777, "isLive": False}]})
        elif pt == CT["ACCOUNT_AUTH"]:
            ans = (CT["ACCOUNT_AUTH_RES"], {})
        elif pt == CT["SYMBOLS"]:
            ans = (CT["SYMBOLS_RES"], {"symbol": SYMBOLS})
        elif pt == ch.HIST["TRENDBARS"]:
            self.trendbar_calls += 1
            if self.trendbar_calls == 1:  # the first one is refused for frequency, the retry goes through
                ans = (CT["OA_ERROR"], {"errorCode": "REQUEST_FREQUENCY_EXCEEDED", "description": "slow down"})
            else:
                end_min = p["toTimestamp"] // 60000
                bars = [{"low": 100000 * 4090, "deltaOpen": 0, "deltaHigh": 100, "deltaClose": 50, "volume": 1,
                         "utcTimestampInMinutes": end_min - k} for k in range(1, 4)]
                ans = (ch.HIST["TRENDBARS_RES"], {"trendbar": bars, "hasMore": end_min > p["fromTimestamp"] // 60000 + 3,
                                                   "period": p["period"]})
        elif pt == ch.HIST["TICKDATA"]:
            ans = (ch.HIST["TICKDATA_RES"], {"tickData": [{"timestamp": p["toTimestamp"] - 10, "tick": 409000000},
                                                          {"timestamp": -100, "tick": 1000}], "hasMore": False})
        if ans:
            self.queue.append(json.dumps({"payloadType": CT["HEARTBEAT"], "payload": {}}))
            self.queue.append(json.dumps({"clientMsgId": msg.get("clientMsgId"), "payloadType": ans[0], "payload": ans[1]}))

    async def recv(self):
        return self.queue.pop(0)

    async def close(self):
        pass


def test_history_pages_back_retries_a_frequency_refusal_and_sends_nothing_that_trades(keys, monkeypatch, tmp_path):
    monkeypatch.setattr(ch, "CACHE_DIR", tmp_path)
    server = FakeServer()
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    async def connect(url):
        return server

    async def run():
        async with ch.HistoryClient(connect=connect, sleep=fake_sleep, rnd=lambda: 0.5, now=lambda: 1794300000) as c:
            bars = await c.trendbars("XAUUSD", "M1", END - 6 * 60000, END)
            ticks = await c.ticks("XAUUSD", "bid", 1794199000000, 1794200000000)
            return c, bars, ticks

    c, bars, ticks = asyncio.run(run())
    assert [b[0] for b in bars] == [END // 1000 - 60 * k for k in range(6, 0, -1)]  # two pages, oldest first, no doubles
    assert bars[0][1:5] == (4090.0, 4090.001, 4090.0, 4090.0005)
    assert ticks == [(1794199999890, 4090.01), (1794199999990, 4090.0)]  # newest first on the wire, oldest first here
    assert c.requests["retries"] == 1 and 1.0 in slept  # the refused request waited 1 s and went again
    assert {m["payloadType"] for m in server.sent} <= READ_ONLY | {CT["HEARTBEAT"]}
    assert all(m["payloadType"] != CT["SUBSCRIBE_SPOTS"] for m in server.sent)
    # a finished range is cached: asked again, nothing goes to the server
    sent = len(server.sent)

    async def again():
        async with ch.HistoryClient(connect=connect, sleep=fake_sleep, now=lambda: 1794300000) as c2:
            return await c2.trendbars("XAUUSD", "M1", END - 6 * 60000, END)

    assert asyncio.run(again()) == bars
    assert all(m["payloadType"] != ch.HIST["TRENDBARS"] for m in server.sent[sent:])


def test_every_timeframe_m1_to_mn1_has_a_ctrader_period():
    assert list(ch.PERIOD) == ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
    assert ch.PERIOD["MN1"] == 14 and ch.PERIOD["W1"] == 13 and ch.PERIOD["M15"] == 7


# --- a live stream that stops ---------------------------------------------------------------------------------------

def test_a_stream_that_only_sends_heartbeats_while_the_market_is_open_is_reconnected(monkeypatch):
    from app.data import market_hours

    from app.live import ctrader

    a = CTrader({"XAUUSD": "XAUUSD"})
    a.ids = {41: ("XAUUSD", "XAUUSD")}
    a.last_spot = 1000.0
    clock = [1000.0 + 60]
    monkeypatch.setattr(ctrader.time, "time", lambda: clock[0])
    monkeypatch.setattr(market_hours, "state", lambda inst, now=None: {"state": market_hours.OPEN})
    heartbeat = {"payloadType": CT["HEARTBEAT"], "payload": {}}
    assert a.parse(heartbeat) == []  # a minute without a price: still fine
    clock[0] = 1000.0 + ctrader.STALL_S + 1
    with pytest.raises(ConnectionError, match="ceny nechodí"):
        a.parse(heartbeat)  # heartbeats keep coming, prices do not, the market is open → reconnect
    assert "ceny nechodí" in a.metrics.errors[-1]["error"]
    a.parse({"payloadType": CT["SPOT"], "payload": {"symbolId": 41, "bid": 409000000, "ask": 409050000}})
    assert a.last_spot == clock[0] and a.parse(heartbeat) == []  # a price resets the watch
    monkeypatch.setattr(market_hours, "state", lambda inst, now=None: {"state": market_hours.CLOSED})
    assert a.stalled(clock[0] + 10_000) is False  # closed market: silence is normal
