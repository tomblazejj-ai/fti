# Rozhodnutí a proč

Log toho, co už je vyřešené — stejný účel jako sekce 3 v CLAUDE.md u ISZ PRO.

- **2026-09-27 — Rozpočet 0 Kč/měsíc na externí data.** Uživatel explicitně
  odmítl jakékoli placené API/datové tarify. Důsledek: žádný Trading
  Economics/Bloomberg-style konsensus feed. Viz ARCHITECTURE.md sekce 1.
- **2026-09-27 — Consensus/forecast pole je nullable, nikdy nevymyšlené.**
  Bez placeného zdroje nemáme legální konsensus číslo. "Surprise" se v MVP
  počítá jako Actual vs Previous (oba z FRED/BLS/BEA, oficiální). Uživatel
  může doplnit konsensus ručně před releasem, jinak UI ukazuje "N/A".
- **2026-09-27 — Žádný scraping Investing.com/ForexFactory kalendáře.**
  Jejich ToS zakazuje automatizovaný sběr. I když by to zadání "silná první
  verze" lákalo obejít, explicitní instrukce uživatele zakazuje neověřený
  scraping — respektováno i za cenu slabšího konsensus pokrytí.
- **2026-09-27 — Žádné volání placeného LLM API pro klasifikaci zpráv v MVP.**
  Sentiment/relevance v Modulu 1 je rule-based (keyword lexikon), ne LLM.
  Důvod: LLM API by porušilo rozpočet 0 Kč na "data a API" v duchu zadání.
  Lokální open-source model (FinBERT přes transformers, CPU, zdarma) je
  navržen jako Fáze 2, ne blokuje MVP.
- **2026-09-27 — SQLite pro MVP, ne Postgres/Docker.** Nulová instalační
  bariéra na Windows bez Dockeru. SQLAlchemy vrstva dělá přechod na Postgres
  jen změnou `DATABASE_URL`, žádný přepis modelů.
- **2026-09-27 — Nový samostatný projekt mimo isz-pro.pine.**
  `C:\Users\tombl\Desktop\fundamental-trading-intelligence`, vlastní git repo.
  Pine Script indikátor a tato platforma jsou nesouvisející projekty.

## Modul 2 — GDELT, CFTC positioning, rozšířený news engine

- **2026-09-27 — CFTC COT dataset ID ověřen živě, ne z paměti.** Než jsem
  napsal konektor, otestoval jsem přímo `publicreporting.cftc.gov/resource/
  6dca-aqww.json` s filtrem na `GOLD - COMMODITY EXCHANGE INC.` — reálná
  data, žádný klíč nutný. Nespoléhal jsem na nutně nepřesnou paměť dataset ID.
- **2026-09-27 — GDELT DOC API je z tohoto sandboxu (sdílená síť/IP) trvale
  rate-limitovaný (HTTP 429), i při odstupu 20 s mezi requesty.** Ověřeno
  opakovaně. Konektor to řeší korektně — `GdeltUnavailableError` zachycena,
  cyklus pokračuje, geopolitika/central_banks pilíře zůstávají `data_quality:
  partial` s jasným důvodem, nic se nevymýšlí. **Upozornění pro tebe:** z
  běžné domácí/firemní IP by GDELT fungovat měl (veřejně dokumentované API,
  limit je jen "1 request/5s"), ale v tomto vývojovém sandboxu to nelze
  spolehlivě ověřit živě. Až poběží mimo sandbox (tvůj počítač / produkční
  hosting), over to znovu.
- **2026-09-27 — GDELT DOC API nemá per-článek tone/sentiment.** To by
  vyžadovalo stahovat bulk GKG 2.0 CSV soubory (15min updaty), výrazně těžší
  pipeline. Pro Modul 2 jde přes stejný rule-based lexikon jako RSS. GKG
  vrstva je kandidát na Fázi 2, ne blokující MVP.
