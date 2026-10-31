"""BullionVault public market feed — a second, independent gold price.

https://www.bullionvault.com/view_market_xml.do — documented for programmers
at bullionvault.com/help/xml_api.html, no account, no key; robots.txt only
blocks some translated help pages. Checked live 2026-10-04.

Prices are best bid/offer for physical gold in a vault, in USD per kilogram.
We take the London vault (tightest spread) and convert the mid to $/oz.
Used only to cross-check the PAXG price the charts are built from.
"""

from __future__ import annotations

import re

import httpx

URL = "https://www.bullionvault.com/view_market_xml.do"
GRAMS_PER_TROY_OZ = 31.1034768
OZ_PER_KG = 1000 / GRAMS_PER_TROY_OZ  # 32.1507…
VAULTS = ("AUXLN", "AUXZU", "AUXNY")  # London first, then Zurich, New York

_PITCH = re.compile(r'<pitch\s+securityClassNarrative="GOLD"\s+securityId="(\w+)"\s+considerationCurrency="USD"\s*>(.*?)</pitch>', re.S)
_BUY = re.compile(r'actionIndicator="B"\s+quantity="[\d.]+"\s+limit="(\d+)"')
_SELL = re.compile(r'actionIndicator="S"\s+quantity="[\d.]+"\s+limit="(\d+)"')


class BullionVaultUnavailableError(RuntimeError):
    pass


def parse(xml: str) -> dict:
    books = {}
    for m in _PITCH.finditer(xml):
        b, s = _BUY.search(m.group(2)), _SELL.search(m.group(2))
        if b and s:
            books[m.group(1)] = (int(b.group(1)) / OZ_PER_KG, int(s.group(1)) / OZ_PER_KG)
    vault = next((v for v in VAULTS if v in books), None)
    if vault is None:
        raise BullionVaultUnavailableError("v odpovědi chybí kniha zlata v USD")
    bid, ask = books[vault]
    return {"vault": vault, "bid": round(bid, 2), "ask": round(ask, 2), "mid": round((bid + ask) / 2, 2)}


def fetch_gold_usd(client: httpx.Client | None = None) -> dict:
    owns = client is None
    client = client or httpx.Client(timeout=20.0)
    try:
        resp = client.get(URL)
        resp.raise_for_status()
        return parse(resp.text)
    except httpx.HTTPError as exc:
        raise BullionVaultUnavailableError(str(exc)) from exc
    finally:
        if owns:
            client.close()
