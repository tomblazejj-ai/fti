"""cTrader Open API sign-in (OAuth, read-only) for the app: status, start, callback. Tokens go to backend/.env only."""

from __future__ import annotations

import html

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.live import ctrader_oauth

router = APIRouter(prefix="/api/ctrader")


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@router.get("/status")
def status(request: Request):
    return ctrader_oauth.status(_base(request))


@router.get("/oauth/start")
def oauth_start(request: Request):
    try:
        return RedirectResponse(ctrader_oauth.start(_base(request)), status_code=302)
    except ctrader_oauth.OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/oauth/callback", response_class=HTMLResponse)
def oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        ok, text = False, f"cTrader přihlášení nepovolil ({error})."
    else:
        try:
            r = ctrader_oauth.finish(code, state, _base(request))
            ok, text = True, f"cTrader je připojený jen pro čtení (rozsah {r['scope']}). Přístup platí asi {r['expires_in_days']} dní, FTI ho pak obnoví samo."
        except ctrader_oauth.OAuthError as exc:
            ok, text = False, str(exc)
    title = "Hotovo" if ok else "Nepovedlo se"
    page = f"""<!doctype html><html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FTI – cTrader</title></head><body style="font-family:system-ui,sans-serif;max-width:40rem;margin:3rem auto;padding:0 1rem">
<h1>{title}</h1><p>{html.escape(text)}</p><p><a href="/#/data">Zpět na Zdroje dat</a></p></body></html>"""
    return HTMLResponse(page, status_code=200 if ok else 400)
