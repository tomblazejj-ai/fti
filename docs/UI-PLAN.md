# FTI — inventura rozhraní a plán nového vzhledu (9. 11. 2026)

Zadání: nový vzhled (inspirace ProJournX + Trading Analyzer), tmavý i světlý režim, **datová a analytická logika
beze změny**, nic funkčního se nemaže, co nemá data → „zatím nedostupné“.

## 1. Současné rozhraní

| Stránka (adresa) | Komponenty | Data z |
|---|---|---|
| Přehled trhů (`#/`) | dlaždice 5 trhů, skóre, argumenty, sledovat | `/api/markets`, `/api/tickers` |
| Detail trhu (`#/trh/XAUUSD`) | hlavička, Proč, Co může ovlivnit, technický výhled portálů, zprávy, graf (vlastní SVG), retail, rozpis skóre, Režim trhu, Mezitrh, AI analýza (LONG/SHORT/NO TRADE), AI výklad | `/api/markets`, `/api/instruments/{c}/candles`, `/api/regime`, `/api/intermarket/intel`, `/api/ai/*` |
| Živě (`#/zive`) | dlaždice 4 instrumentů, živý graf, zdroje | `/api/live/stream` (SSE), `/api/live/candles` |
| Kalendář (`#/kalendar`) | týden událostí, Actual/Forecast/Previous | `/api/calendar` |
| Zprávy (`#/zpravy`) | zprávy a technické výhledy | `/api/markets` |
| Data (`#/data`) | audit zdrojů, test zdrojů, klíče, AI karta, MT5, cloud | `/api/data/audit`, `/api/sources`, `/api/ai/status` … |
| Lišta nahoře | ticker | `/api/tickers` (každých 60 s) |

Barvy: proměnné v `:root` + 144 natvrdo zapsaných barev v `app.css` a ~20 v komponentách (ikona, budíky).

## 2. Nové rozvržení

- Levý sidebar (sbalitelný na ikony): PŘEHLED (Dashboard, Live Markets, Trhy — dosavadní přehled 5 trhů),
  ANALÝZA (Zlato, Technika, Intermarket, Makro & COT, Zprávy), ROZHODNUTÍ (AI Advisor, Risk), VYHODNOCENÍ (Backtest,
  Historie signálů, Deník obchodů), SYSTÉM (Zdroje dat, Nastavení).
- Horní lišta: ticker XAUUSD, EURUSD, US500, NAS100, DXY (syn.), VIX — cena, změna %, LIVE / DELAYED / CLOSED;
  čas Praha a New York, odpočet do další důležité události, přepínač režimu, upozornění.
- Mobil: spodní lišta Přehled · Graf · Rozhodnutí · Feed · Více.

## 3. Kroky

1. Tokeny `src/styles/tokens.css` (tmavý / světlý), přepínač s uložením, všechny barvy přes proměnné.
2. Kostra: sidebar, horní lišta, mobilní lišta, adresy stránek; dosavadní stránky beze změny obsahu.
3. Graf Lightweight Charts (M1–W1, přebarvení bez reloadu) místo vlastního SVG; data stejná.
4. Dashboard: úvodní karta s rozhodnutím FTI, KPI karty s mini grafy, graf, skóre modulů, události, posledních 5 signálů.
5. Detail zlata: hlavička + záložky (Přehled · Technika · Zóny & likvidita · Intermarket · Makro & COT · Sezónnost ·
   Zprávy · Kalendář), AI shrnutí s časem, použitými daty a upozorněním.
6. Ostatní stránky: existující karty, jinak prázdný stav „zatím nedostupné“.
7. Pravidla poctivosti: tooltip u čísel (zdroj, čas, metoda), DELAYED šedě, MOCK štítek, banner, NO TRADE s důvodem.
8. Ověření: oba režimy, žádná barva mimo tokeny, 390 px bez vodorovného scrollu, přebarvení grafu, snímky obrazovky.

Rozhodnutí FTI pro zlato na Dashboardu = pravidlový verdikt enginu (LONG / SHORT / NEUTRAL = „vyčkat“) a nad ním
pravidla kódu: bez živé ceny NO TRADE s důvodem. Nic se nevymýšlí; co engine nepočítá (risk, backtest, deník,
výsledky signálů), je „zatím nedostupné“.
