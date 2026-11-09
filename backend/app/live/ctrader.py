"""Purple Trading cTrader Open API (JSON over WebSocket) — live bid / ask of the user's own broker.

Read-only by construction: FTI sends only authentication, the symbol list and the spot subscription — never an order —
and the token's scope "accounts" (view only, help.ctrader.com/open-api/account-authentication) makes trading impossible
even in principle. Message numbers: ProtoOAPayloadType (help.ctrader.com/open-api/model-messages, checked 9. 11. 2026);
50 / 51 = error / heartbeat of the common messages.

Flow: application auth (client id + secret) → the token's accounts → account auth → symbol list (the broker's names are
looked up, the result is shown on the Data page) → spot subscription. A spot event carries only the side that changed,
prices × 100 000, the quote time in ms. An expired access token (30 days) is renewed with the refresh token and saved.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid

from app.live import providers
from app.live.providers import Provider, Tick

CT = {"APP_AUTH": 2100, "APP_AUTH_RES": 2101, "ACCOUNT_AUTH": 2102, "ACCOUNT_AUTH_RES": 2103, "SYMBOLS": 2114, "SYMBOLS_RES": 2115,
      "SUBSCRIBE_SPOTS": 2127, "SUBSCRIBE_SPOTS_RES": 2128, "SPOT": 2131, "OA_ERROR": 2142, "TOKEN_INVALIDATED": 2147,
      "CLIENT_DISCONNECT": 2148, "ACCOUNTS": 2149, "ACCOUNTS_RES": 2150, "REFRESH": 2173, "REFRESH_RES": 2174,
      "ACCOUNT_DISCONNECT": 2164, "ERROR": 50, "HEARTBEAT": 51}
PRICE = 100000.0
HOSTS = {"demo": "wss://demo.ctraderapi.com:5036", "live": "wss://live.ctraderapi.com:5036"}
# the broker's names of the instruments — the first that exists on the account is used and reported (Data page)
CANDIDATES = {"XAUUSD": ("XAUUSD", "GOLD", "XAUUSD.r", "XAUUSD_ecn"), "EURUSD": ("EURUSD", "EURUSD.r", "EURUSD_ecn"),
              "US500.CFD": ("US500", "US 500", "SPX500", "US500.cash", "US500_ecn", "USA500"),
              "US100.CFD": ("NAS100", "US100", "USTEC", "US Tech 100", "NDX100", "US100.cash", "US100_ecn", "USTECH")}
KEYS = ("CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_ACCESS_TOKEN")


class CTraderError(RuntimeError):
    def __init__(self, code: str, text: str):
        super().__init__(f"{code}: {text}")
        self.code = code


def configured() -> bool:
    from app.data import secrets

    return all(secrets.get(k) for k in KEYS)


def resolve_symbols(symbols: list[dict], codes: list[str]) -> dict[int, str]:
    """{symbolId: FTI code} from the account's symbol list — exact name first, then the same name in other case."""
    by_name = {str(s.get("symbolName") or ""): s for s in symbols if s.get("enabled", True)}
    lower = {k.lower(): v for k, v in by_name.items()}
    out = {}
    for code in codes:
        for cand in CANDIDATES.get(code, (code,)):
            s = by_name.get(cand) or lower.get(cand.lower())
            if s is not None:
                out[int(s["symbolId"])] = code
                break
    return out


