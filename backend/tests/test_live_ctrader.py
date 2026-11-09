"""Purple Trading cTrader Open API adapter (9. 11. 2026): the handshake (application → the token's demo account →
account → the broker's symbol names → spot subscription), an expired token renewed and saved, spot events with only
the changed side, disconnect events — and FTI sends nothing but authentication, the symbol list, the subscription
and heartbeats: never an order. With the user's keys the broker is primary and Deriv a backup."""

import asyncio
import json

import pytest

from app.data import secrets
from app.live import ctrader, instruments
from app.live.ctrader import CT, CTrader

REAL_GET = secrets.get  # conftest blanks every key in tests; this test checks the real reading
READ_ONLY = {CT["APP_AUTH"], CT["ACCOUNTS"], CT["REFRESH"], CT["ACCOUNT_AUTH"], CT["SYMBOLS"], CT["SUBSCRIBE_SPOTS"], CT["HEARTBEAT"]}
SYMBOLS = [{"symbolId": 41, "symbolName": "XAUUSD", "enabled": True}, {"symbolId": 1, "symbolName": "EURUSD", "enabled": True},
           {"symbolId": 10, "symbolName": "US500", "enabled": True}, {"symbolId": 11, "symbolName": "USTEC", "enabled": True},
           {"symbolId": 2, "symbolName": "GBPUSD", "enabled": True}]


class FakeWS:
    """A cTrader server in a box: every request gets its scripted answer."""

    def __init__(self, token_expired=False):
        self.sent, self.queue, self.token_expired = [], [], token_expired

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        pt, p = msg["payloadType"], msg.get("payload") or {}
        answer = {
            CT["APP_AUTH"]: (CT["APP_AUTH_RES"], {}),
            CT["ACCOUNTS"]: ((CT["OA_ERROR"], {"errorCode": "CH_ACCESS_TOKEN_INVALID", "description": "expired"})
                             if self.token_expired and p.get("accessToken") == "old-token" else
                             (CT["ACCOUNTS_RES"], {"ctidTraderAccount": [{"ctidTraderAccountId": 900, "isLive": True},
                                                                         {"ctidTraderAccountId": 777, "isLive": False}]})),
            CT["REFRESH"]: (CT["REFRESH_RES"], {"accessToken": "new-token", "refreshToken": "new-refresh", "expiresIn": 2628000}),
            CT["ACCOUNT_AUTH"]: (CT["ACCOUNT_AUTH_RES"], {"ctidTraderAccountId": p.get("ctidTraderAccountId")}),
            CT["SYMBOLS"]: (CT["SYMBOLS_RES"], {"symbol": SYMBOLS}),
            CT["SUBSCRIBE_SPOTS"]: (CT["SUBSCRIBE_SPOTS_RES"], {}),
        }.get(pt)
        if answer:
            self.queue.append(json.dumps({"payloadType": CT["HEARTBEAT"], "payload": {}}))  # heartbeats come in between
            self.queue.append(json.dumps({"clientMsgId": msg.get("clientMsgId"), "payloadType": answer[0], "payload": answer[1]}))

    async def recv(self):
        return self.queue.pop(0)


@pytest.fixture()
def keys(monkeypatch):
    store = {"CTRADER_CLIENT_ID": "1234_abcdefgh", "CTRADER_CLIENT_SECRET": "secretsecret", "CTRADER_ACCESS_TOKEN": "old-token",
             "CTRADER_REFRESH_TOKEN": "old-refresh"}
    monkeypatch.setattr(secrets, "get", lambda name: store.get(name, ""))
    monkeypatch.setattr(secrets, "set_key", lambda name, value: store.__setitem__(name, value))
    return store


def _adapter():
    return CTrader({c: c for c in ("XAUUSD", "EURUSD", "US500.CFD", "US100.CFD")})


def test_handshake_finds_the_demo_account_and_the_brokers_names(keys):
    a, ws = _adapter(), FakeWS()
    asyncio.run(a.subscribe(ws))
    assert a.account == 777  # the demo account, not the live one
    assert {code for _, code in a.ids.values()} == {"XAUUSD", "EURUSD", "US500.CFD", "US100.CFD"}
    assert "US100.CFD = USTEC" in a.metrics.notes["symboly"]  # the broker's name is reported, not guessed silently
    sub = next(m for m in ws.sent if m["payloadType"] == CT["SUBSCRIBE_SPOTS"])
    assert sorted(sub["payload"]["symbolId"]) == [1, 10, 11, 41] and sub["payload"]["ctidTraderAccountId"] == 777
    assert {m["payloadType"] for m in ws.sent} <= READ_ONLY  # never an order


