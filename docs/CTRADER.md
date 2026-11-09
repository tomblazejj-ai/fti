# cTrader Open API (Purple Trading demo) v FTI

Stav k 9. 11. 2026: **připraveno, proti živému API neověřeno** — aplikace FTI v portálu openapi.ctrader.com je ve stavu
*Submitted*; přihlášení, sandbox i data jdou až ve stavu *Active* (KYC obvykle do 3 pracovních dnů).

## Co FTI dělá (jen čtení)

| Část | Soubor | Co |
|---|---|---|
| Přihlášení v prohlížeči (OAuth 2.0) | `backend/app/live/ctrader_oauth.py`, `api/routes_ctrader.py` | `id.ctrader.com/my/settings/openapi/grantingaccess/` s `scope=accounts` (jen prohlížení, nikdy `trading`) a jednorázovým `state`; výměna kódu na `openapi.ctrader.com/apps/token`; tokeny jen do `backend/.env` |
| Živé ceny | `backend/app/live/ctrader.py` | přihlášení aplikace → demo účet z tokenu → účet → názvy symbolů brokera → odběr spotů; heartbeat 10 s; obnova access tokenu refresh tokenem; znovupřipojení 1–60 s; **hlídání zaseknutého streamu**: přicházejí jen heartbeaty a ceny ne déle než 180 s, zatímco je trh otevřený → nové spojení |
| Historie | `backend/app/live/ctrader_history.py` | trendbary M1–MN1 (ProtoOAGetTrendbarsReq 2137), ticky bid a ask zvlášť (ProtoOAGetTickDataReq 2145), detail symbolu (2116); stránkování přes `hasMore`; hotové úseky v mezipaměti `backend/cache/ctrader/` |
| Limity | tamtéž | 50 požadavků/s běžných, 5 požadavků/s historických na spojení (cTrader) — vlastní omezovač pod limitem, historické dotazy jeden po druhém z fronty, při `REQUEST_FREQUENCY_EXCEEDED` (108), timeoutu nebo výpadku opakování s exponenciálním čekáním 1, 2, 4 … 60 s ± 25 %; v nastavení `ctrader.limits` jde limity jen snížit |

FTI nikdy neposílá zprávu, která by obchodovala (testy kontrolují seznam odeslaných typů zpráv).

## Co je potřeba od uživatele

1. Client ID a Client Secret zadat na stránce **Zdroje dat** (klíče `CTRADER_CLIENT_ID`, `CTRADER_CLIENT_SECRET`) — uloží
   se jen do `backend/.env` (v `.gitignore`); TXT s kopií Secretu pak smazat.
2. V portálu do *Redirect URIs* aplikace zapsat návratovou adresu, kterou ukazuje karta cTrader na stránce Zdroje dat
   (na PC `http://127.0.0.1:8000/api/ctrader/oauth/callback`; s vlastní doménou se nastaví `ctrader.redirect_uri`).
3. Po stavu *Active*: tlačítko **Přihlásit cTrader (jen čtení)**.

## Ověření po schválení (bez přepisování kódu)

- `tools/ctrader_test_a.py` — Test A master spec (OAuth, demo účet, instrumenty, live XAU/USD a EUR/USD, bid/ask, ticky,
  historické OHLC a ticky, obnova tokenu, znovupřipojení) → `docs/CTRADER-TEST-A.md`.
- `tools/ctrader_coverage.py` — kapitola 2.3: hloubka historie (D1, H1, M1, ticky) pro XAUUSD, EURUSD, US500, NAS100,
  bid a ask, mezery, přesnost času ticků, napojení historie na živé ceny, srovnání s Dukascopy → `docs/CTRADER-POKRYTI.md`.
- Neověřené předpoklady, které skripty rozhodnou: ceny trendbarů a ticků jsou celá čísla v 1/100 000 (jako u spotů);
  ticky chodí od nejnovějšího s rozdíly proti předchozímu; jestli portál přijme návratovou adresu na `127.0.0.1`.
- Pokud Purple nedá dost historie, zůstává Dukascopy hlavním historickým zdrojem (master spec 2.3).
- cTrader se stane hlavním živým zdrojem až po Testu C (shoda s Dukascopy a Deriv); Deriv zůstane záloha.