class CTrader(Provider):
    name = "ctrader"

    def __init__(self, symbols: dict[str, str], host: str = "demo"):
        super().__init__(symbols)
        self.url = HOSTS[host]
        self.host = host
        self.ids: dict[int, tuple[str | None, str]] = {}  # symbolId → (broker's name, FTI code)
        self.last: dict[int, list] = {}  # symbolId → [bid, ask]
        self.account: int | None = None

    async def _call(self, ws, ptype: int, payload: dict, expect: int) -> dict:
        await ws.send(json.dumps({"clientMsgId": uuid.uuid4().hex, "payloadType": ptype, "payload": payload}))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 20))
            pt = msg.get("payloadType")
            if pt in (CT["OA_ERROR"], CT["ERROR"]):
                p = msg.get("payload") or {}
                raise CTraderError(str(p.get("errorCode")), str(p.get("description") or ""))
            if pt == expect:
                return msg.get("payload") or {}

    async def subscribe(self, ws) -> None:
        from app.data import secrets

        await self._call(ws, CT["APP_AUTH"], {"clientId": secrets.get("CTRADER_CLIENT_ID"),
                                               "clientSecret": secrets.get("CTRADER_CLIENT_SECRET")}, CT["APP_AUTH_RES"])
        try:
            accounts = await self._call(ws, CT["ACCOUNTS"], {"accessToken": secrets.get("CTRADER_ACCESS_TOKEN")}, CT["ACCOUNTS_RES"])
        except CTraderError as exc:
            if "TOKEN" not in exc.code.upper() and "AUTH" not in exc.code.upper():
                raise
            await self.refresh(ws)  # the access token expired: a new one with the refresh token, saved in FTI
            accounts = await self._call(ws, CT["ACCOUNTS"], {"accessToken": secrets.get("CTRADER_ACCESS_TOKEN")}, CT["ACCOUNTS_RES"])
        mine = [a for a in accounts.get("ctidTraderAccount") or [] if bool(a.get("isLive")) == (self.host == "live")]
        if not mine:
            raise CTraderError("NO_ACCOUNT", f"token nemá žádný {'živý' if self.host == 'live' else 'demo'} účet cTrader")
        self.account = int(mine[0]["ctidTraderAccountId"])
        await self._call(ws, CT["ACCOUNT_AUTH"], {"ctidTraderAccountId": self.account,
                                                   "accessToken": secrets.get("CTRADER_ACCESS_TOKEN")}, CT["ACCOUNT_AUTH_RES"])
        listed = await self._call(ws, CT["SYMBOLS"], {"ctidTraderAccountId": self.account}, CT["SYMBOLS_RES"])
        rows = listed.get("symbol") or []
        found = resolve_symbols(rows, list(self.symbols.values()))
        names = {int(s["symbolId"]): s.get("symbolName") for s in rows}
        self.ids = {sid: (names.get(sid), code) for sid, code in found.items()}
        missing = sorted(set(self.symbols.values()) - set(found.values()))
        kept = {k: v for k, v in self.metrics.notes.items() if k == "token"}  # the token note of this connection stays
        self.metrics.notes = {**kept, **{code: f"u brokera nenalezen (zkoušeno {', '.join(CANDIDATES.get(code, (code,)))})"
                                         for code in missing}}
        self.metrics.notes["symboly"] = ", ".join(f"{code} = {name}" for name, code in self.ids.values())
        if not self.ids:
            raise CTraderError("NO_SYMBOLS", "žádný z instrumentů FTI na účtu nenalezen")
        await self._call(ws, CT["SUBSCRIBE_SPOTS"], {"ctidTraderAccountId": self.account, "symbolId": list(self.ids)},
                         CT["SUBSCRIBE_SPOTS_RES"])

    async def refresh(self, ws) -> None:
        from app.data import secrets

        res = await self._call(ws, CT["REFRESH"], {"refreshToken": secrets.get("CTRADER_REFRESH_TOKEN")}, CT["REFRESH_RES"])
        secrets.set_key("CTRADER_ACCESS_TOKEN", res["accessToken"])
        if res.get("refreshToken"):
            secrets.set_key("CTRADER_REFRESH_TOKEN", res["refreshToken"])
        self.metrics.notes["token"] = "access token obnoven refresh tokenem"

    async def keepalive(self, ws, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(10)  # cTrader closes a connection that stays silent
            await ws.send(json.dumps({"payloadType": CT["HEARTBEAT"], "payload": {}}))

    def parse(self, msg: dict) -> list[Tick]:
        now = time.time()
        pt = msg.get("payloadType")
        p = msg.get("payload") or {}
        if pt in (CT["OA_ERROR"], CT["ERROR"]):
            self.metrics.error(f"{p.get('errorCode')}: {p.get('description')}")
            return []
        if pt in (CT["TOKEN_INVALIDATED"], CT["CLIENT_DISCONNECT"], CT["ACCOUNT_DISCONNECT"]):
            raise ConnectionError(f"cTrader ukončil spojení ({pt}): {p.get('reason') or ''}")
        if pt != CT["SPOT"]:
            return []
        sid = int(p.get("symbolId") or 0)
        if sid not in self.ids:
            return []
        last = self.last.setdefault(sid, [None, None])
        if p.get("bid") is not None:
            last[0] = int(p["bid"]) / PRICE
        if p.get("ask") is not None:
            last[1] = int(p["ask"]) / PRICE
        if last[0] is None or last[1] is None:
            return []  # a price is complete only with both sides
        ts = p.get("timestamp")
        name, code = self.ids[sid]
        return [Tick(code, self.name, name or str(sid), int(ts) / 1000 if ts else now, now, last[0], last[1], None,
                     "quote" if ts else "receive")]


providers.ADAPTERS["ctrader"] = CTrader