def test_an_expired_token_is_renewed_and_saved(keys):
    a, ws = _adapter(), FakeWS(token_expired=True)
    asyncio.run(a.subscribe(ws))
    assert keys["CTRADER_ACCESS_TOKEN"] == "new-token" and keys["CTRADER_REFRESH_TOKEN"] == "new-refresh"
    assert [m["payloadType"] for m in ws.sent][:4] == [CT["APP_AUTH"], CT["ACCOUNTS"], CT["REFRESH"], CT["ACCOUNTS"]]
    assert a.account == 777 and "obnoven" in a.metrics.notes["token"]


def test_a_missing_instrument_is_said_and_the_rest_streams(keys, monkeypatch):
    monkeypatch.setattr(ctrader, "CANDIDATES", {**ctrader.CANDIDATES, "US100.CFD": ("NAS100",)})
    a = _adapter()
    asyncio.run(a.subscribe(FakeWS()))
    assert "nenalezen" in a.metrics.notes["US100.CFD"] and len(a.ids) == 3


def test_spot_events_carry_only_the_changed_side(keys):
    a = _adapter()
    asyncio.run(a.subscribe(FakeWS()))
    assert a.parse({"payloadType": CT["SPOT"], "payload": {"symbolId": 41, "bid": 409612000}}) == []  # no ask yet
    t = a.parse({"payloadType": CT["SPOT"], "payload": {"symbolId": 41, "ask": 409640000, "timestamp": 1794218000123}})[0]
    assert (t.code, t.bid, t.ask, t.t, t.time_basis) == ("XAUUSD", 4096.12, 4096.4, 1794218000.123, "quote")
    t = a.parse({"payloadType": CT["SPOT"], "payload": {"symbolId": 41, "bid": 409615000}})[0]
    assert (t.bid, t.ask, t.time_basis) == (4096.15, 4096.4, "receive")  # the ask kept; no time given → receive time, said
    assert a.parse({"payloadType": CT["SPOT"], "payload": {"symbolId": 2, "bid": 1, "ask": 2}}) == []  # not subscribed
    with pytest.raises(ConnectionError):
        a.parse({"payloadType": CT["TOKEN_INVALIDATED"], "payload": {"reason": "revoked"}})


def test_with_the_users_keys_the_broker_is_primary_and_deriv_a_checked_backup(keys, monkeypatch):
    assert instruments.build(False) == instruments.INSTRUMENTS
    built = {i.code: i for i in instruments.build(True)}
    for code, inst in built.items():
        assert inst.feeds[0].provider == "ctrader" and inst.feeds[0].price_type == "bid" and "Purple" in inst.feeds[0].product
        assert [f.role for f in inst.feeds if f.provider == "deriv"] == ["backup"]
    assert built["US500.CFD"].feeds[1].sessions_utc == (6, 21)  # Deriv's session still limits the backup
    assert ctrader.configured() and instruments.current()[0].feeds[0].provider == "ctrader"
    keys["CTRADER_ACCESS_TOKEN"] = ""
    assert not ctrader.configured() and instruments.current()[0].feeds[0].provider == "deriv"


def test_capital_keys_have_their_own_checked_format(monkeypatch, tmp_path):
    """Capital.com needs the account's login e-mail (sent only to Capital.com) and the API key's own password."""
    monkeypatch.setattr(secrets, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(secrets, "get", REAL_GET)
    secrets.set_key("CAPITAL_IDENTIFIER", "jmeno.prijmeni@example.cz")
    secrets.set_key("CAPITAL_API_PASSWORD", "Abc!x9$z")
    assert "CAPITAL_IDENTIFIER=jmeno.prijmeni@example.cz" in (tmp_path / ".env").read_text(encoding="utf-8")
    for name, bad in (("CAPITAL_IDENTIFIER", "bez zavinace"), ("CAPITAL_API_PASSWORD", "ma mezeru"), ("CAPITAL_API_PASSWORD", "abc")):
        with pytest.raises(ValueError):
            secrets.set_key(name, bad)
    shown = {k["name"]: k for k in secrets.status()}
    assert shown["CAPITAL_IDENTIFIER"]["set"] and shown["CAPITAL_IDENTIFIER"]["hint"] is None  # never shown back