- **2026-09-27 — Near-duplicate práh (Jaccard 0.25) je záměrně nízký.**
  Skutečné titulky o stejné události z různých zdrojů sdílí často méně než
  třetinu tokenů ("Fed cuts rates" vs "Federal Reserve lowers interest
  rates"). Bezpečné držet nízko, protože chybná shoda jen vyřadí jeden údaj
  z agregace do skóre (viz `run_ingest._aggregate_news_signal`) — nikdy nic
  nevymyslí, a duplicitní záznam zůstává v DB pro audit se svým zdrojem a
  časem, jen se nezapočítá dvakrát.
- **2026-09-27 — Traceability: `related_news_ids`/`related_observation_ids`
  se plní skutečnými ID, ne prázdnými seznamy.** Každá `ScoreHistoryEntry`
  teď odkazuje na konkrétní `MacroObservation` (FRED + CFTC) a `NewsItem`
  řádky, které do daného výpočtu vstoupily — ověřeno testem
  `test_ingestion.py::test_ingestion_dedupes_same_event_across_sources_and_records_traceable_history`.

## Modul 3 — ISM PMI, časové váhy, horizonty, scénáře, invalidation

- **2026-09-27 — ISM PMI NEIMPLEMENTOVÁNO — záměrně.** Živě jsem ověřil
  `ismworld.org/robots.txt` (nic to nezakazuje) a sitemap.xml, ale veřejný
  "Report on Business Roundup" blog, který dřív nesl headline číslo zdarma,
  se přestal publikovat kolem roku 2022 (poslední záznam v sitemap je z
  2022-06). Stavět scraper na zastaralém/neudržovaném zdroji by porušilo
  tvou vlastní podmínku "pokud to lze udělat spolehlivě". Žádný jiný zdarma
  a legální zdroj headline ISM PMI čísla nebyl nalezen. Neimplementováno.
- **2026-09-27 — GDELT GKG bulk tone soubory: ověření naživo se nepodařilo,
  neimplementuji naslepo.** Zkusil jsem `data.gdeltproject.org/gdeltv2/
  lastupdate.txt` (funguje, žádný rate limit — jiná infrastruktura než DOC
  API) a stažení odkazovaného `.gkg.csv.zip`, ale z tohoto sandboxu soubor
  opakovaně vracel 404 i po čekání (pravděpodobně cache/proxy specifická pro
  toto vývojové prostředí, ne obecná vlastnost GDELT). Nechtěl jsem
  implementovat parser TSV formátu, který jsem nikdy neviděl fungovat na
  reálných datech — riziko tichého bugu je vyšší než přínos. Místo toho jsem
  zlepšil kvalitu existujícího rule-based lexikonu (negace, víc termínů) —
  ověřitelné a otestované beze zbytku. GKG zůstává kandidát na budoucí fázi,
  až půjde ověřit mimo tento sandbox.
- **2026-09-27 — GDELT query syntax bug nalezen a opraven živým testem.**
  Dotazy s `OR` musí být v závorkách (`(war OR sanctions OR ...)`), jinak
  GDELT vrátí textovou chybu místo JSON. Bez živého testu (ne jen mocků) by
  tenhle bug prošel — unit testy s mockovaným transportem ho nemohly odhalit,
  protože mock vrací, co mu řekneš. Ponaučení: connector proti reálnému
  veřejnému API se musí aspoň jednou zkusit naživo, i když je to pomalé.
- **2026-09-27 — Časová váha: decay, ne přepisování vah pilířů podle
  horizontu.** Zvažoval jsem dát každému z 5 horizontů vlastní sadu vah
  pilířů, ale to by bylo arbitrární a špatně zdůvodnitelné ("proč má
  1-4w geopolitiku váženou zrovna takhle a ne jinak"). Místo toho: denní
  série (real yields, USD, Fed funds) nikdy nedecayují (jsou to aktuální
  fakta), měsíční/týdenní releasy a news decayují s poločasem rozpadu
  závislým na horizontu, ale nikdy pod podlahu 0.3 (viz `base.decay_factor`)
  — to plní požadavek "staré informace ztrácejí váhu, ale dlouhodobé
  fundamenty nezmizí" bez nutnosti vymýšlet horizon-specific váhové tabulky.
- **2026-09-27 — Bug nalezený živým testem: nekonzistentní práh pro bucket
  "bullish/bearish/neutral" ve scénářích vs. `PillarResult.impact`.**
  Scénáře používaly práh 0.15, `impact` property 0.1 — pilíř s raw_signal
  mezi nimi mohl vypsat "obrátit se z bearish na bearish". Opraveno: scénáře
  teď bucketují přes stejnou `p.impact` property, ne přes duplicitní práh.
  Přidán regresní test `test_invalidation_never_asks_a_pillar_to_flip_into_
  its_own_current_state`.
- **2026-09-27 — FOMC termíny pro 2026 natvrdo v kódu, ale ověřené naživo.**
  Zdroj: federalreserve.gov/monetarypolicy/fomccalendars.htm, staženo a
  parsováno 2026-09-27. Nejde o veřejné REST API (žádné neexistuje), kalendář
  se ale mění jen jednou za rok a je to jediný spolehlivý veřejný zdroj —
  hardcoded datum s citovaným zdrojem je čestnější než předstírat live-fetch
  z něčeho, co nemá stabilní strukturovaný endpoint. Nutno doplnit 2027, až
  Fed kalendář zveřejní.

## Modul 5 — souhrn se směrem, trend, technika, korelace, zjednodušené UI

- **2026-09-29 — Cena zlata: FRED `NASDAQQGLDI` (NASDAQ Gold FLOWS103 Price
  Index).** Denní index, který kopíruje cenu zlata; zdarma, bez klíče, ověřeno
  živě (propad −3,7 % 28. 9. odpovídá zprávám). Je v bodech indexu, ne v $/oz,
  proto všechny úrovně a graf ukazujeme v **% od aktuální ceny** — to se dá
  přenést na libovolný graf XAUUSD, číslo indexu ne.
- **2026-09-29 — Stooq zamítnut.** Nabízí denní CSV XAUUSD, ale robots.txt
  zakazuje všechny roboty (`Disallow: /`) a web vrací anti-bot výzvu. Obcházet
  ochranu nebudeme.
- **2026-09-29 — Bundesbank zamítnuta.** V otevřených datech je cena zlata jen
  jako ukončená řada v DEM (do 1998), v USD denně ne.
- **2026-09-29 — Technika jen z denních závěrů.** Zdroj nemá high/low ani
  intradenní data, takže: SMA50/200, RSI14, momentum, realizovaná volatilita,
  swingová minima/maxima. Žádné ATR ani intradenní signály — záměrně, ne
  opomenutím.
- **2026-09-29 — Souhrn je pevné, čitelné pravidlo, ne černá skříňka.**
  fundament 50 % + trend 35 % + korelace 15 %; pod ±0,2 = vyčkat; silný rozpor
  fundamentu a trendu = vyčkat. Pravidlo je v aplikaci vidět („Jak souhrn
  vznikl?“). Není to předpověď ani investiční doporučení a UI to říká.
- **2026-09-29 — Úrovně v neutrální barvě.** Zelený odpor / červená podpora by
  u shortu četla cíl jako „špatný“; jestli je úroveň vstup nebo cíl, závisí na
  směru obchodu.
- **2026-09-29 — Bug nalezený živě: stejný článek ve dvou dotazech GDELT shodil
  celou aktualizaci** (UNIQUE constraint; session má vypnutý autoflush, takže
  dříve přidaná položka téže dávky nebyla vidět). Opraveno množinou hashů v dávce
  + flush po každé položce (tím funguje i detekce blízkých duplicit uvnitř
  jedné dávky). Regresní testy v `test_ingestion.py`.
- **2026-09-29 — Rozhraní zjednodušeno.** Nahoře souhrn se směrem, pod ním tři
  karty (fundament, trend s grafem, korelace); horizonty, 8 pilířů, scénáře,
  zprávy a historie jsou schované v rozbalovacích „Podrobnostech“.
- **2026-10-02 — Cena zlata z PAXG/USD (Kraken) místo FRED NASDAQQGLDI.**
  NASDAQQGLDI je *futures* index (Credit Suisse NASDAQ Gold FLOWS103) — za
  2026 se od spotu odchýlil o ~7 % (roll), takže neumí úrovně v dolarech.
  PAXG = token krytý 1:1 uncí LBMA zlata; živě 2. 10. 2026 09:09 UTC: spot
  4 182,56 vs. PAXG 4 187,51 (+0,12 %). Kraken má veřejné dokumentované API
  bez klíče, svíčky M15–W1. Víkendové svíčky (spot zavřený pá 17:00 – ne 18:00
  New York) se zahazují. FRED index zůstává jako záloha a pro korelace.
  Zamítnuto: Binance (robots.txt na api.binance.com `Disallow: /`), LBMA JSON
  (blokuje skripty).
- **2026-10-02 — Trend na 5 timeframech + intradenní/swingový/celkový.**
  Stejný recept na každém TF (cena vs. EMA50, EMA20 vs. EMA50, sklon EMA20 v
  ATR, struktura maxim/minim), síla z ADX. Smíšené skóre ±0,2–0,4 = „spíše“.
  Prahy jsou pravidlo, ne optimalizace.
- **2026-10-02 — Fundamentální kalendář z oficiálních ICS.** BEA (HDP, PCE)
  volně; BLS (CPI, NFP, PPI, JOLTS) vrací 403 bez kontaktního e-mailu v
  User-Agentu (jejich pravidlo) → BLS se nepoužívá, kalendář tu mezeru
  přizná. Prognózy (konsenzus) zdarma a legálně nejsou → jen minulá hodnota
  z FRED.
- **2026-10-02 — E-mail uživatele se nikdy nikam neposílá.** Výslovné
  rozhodnutí uživatele. Žádná volba „kontaktní e-mail“ v konfiguraci, žádné
  osobní údaje v hlavičkách požadavků. Nepřidávat zpět ani kvůli zdroji dat.
- **2026-10-02 — Stará data se nikdy netváří jako aktuální.** Starší než dva
  intervaly aktualizace → varování a ztlumený verdikt; plánovač po probuzení
  PC doběhne zmeškanou aktualizaci; GDELT po prvním 429 přestane zkoušet.
- **2026-10-02 — Termíny CPI/NFP/PPI/JOLTS z kalendáře FRED, ne z BLS.** BLS
  chce osobní e-mail (zamítnuto uživatelem). Stránka
  `fred.stlouisfed.org/releases/calendar` je veřejná, robots.txt ji povoluje
  (Crawl-delay 1 dodržen), časy jsou v US Central. FRED resetuje spojení pro
  neznámé vlastní User-Agenty → posíláme výchozí `python-httpx/…` (pravdivý,
  bez osobních údajů, nepředstírá prohlížeč). Kešováno 12 h.
- **2026-10-02 — COT z podrobného reportu (Disaggregated).** „Managed money“
  = hedgeové fondy; navíc banky/swap dealeři, producenti, ostatní, malí.
  Základní (Legacy) report jen jako záloha. U reportu je datum dat (úterý),
  zveřejnění a očekávaný další report (pá 15:30 New York, „obvykle“).
- **2026-10-02 — DXY jen kvůli korelaci se zlatem (rozhodnutí uživatele).**
  Žádný samostatný verdikt; záložka DXY u zlata. DXY přepočítán vzorcem ICE:
  EUR, GBP, CAD, CHF živě z Krakenu, JPY a SEK z denního fixingu ECB (yen na
  Krakenu má ~25 obchodů denně). Ověřeno: 101,90 vs. ICE 101,92. Kraken FX
  tiskne nesmyslné knoty (GBP/USD high 1,70) → knoty omezeny na 3× medián
  těla svíčky; open/close beze změny.
- **2026-10-02 — Vzhled podle předlohy uživatele (terminál).** Černá + modrá
  záře, modré „pilulky“, panely, živý svíčkový graf (obnova 60 s), budík
  techniky, COT prstence, tabulka kalendáře s posunem po dnech, sezónnost s
  heatmapou, skóre faktorů −5…+5. Shrnutí je skládané pravidly a UI říká, že
  to není AI.
- **2026-10-04 — Čerstvost: technika a verdikt každých 5 minut, zprávy z
  portálů každých 10 minut.** Úplný cyklus (makro, COT, kalendář, GDELT)
  zůstává 30 min; pomalé vstupy se mezi tím berou z mezipaměti (FRED/COT 1 h,
  BEA 6 h, ECB 6 h, kalendář FRED 12 h). Tabulka analýz se ořezává na 30
  posledních záznamů.
- **2026-10-04 — Stav trhu.** Spot XAUUSD ne 18:00 – pá 17:00 New York,
  denní pauza 17–18 h. O víkendu UI říká „trh zavřen“, ukazuje uzavírací cenu
  a víkendový pohyb PAXG jako náznak gapu (svátky nezohledněny → „obvykle“).
- **2026-10-04 — Kontrola ceny třemi zdroji.** PAXG (Kraken), BullionVault
  (veřejný XML kanál pro programátory, londýnský trezor, mid) a XAUT (Kraken).
  Rozdíl > 0,5 % → varování. Živě 4. 10.: shoda do 0,10 %.
- **2026-10-04 — Korelace na skutečné ceně.** Zlato = PAXG denní (ne futures
  index FRED), dolar = DXY z denních kurzů ECB a EUR/USD z ECB (FRED
  DTWEXBGS/DEXUSEU vycházejí s týdenním zpožděním → jen záloha).
- **2026-10-04 — Panel „Zdroje a čerstvost dat“.** U každého vstupu zdroj,
  „data k“, rytmus a stav (aktuální / trh zavřen / zpožděné / chybí).
  Ověřeno: RSI (Wilder), MACD 12/26/9, SMA odpovídají TradingView; denní
  svíčka = den UTC (OANDA uzavírá ve 23:00 našeho času) — přiznáno v UI.

## Modul 6 — fundamentální skóre zlata a dolaru, 11 kategorií (2026-10-06)

- **Skóre = součet 11 kategorií (±25).** COT ±3, retail ±1, sezónnost ±2,
  HDP ±2, inflace ±3, trh práce ±4, sazby ±2, PMI služby ±2, PMI průmysl ±2,
  tržby ±2, trend ±2. Makro kategorie se počítají pro USD a u XAU/USD mají
  opačné znaménko. Prahy jsou pevné a vypsané u každé položky
  (`app/market/tra.py`).
- **Náhrady placených dat (vždy označené „≈“ v UI).** ISM/S&P PMI → regionální
  průzkumy Fedu (NY, Philadelphia, Dallas; FRED). Brokerský retail sentiment →
  „malí obchodníci“ z CFTC COT. Pravděpodobnosti sazeb (FedWatch) → 2letý
  výnos vs. efektivní sazba Fedu. COT dolaru = CFTC TFF „USD INDEX - ICE“,
  skupina leveraged funds.
- **Historie skóre se rekonstruuje se zpožděním zveřejnění.** Každá řada FRED
  má svůj typický odstup zveřejnění; zpětný bod smí použít jen data, která už
  byla venku.
- **Chybějící měsíc v datech USA (říjen 2025, shutdown).** Meziroční změny se
  počítají podle data, ne podle pozice v řadě, a jeden chybějící měsíc se
  překlene průměrem sousedů.
- **Sezónnost 5/10/15 let ze Světové banky** (Pink Sheet, CC BY 4.0) a
  **denní zlato od 2013 z NBP** (api.nbp.pl, cena v PLN/g × kurz USD/PLN →
  USD/oz; ověřeno 16. 10. 2026 = 4 164 $, spot ~4 160 $). Sezónní okno se
  zmíní, jen když jde ≥ 7 z 10 let stejným směrem a průměr je aspoň 1 %.
- **COT u zlata:** commercials a open interest (3letý index ≥ 90 / ≤ 10 přidá
  ±1 do kategorie COT). `tra.MODEL_VERSION = 2` — historie se přepočítala.

## Modul 8 — všechny trhy, jednodušší, mobil (2026-10-31)

Zadání uživatele: přehled trhů se skóre −10 až +10 a detailem s argumenty,
riziky, „co dál sledovat“ a retail sentimentem; zrušit korelace; mnohem
jednodušší; mobilní aplikace pro obchodování ve vlaku a ve škole. Vše zdarma.

- **Pět trhů:** XAU/USD, EUR/USD, GBP/USD, USD/JPY, ropa WTI. Zlato má
  11kategoriové skóre (±25 → přepočet na ±10).
- **Model měnových párů (±10):** sazby ±3 (změna rozdílu 2letých výnosů za 3
  měsíce + očekávání z 2Y vs. sazba centrální banky), inflace ±2, HDP ±2, trh
  práce ±1, COT leveraged funds ±1, sezónnost ±1. Kategorie bez dat se
  nepočítá a skóre se přepočte z ostatních — UI vypíše, co chybí.
- **Model ropy (±10):** zásoby EIA ±3, COT managed money ±2, sezónnost ±2,
  dolar ±1, poptávka (CFNAI) ±1, riziko nabídky ze zpráv ±1.
- **Zdroje (zdarma, bez klíče, ověřeno 31. 10.):** ECB Data Portal (2Y výnos,
  nezaměstnanost), Eurostat `prc_hicp_minr` (HICP — od 2026 ECOICOP 2, staré
  řady ECB končí 12/2025), ONS (UK inflace, nezaměstnanost, HDP), FRED (HDP
  eurozóny, sazba ECB, SONIA, Japonsko: nezaměstnanost, HDP, call rate),
  ministerstvo financí Japonska (2Y JGB), EIA XLS (zásoby ropy; čte `xlrd`),
  CFTC TFF (EUR, GBP, JPY futures) a Disaggregated (WTI-PHYSICAL NYMEX).
  **Zamítnuto:** Bank of England IADB (robots.txt zakazuje roboty) → UK bez
  2letého výnosu, sazba přes SONIA; japonská inflace nemá zdroj zdarma bez
  registrace (e-Stat chce app ID, kopie OECD/FRED skončily) → kategorie chybí.
- **Kalendář všech měn:** export ForexFactory „this week“ (JSON s prognózami,
  robots povoluje, stahujeme max. 1× za hodinu, historie 60 dní v
  `backend/cache/`). Další týdny: oficiální termíny Fedu, ECB, BoE a BoJ
  (`app/market/central_banks.py`) a kalendář dat USA. Názvy událostí přes
  slovník do češtiny; neznámé zůstávají anglicky.
- **Retail sentiment = malí obchodníci z CFTC** (non-reportable). Brokerská
  data zdarma bez registrace a bez scrapování nejsou. Sentiment neovlivňuje
  skóre, jen ho komentuje.
- **Mobil:** stejná webová aplikace jako PWA (manifest, ikona, offline přes
  service worker). Statický snímek API odpovědí
  (`python -m app.export_static <složka> --cycle`) + build s `VITE_STATIC=1`
  běží bez serveru; živé ceny bere telefon přímo z Krakenu (CORS povoleno).
  Hosting zdarma: GitHub Actions + GitHub Pages (`.github/workflows/mobil.yml`,
  každých 30 minut), veřejný repozitář se souhlasem uživatele. Do veřejného
  repozitáře jde jen commit s autorem `tomblazejj-ai` (noreply), nikdy lokální
  historie s e-mailem.

## Modul 9 — světlý vzhled, bez osobní strategie (2026-10-31)

Zadání uživatele: změnit název (ten starý už používá jiná platforma), světlejší
a animovanější vzhled, méně informací — hlavní věci (fundament, zprávy, co může
trh ovlivnit) hned nahoře; **žádná jeho obchodní strategie**; technický výhled
jen z veřejných webů zdarma.

- **Název:** 31. 10. krátce „Směrovka“, od 1. 11. podle zadání uživatele „FTI – Financial Trading Intelligence“.
- **Úvod:** odpočet do další důležité zprávy → dlaždice trhů (ručičkový
  ukazatel skóre, směr, jedna věta proč) → „Co hýbe trhy“ (5 nejdůležitějších
  zpráv) a „Co může trh ovlivnit“ (4 nejbližší zprávy s vysokým dopadem).
  Menu má jen Přehled, Kalendář a Zprávy. Detail trhu: proč (3 důvody + co
  jde proti), co může trh ovlivnit, technický výhled z veřejných zdrojů,
  zprávy, graf; drobní obchodníci a rozpis skóre jsou dole, rozpis sbalený.
- **Odstraněno vše, co patřilo ke strategii uživatele:** obchodní plán, zóny,
  checklist, stránka s materiály, pravidlo „nevstupovat před zprávou“ a
  týdenní plán — kód, dokumentace i stránky. Z veřejného repozitáře zmizela i
  historie — zveřejněný je jediný nový commit bez předků.
- **Technický výhled = převzaté titulky s odkazem**, ne náš výpočet: oficiální
  RSS kanály Investing.com (technická analýza měn, komodit, trhů), FXEmpire
  (prognózy) a FXStreet (analýzy). U každého zdroj a čas; anglické titulky
  strojově přeložené a označené. FXStreet blokuje servery GitHubu (403), takže
  v mobilní verzi chybí; na PC funguje.
- **Vzhled:** světlý podklad, bílé karty, jemné animace (postupné vyjetí karet,
  ručička ukazatele, vykreslení grafu, pulzující živá tečka, záblesk při změně
  ceny); „omezit pohyb“ v systému animace vypne.
- **Mobil:** service worker bere stránku a data nejdřív ze sítě, takže nová
  verze se ukáže hned při dalším otevření; offline zůstávají poslední data.

## Modul 10 — pravdivá identita instrumentů, datová vrstva, 0 Kč (2026-11-01)

Zadání uživatele: master specifikace FTI, kritická oprava XAUUSD („PAXG není XAUUSD“),
globální pravidlo pravdivosti všech instrumentů a rozpočet **0 Kč** pro celý projekt.

- **Záměna PAXG → XAUUSD odstraněna.** Konektor Krakenu měl pevně pár PAXGUSD a z něj se
  počítala cena, graf, trend M15–W1, technika, trendová kategorie skóre, sezónnost, korelace s
  DXY, headline risk, tickery i export. Navíc se při výpadku dosazoval zlatý futures index FRED.
  Nyní: XAUUSD bere data jen ze svých zdrojů (`app/data/universe.py`): terminál MT5 brokera nebo
  OANDA (obojí zdarma, vypnuté do souhlasu uživatele), jinak jen denní referenční cena NBP
  (označená, jen D1/W1). PAXG je samostatný instrument „PAXG (token)“ s označením proxy.
- **Registr instrumentů** s pravdivou identitou: typ produktu, jednotka, místo kotace,
  podklad, expirace. Hotovostní index ≠ CFD (US500 vs US500.CFD), spot WTI ≠ CFD na futures,
  BTC spot ≠ perpetual futures. U každého zdroje (feedu) se uvádí, co jeho čísla skutečně jsou:
  EUR/USD z Krakenu = kotace kryptoburzy (PROXY), ECB = denní fixing, NBP = reference.
- **Jeden vstup pro ceny** `app/data/bars.py`: zdroje v pořadí, nikdy data jiného instrumentu,
  štítek kvality LIVE / NEAR_REAL_TIME / DELAYED / HISTORICAL / STALE / UNAVAILABLE / PROXY,
  validace svíček, ukládání historie (`price_bars`), monitoring zdrojů (`source_health`).
- **FRED:** oficiální API s klíčem (zdarma, volitelně), opakování, a když FRED selže, stejná
  statistika od oficiálního vydavatele (BLS, US Treasury, CBOE, EIA). Poslední platná data se
  při výpadku ukážou se skutečným datem a označením (`series_cache`), nikdy jako aktuální.
- **Nové bezplatné zdroje (ověřeno 1. 11.):** BLS API v1, Treasury (nominální i reálné
  výnosy), CBOE VIX, EIA denní spot (WTI, Brent, Henry Hub), OECD (CPI, nezaměstnanost, sazby),
  Bank of Canada Valet, SNB, Kraken Futures (funding, open interest). Zamítnuto: RBA, RBNZ
  (403), Stooq (robots), LBMA JSON (403).
- **0 Kč:** žádné placené API, data, AI ani hosting. AI vrstva (`app/ai/provider.py`) zná jen
  „bez modelu“ (rozbor z výpočtů) a lokální open-source model přes Ollamu (Qwen/Llama 7–8B na
  RTX 3060 6 GB). Placení poskytovatelé nejsou implementováni.
- **Stránka Data:** audit všech instrumentů (co FTI skutečně dostává, odkud, jestli to odpovídá,
  omezení, doporučení), stav zdrojů, připojení MT5/OANDA a klíče (ukládají se jen do
  `backend/.env`, API je nikdy nevrací). Do veřejného exportu nejde nic z nastavení PC.

## Modul 11 — jedna cenová vrstva, stav trhu, ověření zdrojů (2026-11-01)

- **Cena 4 051,59 u zlata byla denní cena NBP** (511,29 PLN/g ÷ 3,9251 × 31,1035) a lišila se
  o 4,5 % od skutečného pátečního závěru (~3 875, TradingView OANDA). Měření na 497 dnech:
  NBP nejlépe odpovídá závěru *předchozího* obchodního dne, medián odchylky 0,6 %. NBP proto
  není zdrojem ceny XAUUSD v žádném modulu; zůstává jen jako označená referenční řada pro
  dlouhodobá sezónní okna. XAUUSD bez OANDA/MT5 = „cena nedostupná“.
- **USD/JPY, EUR/JPY, AUD/JPY, EUR/AUD, EUR/CAD z Krakenu byly falešné kotace** (54–94 %
  hodinových svíček bez obchodu, USD/JPY o 1,7 % mimo fixing ECB). Každý pár z Krakenu se teď
  automaticky kontroluje (podíl svíček bez obchodu, odchylka od fixingu ECB ve 14:15 SEČ/SELČ);
  neprojde-li, zůstane jen denní fixing ECB a intradenní data jsou nedostupná.
- **Jedna autoritativní cena** (`app/data/prices.py`): lišta, karty, detail, graf i analýza
  berou cenu ze stejné řady (`bars.get_bars`); změna se počítá jen proti závěru téhož zdroje.
- **Stav trhu** (`app/data/market_hours.py`): OPEN / CLOSED / PRE_MARKET / POST_MARKET /
  TRADING_BREAK / HOLIDAY / UNKNOWN z kalendářů burz (NYSE, CME Globex, Xetra, LSE, TSE, forex,
  kovy, kryptoburza přes SystemStatus Krakenu), svátky podle pravidel burz, časová pásma přes
  tzdata (letní/zimní čas). Otevřený trh bez nových kotací → STALE; zavřený trh → poslední
  kotace s datem a časem, nikdy jako obchodovatelná cena.
- **Test zdrojů** na stránce Data: jeden skutečný dotaz na každý zdroj, kontrola obsahu a stáří
  nejnovějšího údaje (ne jen HTTP 200).
- Fundamentální karta zlata ukazuje u každé kategorie data a jejich období (např. HDP USA
  +3,4 % = 3. čtvrtletí 2026, anualizovaně).
