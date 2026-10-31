# Fundamental Trading Intelligence — architektura a plán

Cíl: platforma, která průběžně vyhodnocuje fundamentální bias pro finanční
instrumenty (start: XAUUSD) na **0 Kč nákladech na externí data/API**.

Tento dokument je živý — aktualizuje se s každým modulem. Rozhodnutí se
zapisují do `docs/DECISIONS.md` (log, proč jsme udělali co jsme udělali),
podobně jako `CLAUDE.md` u ISZ PRO.

---

## 1. Rozpočtová bariéra: 0 Kč/měsíc

Tvrdé pravidlo: **žádný placený tarif, žádný scraping webů, které to zakazují.**
Dopad na návrh:

- Konsensus/forecast čísla u ekonomických dat (co typicky prodává Trading
  Economics/Bloomberg) **nemají čistý bezplatný a legální zdroj**. Investing.com
  a ForexFactory mají ekonomický kalendář zdarma na webu, ale jejich ToS
  zakazuje scraping/automatizovaný sběr pro vlastní aplikaci. Nepoužívám je.
  → MVP řeší "surprise" jako **Actual vs Previous** (obojí z oficiálních
  zdrojů, viz níže), ne Actual vs Consensus. Pole pro konsensus v datovém
  modelu existuje, ale je nullable a plní se buď ručně (uživatel si ho může
  zadat před releasem), nebo zůstane prázdné a UI to transparentně ukáže
  jako "consensus: N/A" — nikdy nevymýšlíme číslo.
- Sentiment/relevance analýza zpráv: žádné volání placeného LLM API (to by
  stálo peníze za token). MVP používá **rule-based/lexikonový klasifikátor**
  (keyword matching + jednoduchá pravidla pro směr dopadu). Kvalitnější, ale
  pořád zdarma cesta pro později: lokální open-source model (např. FinBERT
  přes `transformers`, běží na CPU, žádné API volání) — navrhnu jako Fázi 2,
  neimplementuji hned, ať je MVP jednoduchý na ladění.
- Tržní data (DXY, yields, VIX): **FRED má tohle všechno zdarma** jako
  oficiální statistiky (viz tabulka níže) — nepotřebujeme placený market-data
  feed vůbec.

## 2. Zdroje dat — ověření zdarma / limity / podmínky

| Zdroj | Co bereme | Zdarma? | Limit | Podmínky použití | Přístup |
|---|---|---|---|---|---|
| **FRED** (St. Louis Fed) | CPI, Core CPI, PCE, Core PCE, PPI, unemployment, NFP (PAYEMS), JOLTS, wages, GDP, Fed Funds Target, 10Y yield (DGS10), real yield (DFII10), trade-weighted USD index (DTWEXBGS), VIX (VIXCLS) | Ano | ~120 req/min na API klíč | Veřejná data, vyžaduje registraci API klíče zdarma (okamžitá), vyžaduje atribuci "Federal Reserve Bank of St. Louis" | REST API, JSON |
| **BLS** (Bureau of Labor Statistics) | CPI/NFP detail, JOLTS detail (fallback/doplněk k FRED) | Ano | 500 req/den bez klíče, 500/den + vyšší burst s registrací (zdarma) | Veřejná vládní data (public domain, US gov work) | REST API, JSON |
| **BEA** (Bureau of Economic Analysis) | GDP detail, PCE detail | Ano | Rozumné rate limity, klíč zdarma | Veřejná vládní data | REST API, JSON |
| **US Treasury (fiscaldata.treasury.gov + TreasuryDirect)** | Výnosová křivka, aukce, fiskální data | Ano | Bez klíče, rozumné limity | Veřejná vládní data | REST API, JSON |
| **EIA** (Energy Information Administration) | Ropné zásoby, produkce (pro WTI později) | Ano | Klíč zdarma, rozumné limity | Veřejná vládní data | REST API, JSON |
| **Federal Reserve Board (federalreserve.gov)** | FOMC statementy, tiskové zprávy, kalendář zasedání | Ano | RSS/veřejné stránky, žádný formální limit | Veřejné vládní publikace, RSS určený k odběru | RSS `/feeds/press_all.xml` + kalendář (statické datum příštích FOMC ze zveřejněného harmonogramu) |
| **ECB** | Tiskové zprávy, kalendář, SDW (statistický warehouse) | Ano | RSS + SDW API bez klíče | Veřejné publikace/ SDW terms povolují nekomerční i integraci s atribucí | RSS `ecb.europa.eu/rss/press.html` + SDW REST |
| **Bank of England** | Tiskové zprávy, MPC kalendář, Bank Rate | Ano | RSS + IADB (statistická databáze) bez klíče | Veřejné publikace | RSS + IADB REST |
| **Bank of Japan** | Tiskové zprávy, rozhodnutí o sazbách | Ano | Veřejné stránky/RSS kde dostupné | Veřejné publikace | RSS kde existuje, jinak pravidelný fetch veřejné stránky s rozhodnutími (ne behind paywall) |
| **GDELT Project** | Globální geopolitické/news event data (sankce, konflikty, obchodní spory) — strukturovaně, ne plný text | Ano | Zdarma, velkoryse | Explicitně určeno k výzkumnému/aplikačnímu použití, žádné ToS omezení na non-scraping (je to export dat, ne scraping webu) | GDELT 2.0 GKG API / BigQuery veřejný dataset |
| **Centrální banky — kalendáře zasedání** | FOMC/ECB/BoE/BoJ termíny na rok dopředu | Ano | Zveřejněno oficiálně předem | Veřejné | Statický seznam v DB, ročně aktualizovaný ručně z oficiálních kalendářů |

