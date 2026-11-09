# FTI LIVE — srovnání zdrojů pro XAUUSD, EURUSD, US500, NAS100 (9. 11. 2026)

Rozpočet 0 Kč, žádné placené API, předplatné ani VPS. Zdroje bez klíče jsou **skutečně otestované** (živý příjem
60 s v 9:55 SEČ a porovnání historie s brokerem Purple v provozní DB, jen pro čtení); u zdrojů s účtem jsou podmínky
z jejich dokumentace — ověřit je půjde až s účtem, který si založíte vy (FTI účty nezakládá).

## 1. Výsledek testu zdrojů bez klíče

| Zdroj | Instrument | Co skutečně dodává | Frekvence | Stáří kotace | Spread (medián) |
|---|---|---|---|---|---|
| **Deriv** veřejný WebSocket | Gold/USD (`frxXAUUSD`) | bid, ask, střed, čas kotace | 1× za s (snímek, ne každý tick) | 0,3 s | 0,57 USD |
| | EUR/USD (`frxEURUSD`) | totéž | 1× za s | 0,3 s | 0,9 pipu |
| | US 500 (`OTC_SPC`) | totéž, **jen 6–21 h UTC** | 1× za s | 0,3 s | 0,4 bodu |
| | US Tech 100 (`OTC_NDX`) | totéž, **jen 6–21 h UTC** | 1× za s | 0,3 s | 1,0 bodu |
| **Kraken** WebSocket v2 | EUR/USD (burza Kraken) | bid, ask, poslední obchod | tick po ticku (medián 0,03 s) | čas kotace neuvádí | 0,6 pipu |
| gold-api.com | XAU | jedna cena bez času kotace | za minutu jen 2 různé ceny | neznámé | — |
| Dukascopy | všechny 4 (CFD) | hodinové soubory | ~1 h zpoždění | — | — |

**Shoda s vaším brokerem** (Purple Trading MT5, hodinové závěry 26. 10.–6. 11., stejné hodiny UTC):

| Deriv × Purple | Společných hodin | Posun (Deriv − Purple) | Rozdíl medián | 95 % | Max |
|---|---|---|---|---|---|
| XAUUSD × XAUUSD_ecn | 226 | +0,18 USD (střed × bid) | 0,24 USD | 0,77 | 1,86 |
| EURUSD × EURUSD_ecn | 234 | +0,4 pipu | 0,4 pipu | 1,3 | 6,3 |
| US 500 × US500_ecn | 149 | −0,59 bodu | 0,9 bodu | 3,4 | **44** |
| US Tech 100 × US100_ecn | 150 | +0,13 bodu | 4,2 bodu | 21 | **338** |

Velké rozdíly u indexů jsou vždy v hodině, kdy Deriv končí (20/21 h UTC): poslední svíčka Deriv má jedinou kotaci
(otevření = závěr), Purple CFD obchoduje dál 23 h denně. **Deriv US 500 / US Tech 100 není totéž co CFD brokera
mimo americkou seanci** — mimo ni nesmí být LIVE a nesmí na něj přepnout záloha. Kraken EUR/USD je kotace kryptoburzy,
od brokera se liší o 2 pipy (medián) → jen kontrola, ne záloha. Dukascopy × Purple u zlata: viz Ú1 (H4 0,17 USD).

## 2. Zdroje s účtem (podmínky z dokumentace, neověřeno bez účtu)

| Zdroj | 4 instrumenty | Streaming | Bezplatně | Co je potřeba od vás | Poznámka |
|---|---|---|---|---|---|
| **Purple Trading cTrader — Open API** | ano (váš broker) | WebSocket JSON `demo.ctraderapi.com:5036`, kotace bid/ask tick po ticku | ano („free, publicly accessible“) | demo účet cTrader u Purple + registrace aplikace na openapi.ctrader.com (schválení Spotware, obvykle do 1 prac. dne) | **nejlepší volba**: přesně ceny vašeho brokera, 23 h, i z cloudu; limit 50 dotazů/s na spojení |
| Purple MT5 | ano | lokálně (balík MetaTrader5) | ano | běžící terminál na PC | jen s PC → kontrola, ne cloud |
| OANDA v20 practice | XAU_USD, EUR_USD; indexy SPX500/NAS100 u evropských účtů nejisté | HTTP streaming | ano | demo účet OANDA + token | FTI má konektor; podle třetích stran mají demo účty zpožděná data |
| Capital.com API | GOLD, EURUSD, US500, US100 | WebSocket, max 40 instrumentů, relace 10 min (ping) | ano s demo účtem | účet + API klíč (2FA) | jiný broker než Purple → jen záloha po ověření |
| IG (demo) | ano | Lightstreamer | ano | demo účet IG | složitější protokol |
| Twelve Data Basic | jen „trial“ symboly | 1 spojení, 8 symbolů z trial seznamu | 800 dotazů/den | bezplatný klíč | streaming našich instrumentů jen v placeném Pro |
| Finnhub free | forex nejasný, CFD indexy ne | WebSocket (50 symbolů) | jen nekomerčně | bezplatný klíč | pokrytí forexu na free tarifu nepotvrzené |
| **XTB** | — | — | — | — | **xAPI zrušeno 14. 3. 2025** — porovnání s XTB jen ručně ze screenshotu |

