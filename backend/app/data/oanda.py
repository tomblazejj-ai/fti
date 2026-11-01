"""OANDA v20 REST API as a data source (candles only, read-only).

Needs the user's own API token (free with an OANDA practice account) in backend/.env as
OANDA_API_TOKEN. OFF until that token exists. The data are OANDA's broker quotes — the same
feed TradingView shows as "OANDA:XAUUSD". Volume is OANDA's tick volume, not market volume.
"""

from __future__ import annotations

import datetime as dt

import httpx

from app.data import secrets, settings_store

HOSTS = {"practice": "https://api-fxpractice.oanda.com", "live": "https://api-fxtrade.oanda.com"}
GRANULARITY = {"M1": "M1", "M5": "M5", "M15": "M15", "M30": "M30", "H1": "H1", "H4": "H4", "D1": "D", "W1": "W", "MN1": "M"}


class OandaUnavailable(RuntimeError):
    pass


def token() -> str:
    return secrets.get("OANDA_API_TOKEN")


def fetch_bars(instrument: str, tf: str, count: int = 1000, client: httpx.Client | None = None) -> tuple[list[tuple], dict]:
    tok = token()
    if not tok:
        raise OandaUnavailable("Token OANDA není nastaven (Nastavení → klíče).")
    env = (settings_store.get("oanda.environment") or "practice")
    host = HOSTS.get(env, HOSTS["practice"])
    gran = GRANULARITY.get(tf)
    if not gran:
        raise OandaUnavailable(f"Timeframe {tf} OANDA nezná.")
    owns = client is None
    client = client or httpx.Client(timeout=20.0)
    try:
        resp = client.get(f"{host}/v3/instruments/{instrument}/candles",
                          params={"granularity": gran, "count": min(count, 5000), "price": "M"},
                          headers={"Authorization": f"Bearer {tok}", "Accept-Datetime-Format": "UNIX"})
        if resp.status_code in (401, 403):
            raise OandaUnavailable("OANDA odmítla token (neplatný nebo pro jiné prostředí).")
        resp.raise_for_status()
        body = resp.json()
    except httpx.HTTPError as exc:
        raise OandaUnavailable(f"OANDA {instrument} {tf}: {exc}") from exc
    finally:
        if owns:
            client.close()
    bars = []
    for c in body.get("candles", []):
        mid = c.get("mid") or {}
        try:
            t = float(c["time"]) if str(c["time"]).replace(".", "", 1).isdigit() else \
                dt.datetime.fromisoformat(str(c["time"]).replace("Z", "+00:00")).timestamp()
            bars.append((int(t), float(mid["o"]), float(mid["h"]), float(mid["l"]), float(mid["c"]), float(c.get("volume", 0))))
        except (KeyError, ValueError, TypeError):
            continue
    if not bars:
        raise OandaUnavailable(f"OANDA nevrátila svíčky pro {instrument}.")
    return bars, {"symbol": instrument, "broker": "OANDA", "server": env, "volume": "tick volume OANDA (ne celkový objem trhu)"}