### Co jsem vyřadil a proč
- **NewsAPI.org free tier** — ToS explicitně zakazuje produkční/komerční
  nasazení na free tieru (jen "development"), navíc má embargo 24h na
  aktuální zprávy. Nepoužívám.
- **Alpha Vantage / Trading Economics / Benzinga placené tiery** — mimo
  rozpočet 0 Kč, nepoužívám.
- **Investing.com / ForexFactory ekonomický kalendář** — zdarma na webu, ale
  scraping proti ToS. Nepoužívám bez explicitního svolení uživatele k
  přijetí rizika (viz sekce 1 — řešíme jinak).
- **Yahoo Finance neoficiální endpointy** — fungují, ale nejsou to
  dokumentované/podporované API a ToS Yahoo je nejednoznačné pro
  automatizovaný komerční sběr. Necháno mimo MVP; pokud budeš chtít
  real-time cenu XAUUSD do UI (ne fundament, jen kontext), řeším to zvlášť a
  upozorním tě předem, než to zapojím.

**Otevřený bod, na který upozorňuji explicitně:** bez placeného zdroje
nemáme "Wall Street consensus" číslo pro forecast u dat jako CPI/NFP. Řešení
v MVP je popsané výše (Actual vs Previous + volitelný manuální konsensus).
Pokud ti to nebude stačit, jediná legální cesta ke skutečnému konsensu je
placený zdroj — to je tvoje rozhodnutí, ne něco, co bych měl řešit tichým
scrapingem.

## 3. Tech stack (moje volba, zdůvodnění)

- **Backend: Python 3.12 + FastAPI** — nejlepší ekosystém pro datové pipeline
  (pandas, requests/httpx, feedparser), async REST API, snadné psaní testů
  (pytest), nulová licenční cena.
- **DB: PostgreSQL**, pro MVP provoz **SQLite** (soubor, žádná instalace) přes
  stejnou SQLAlchemy vrstvu — přepnutí na Postgres je jen změna
  `DATABASE_URL`. Later: zdarma hostovaný Postgres (Supabase/Neon free tier)
  až budeš chtít nasadit mimo localhost.
- **Scheduler:** APScheduler uvnitř backendu (žádná externí služba) — polling
  FRED/RSS v rozumných intervalech (např. FRED denně, RSS každých 15 min).
- **Frontend: Vite + React + TypeScript** (původně plánován Next.js; SSR nepotřebujeme, sestavený frontend servíruje přímo FastAPI z jednoho procesu) — sdílí datový model/typy
  s budoucí mobilní appkou (React Native/Expo používá stejný jazyk a dá se
  sdílet business logika a API klient). Hosting později zdarma na
  Vercel/Netlify free tier.
- **Mobilní appka (později):** Expo (React Native) — stejný backend/API,
  Expo push notifications zdarma pro alerty.
- **Notifikace v MVP:** web push (Service Worker + Push API) — zdarma, bez
  SMS/e-mail providera.
- **Testy:** pytest (backend logika — scoring engine, klasifikátor,
  konektory s mockovanými odpověďmi, nikdy testy se skutečným síťovým
  voláním).

## 4. Datový model (jádro)

- `instruments` — kód, název, aktivní pilíře (JSON config vah dle sekce 7
  zadání), specifický driver-set.