Zdroje: [cTrader Open API](https://help.ctrader.com/open-api/), [endpointy cTrader](https://help.ctrader.com/open-api/proxies-endpoints/),
[registrace aplikace](https://help.ctrader.com/open-api/api-application), [Purple cTrader demo](https://www.purple-trading.com/ctrader-demo-account/),
[Deriv ticks](https://developers.deriv.com/llms/ticks.md), [Capital.com API](https://open-api.capital.com/),
[Capital.com limity](https://help.capital.com/hc/en-us/articles/6630830103058-Do-you-have-any-limitations-on-your-API),
[Twelve Data trial](https://support.twelvedata.com/en/articles/5335783-trial), [Twelve Data ceny](https://twelvedata.com/pricing.md),
[XTB API ukončeno](https://www.xtb.com/int/help-center/our-platforms-1/do-you-offer-api-1),
[OANDA v20](https://developer.oanda.com/rest-live-v20/introduction/),
[Cloudflare Durable Objects ceny](https://developers.cloudflare.com/durable-objects/platform/pricing/).

## 3. Doporučení

| Instrument | Primární | Záloha (jen po ověření shody) | Kontrola |
|---|---|---|---|
| XAUUSD | Purple cTrader Open API (až založíte demo + aplikaci); do té doby **Deriv** | Deriv | Dukascopy (zpožděná), MT5 při běžícím PC |
| EURUSD | Purple cTrader; do té doby **Deriv** | Deriv | Kraken (jiný trh, 2 pipy), Dukascopy, FXCM |
| US500 (CFD) | Purple cTrader | Deriv `OTC_SPC` **jen 6–21 h UTC** | Dukascopy `USA500IDXUSD` (CFD), FRED SP500 (index, denně) |
| NAS100 (CFD) | Purple cTrader | Deriv `OTC_NDX` **jen 6–21 h UTC** | MT5 při běžícím PC |

Bez účtu u brokera **nejde zdarma získat živé CFD kotace US500 / NAS100 na 23 hodin** — Deriv je pokryje jen
v americké seanci, mimo ni FTI ukáže stav DELAYED / HISTORICAL. Indexové hodnoty S&P 500 a Nasdaq-100 (ne CFD)
v reálném čase zdarma legálně nejsou (licence burz); FTI je proto nezaměňuje.

## 4. Architektura LIVE DATA ENGINE

```
poskytovatel (adaptér)  →  normalizovaný tick (bid, ask, čas kotace, čas příjmu, zdroj, typ produktu)
   Deriv / cTrader / MT5 / Kraken / …        │
                                              ├→ stav instrumentu LIVE / DELAYED / HISTORICAL / UNAVAILABLE
                                              ├→ záloha: přepnutí jen na zdroj s ověřenou shodou (souběžné kotace)
                                              ├→ svíčky M1 … D1 (mřížka brokera z Ú1, každý zdroj svou historii)
                                              ├→ ticky po minutových blocích (historie pro analýzu)
                                              ├→ monitoring: spojení, latence, stáří, výpadky
                                              └→ SSE stream do aplikace · brána pro AI (bez LIVE žádný signál)
```

- Nový instrument nebo poskytovatel = jeden řádek mapování / jeden adaptér, jádro se nemění.
- Ceny se nikdy neupravují o posun mezi zdroji; posun se jen měří a rozhoduje o povolení zálohy.
- **Cloud bez PC:** stejný engine jako Cloudflare Durable Object (bezplatný tarif: 13 000 GB-s/den, jeden stále
  běžící objekt ≈ 10 800 GB-s; příchozí zprávy 20 : 1 vůči 100 000 požadavků/den ≈ 17 300 při 4 × 1 tick/s).
  Že Cloudflare drží trvalé odchozí spojení, se dá ověřit jen nasazením → **až s vaším souhlasem**.
- Otevřené: podmínky Deriv pro další šíření dat se nepodařilo dohledat → živé ceny jen pro vás, ne na veřejnou
  mobilní stránku.
