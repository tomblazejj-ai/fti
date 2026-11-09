"""cTrader Open API sign-in in the browser (OAuth 2.0 authorization code) — READ-ONLY.

Flow (help.ctrader.com/open-api/account-authentication, checked 9. 11. 2026):
  1. FTI sends the user to id.ctrader.com/my/settings/openapi/grantingaccess/ with client_id, redirect_uri,
     scope=accounts (view only — FTI never asks for "trading") and product=web, plus a one-time `state`.
  2. cTrader sends the user back to redirect_uri?code=… (the code lives one minute).
  3. FTI exchanges the code at openapi.ctrader.com/apps/token (grant_type=authorization_code) and stores the access
     token (~30 days) and the refresh token (no expiry) in backend/.env through app/data/secrets — never in the database,
     the frontend, a log or GitHub. The live adapter renews the access token with ProtoOARefreshTokenReq.

The redirect URI comes from configuration (env FTI_CTRADER_REDIRECT_URI, settings ctrader.redirect_uri) or from the
address the app is opened at — nothing is tied to one host (a custom domain later works the same). The same URI must be
listed in the app's Redirect URIs in openapi.ctrader.com. Until the app is Active, cTrader refuses the sign-in: the flow
is ready, not verified against the live service.
"""

from __future__ import annotations

import os
import secrets as pysecrets
import time
import urllib.parse

import httpx

from app.data import secrets, settings_store

AUTH_URL = "https://id.ctrader.com/my/settings/openapi/grantingaccess/"
TOKEN_URL = "https://openapi.ctrader.com/apps/token"
SCOPE = "accounts"  # view only. "trading" would allow orders — FTI never asks for it.
CALLBACK_PATH = "/api/ctrader/oauth/callback"
STATE_TTL_S = 600
_states: dict[str, float] = {}


class OAuthError(RuntimeError):
    """A sign-in that did not work, said in Czech — never with a key, token or the token URL in the text."""


def redirect_uri(base_url: str | None = None) -> str | None:
    """The configured redirect URI, else the callback on the address the app was opened at."""
    configured = os.environ.get("FTI_CTRADER_REDIRECT_URI") or (settings_store.get("ctrader", {}) or {}).get("redirect_uri")
    if configured:
        return str(configured)
    return base_url.rstrip("/") + CALLBACK_PATH if base_url else None


def status(base_url: str | None = None) -> dict:
    """What is set (yes / no only — values never leave the backend) and what to enter in the cTrader portal."""
    have = {k: bool(secrets.get(k)) for k in ("CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_ACCESS_TOKEN", "CTRADER_REFRESH_TOKEN")}
    return {
        "client_id": have["CTRADER_CLIENT_ID"],
        "client_secret": have["CTRADER_CLIENT_SECRET"],
        "access_token": have["CTRADER_ACCESS_TOKEN"],
        "refresh_token": have["CTRADER_REFRESH_TOKEN"],
        "scope": SCOPE,
        "redirect_uri": redirect_uri(base_url),
        "ready_to_sign_in": have["CTRADER_CLIENT_ID"] and have["CTRADER_CLIENT_SECRET"],
        "note": "Přihlášení funguje až ve chvíli, kdy je aplikace FTI v portálu cTrader ve stavu Active (Submitted nestačí).",
    }


def start(base_url: str | None, now: float | None = None) -> str:
    """The cTrader consent page to send the user to (one-time state against forged returns)."""
    client_id = secrets.get("CTRADER_CLIENT_ID")
    if not client_id:
        raise OAuthError("Chybí Client ID aplikace cTrader — zadej ho na stránce Zdroje dat.")
    uri = redirect_uri(base_url)
    if not uri:
        raise OAuthError("Návratová adresa pro cTrader není nastavená.")
    now = now or time.time()
    for k, t in list(_states.items()):
        if now - t > STATE_TTL_S:
            _states.pop(k, None)
    state = pysecrets.token_urlsafe(24)
    _states[state] = now
    query = urllib.parse.urlencode({"client_id": client_id, "redirect_uri": uri, "scope": SCOPE, "product": "web", "state": state})
    return f"{AUTH_URL}?{query}"


def finish(code: str, state: str, base_url: str | None, client: httpx.Client | None = None, now: float | None = None) -> dict:
    """Exchange the one-minute code for tokens and store them; returns only what may be shown (no token)."""
    now = now or time.time()
    issued = _states.pop(state or "", None)
    if issued is None or now - issued > STATE_TTL_S:
        raise OAuthError("Přihlášení vypršelo nebo nepochází z FTI — začni znovu tlačítkem Přihlásit cTrader.")
    if not code:
        raise OAuthError("cTrader nevrátil autorizační kód (přihlášení bylo zrušeno?).")
    params = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(base_url) or "",
              "client_id": secrets.get("CTRADER_CLIENT_ID"), "client_secret": secrets.get("CTRADER_CLIENT_SECRET")}
    own = client is None
    client = client or httpx.Client(timeout=20)
    try:
        resp = client.get(TOKEN_URL, params=params, headers={"Accept": "application/json"})
        body = resp.json()
    except (httpx.HTTPError, ValueError):
        # the request URL carries the client secret (cTrader's design): the error text is never passed on
        raise OAuthError("cTrader teď na výměnu kódu neodpověděl — zkus to znovu za chvíli.") from None
    finally:
        if own:
            client.close()
    if body.get("errorCode") or not body.get("accessToken"):
        raise OAuthError(f"cTrader přihlášení odmítl: {body.get('errorCode') or 'bez tokenu'} {body.get('description') or ''}".strip())
    secrets.set_key("CTRADER_ACCESS_TOKEN", str(body["accessToken"]))
    if body.get("refreshToken"):
        secrets.set_key("CTRADER_REFRESH_TOKEN", str(body["refreshToken"]))
    return {"ok": True, "expires_in_days": round(int(body.get("expiresIn") or 0) / 86400, 1), "scope": SCOPE}