- `macro_series` — katalog sledovaných řad (zdroj, external_id, jednotka,
  frekvence, poslední sync).
- `macro_observations` — (series_id, period, actual, previous, consensus
  nullable, surprise nullable, fetched_at, source_url).
- `news_items` — (source, external_id/hash pro dedup, title, url, published_at,
  fetched_at, raw_snippet, instrument_tags[], relevance_score, sentiment,
  factor_tags[]).
- `central_bank_events` — (bank, event_type, scheduled_at, actual statement
  url, outcome_summary).
- `score_snapshots` — (instrument_id, computed_at, horizon, bias, score,
  pillar_breakdown JSON, drivers[], contrarian[], risks[], scenarios JSON).
- `score_history` — append-only log každé změny skóre/biasu s důvodem a
  odkazem na news_items/macro_observations, které ji vyvolaly (sekce 14).

## 5. Fundamental Scoring Engine — XAUUSD (první instrument)

Piliře přesně dle tvého zadání (sekce 7), s vahami jako start (ladíme
empiricky, ne posvátně):

| Pilíř | Zdroj dat | Váha (start) |
|---|---|---|
| Fed / sazby | FRED (DFEDTARU/L, Fed Funds Futures nemáme zdarma → proxy: FRED FEDFUNDS + statement tón z RSS) | 20 |
| Inflace | FRED CPI/Core CPI/PCE/Core PCE/PPI, surprise vs previous | 15 |
| Real yields | FRED DFII10 | 20 |
| USD | FRED DTWEXBGS (trade-weighted dollar) | 15 |
| Ekonomika | FRED GDP, UNRATE, PAYEMS, ISM headline (parsed z veřejné tiskové zprávy, ne API) | 10 |
| Geopolitika | GDELT + centrální-bankovní/vládní RSS s geopolitickým tagem | 5 |
| Centrální banky (tón) | Klasifikace tónu FOMC/ECB statementů (hawkish/dovish lexikon) | 8 |
| Positioning | **Bez zdarma zdroje (CFTC COT je zdarma týdenní, ale s 3denním zpožděním — zahrnu jako slabý/pomalý signál, ne real-time)** | 7 |

Total = 100, škáluje se na finální score/bias (LONG/NEUTRAL/SHORT), stejná
transparentnost jako u ISZ PRO — žádné černé skříňky, každý pilíř má
"reasons" pole.

CFTC Commitments of Traders je bonus co jsem našel za pochodu: **zdarma,
týdenní, oficiální, žádné ToS omezení** — dobrý free zdroj pro positioning
pilíř, přidávám do tabulky zdrojů v sekci 2 jako doplněk (ověřím API detail
při implementaci pilíře).

## 6. Struktura projektu

```
fundamental-trading-intelligence/
  ARCHITECTURE.md        (tento soubor)
  docs/DECISIONS.md       (log rozhodnutí, jako CLAUDE.md u ISZ PRO)
  backend/
    app/
      main.py
      config.py
      db.py
      models.py
      schemas.py
      connectors/        (fred.py, rss_news.py, gdelt.py, cot.py, ...)
      news/               (classifier.py, dedupe.py)
      scoring/            (base.py, xauusd.py)
      ingestion/          (run_ingest.py)
      api/                (routes_instruments.py)
    tests/
    requirements.txt
    .env.example
  frontend/               (Vite + React — dashboard + detail instrumentu)
  start.bat               (spuštění celé aplikace dvojklikem)
```

## 7. Implementační pořadí (moduly)

1. **Modul 1 (tento krok):** DB modely, FRED konektor, rule-based news
   klasifikátor, scoring engine pro XAUUSD, ingestion orchestrátor, FastAPI
   endpoint, testy. Vše na SQLite, běží lokálně bez nutnosti Docker.
2. **Modul 2:** RSS/centrální-bankovní tón + GDELT geopolitika + CFTC
   positioning napojené do scoring enginu, score history/diff/alerts.
3. **Modul 3:** Frontend dashboard (seznam instrumentů) + detail XAUUSD dle
   sekce 12/13 zadání.
4. **Modul 4:** Replikace na EURUSD → zbytek instrumentů, per-instrument
   driver konfigurace.
5. **Modul 5:** Web push alerty, historie/graf vývoje skóre.
6. **Později:** mobilní appka (Expo), volitelný LLM/local-model news
   sentiment layer, volitelný placený upgrade dat (tvoje rozhodnutí, ne
   výchozí stav).
