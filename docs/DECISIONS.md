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

## Modul 12 — AI přes Groq Free, jen výklad výpočtů FTI (2026-11-01)

- **Poskytovatel:** Groq, výhradně bezplatný tarif Free, přes oficiální rozhraní kompatibilní
  s OpenAI (`https://api.groq.com/openai/v1`, volání přes httpx, žádná nová knihovna).
  Povolené jsou jen produkční modely `openai/gpt-oss-120b`, `openai/gpt-oss-20b` a záložní
  `llama-3.3-70b-versatile`; žádné placené režimy (Batch, Flex). Mistral zatím ne.
- **Klíč** jen `GROQ_API_KEY` v proměnných prostředí nebo v `backend/.env` (v `.gitignore`).
  API ho nikdy nevrací, u AI klíče se neukazují ani poslední znaky, výpisy procházejí filtrem,
  který maže vše, co vypadá jako klíč (`app/ai/redact.py`).
- **Vlastní limity FTI** (`app/ai/guard.py`): nejvýš 80 dotazů denně (natvrdo, nastavení je může
  jen snížit; počítají se i neúspěšné), 100 000 tokenů denně, 6 dotazů za minutu, nejvýš 90 %
  minutového limitu tokenů, který Groq hlásí; posledních 20 % denního limitu jen pro důležité
  události. HTTP 429 → model čeká podle `retry-after` / obnovy denního limitu; výpadek → pauza
  1 → 5 → 15 → 60 min; odmítnutý klíč → AI vypnutá do změny klíče; požadavek platby (402) →
  AI zastavená do ručního povolení. Stav i čítače jsou v databázi (přežijí restart).
- **Proč ne „polovina minutového limitu“:** dotaz na zlato má i s odpovědí ~3 700 tokenů,
  Groq Free u gpt-oss hlásí 8 000 tokenů za minutu; polovina by takový dotaz zablokovala natrvalo.
- **AI nesmí nic vymýšlet:** dostane jen balíček faktů z výpočtu FTI (`app/ai/facts.py`, každý
  fakt s označením, zdrojem a datem). Odpověď se kontroluje (`app/ai/validate.py`): schéma,
  existující označení faktů a každé číslo v textu musí být ve faktech (v libovolném zápisu).
  Neprojde-li, uloží se jako „neověřeno“ a aplikace ukazuje rozbor FTI. Rozhodnutí LONG/SHORT
  nikdy nedělá AI (sloupec `preferred` zůstává prázdný).
- **Úspornost:** stejné vstupy → uložená odpověď bez dotazu; odstupy (tržní výklad 60 min,
  briefing 240 min, změna 15 min); automatické analýzy (výchozí vypnuto) jen při změně BIAS
  nebo skóre o ≥ 2 body, u důležité zprávy (relevance ≥ 0,5, max. 2 za cyklus) a 2× denně
  briefing; nejvýš 3 dotazy na cyklus.
- **Nepřipravené úlohy** (engine pro ně nemá vstupy): LONG/SHORT/NO TRADE (engine má jen
  fundamentální BIAS), makro událost po zveřejnění (kalendář neukládá actual), S/D zóny, order
  blocky a FVG. Aplikace je ukazuje jako nepřipravené, žádný AI text pro ně nevzniká.
- Mobilní (statická) verze AI nemá — přijde až s cloudem.

## Etapa 2 — datová infrastruktura (listopad 2026)

- **2026-11-07 — Vize je závazná.** Produktová vize (osobní AI trading analytik, AI-first,
  aktualizace modelů jen po ověření, Live AI Market Analyst, Intermarket Intelligence) je
  v [VIZE.md](VIZE.md). Nic z ní se neimplementuje předčasně; etapa 2 ji připravuje daty.
- **2026-11-07 — Bez platební karty.** Oracle Cloud Always Free uživatel neschválil (ověření
  kartou). Twelve Data Basic se neintegruje (jen „bez zobrazení“, XAU/USD až v placeném).
- **2026-11-07 — Dukascopy má vlastní historii.** `bars.collect_history()` ukládá Dukascopy
  XAUUSD při každé obnově trhu, i když se zobrazuje MT5; jen celé svíčky, rozpracovaná nikdy
  jako uzavřená, mezery se hlásí a nedoplňují.
- **2026-11-07 — Monitoring hodnotí zdroj podle toho, co nabízí.** Nepodporovaný rámec (H1
  z denního zdroje) není chyba; odmítnutá data kontrolou kvality se počítají zvlášť.
- **2026-11-07 — Čas zprávy má vždy svůj původ.** Sloupec `news_items.time_basis`:
  `published` (čas zdroje), `gdelt_seen` (GDELT čas publikace nedává, jen kdy článek zachytil),
  `fetched` (zdroj čas neuvedl, stojí tam čas stažení FTI — vždy s popiskem). GDELT článek bez
  času se neuloží. Staré záznamy podle pravidla ověřeného na datech (30× `fetched`, vše RSS
  Investing.com technika); časy samotné se nezměnily.
- **2026-11-07 — GDELT šetrně.** 41 % dotazů skončilo 429 při rozestupu 5 s. Nově 2 dotazy
  na cyklus po 10 s, střídání, jen nové články od posledního úspěchu, pauza 15 → 30 → 60 min
  uložená přes restart, jedno opakování při krátkém výpadku.
- **2026-11-07 — AI zná původ každého času zprávy (nález A).** Fakt zprávy nese vedle času
  „k“ pole `puvod_casu` (čas publikace / zachycení GDELT / stažení FTI) a systémový pokyn
  zakazuje vydávat zachycení či stažení za publikaci. AI dostává originální titulek, ne
  strojový překlad.
- **2026-11-07 — Neznámé stáří není čerstvost (nález B).** Zpráva jen s časem stažení
  (`fetched`) se nezapočítává do rizika titulků, nálady zpráv, váhy zpráv ve skóre ani rizika
  nabídky ropy; každý výpočet uvádí, kolik jich vynechal. V seznamech je až za zprávami se
  známým časem. Žádný náhradní čas se nevymýšlí. Čas zachycení GDELT se dál bere jako
  přibližný (42 článků s datem v URL: 37 týž den, 3 další den, 2 o 2–3 dny později).
- **2026-11-07 — GDELT „gold“ jen o zlatě jako trhu (nález C).** Ze 250 článků starého dotazu
  bylo o trhu se zlatem asi 15–20 (GDELT hledá v překladech celých textů ve ~65 jazycích).
  Dotaz nově vyžaduje i tržní slovo; FTI navíc kontroluje titulek (zlato + tržní souvislost
  ve ~20 jazycích, `app/news/relevance.py`). Jazyk bez slovníku se nevyřazuje — souvislost
  ručí dotaz. Na skutečné odpovědi: ponecháno 17 z 250, z toho 15 o trhu se zlatem; žádný
  vyřazený titulek se zlatem nebyl o trhu. Obrazovka Zprávy už nebere „Gold Coast“/medaile.
- **2026-11-07 — Překlad nesmí měnit čísla (nález D).** Každý překlad se kontroluje: všechna
  čísla s měnou, procentem a řádem (tisíc / milion / miliarda) i rozpětí musí sedět
  s originálem. Neprojde-li, uloží se `title_cs = ""` a zobrazí se originál s popiskem.
  Kontrola běží i při zobrazení, takže starší chybný překlad se už neukáže (12 z 376
  uložených, např. „3-month low“ → „kleslo o 8 %“); nedávné se přeloží znovu. Před
  překladem se opravují mezery GDELT v číslech („$3 , 800“), „$4k“, „$1.28m“ a rozpětí.
  Struktura databáze se nezměnila, `published_at` zůstává povinný.
- **2026-11-08 — První kompletní AI analýza XAU/USD (základ etapy 3/5).** Společný analytický
  kontext (`app/ai/context.py`, 12 oblastí, každý údaj se zdrojem, časem a kvalitou) → AI Router
  (`app/ai/router.py`, registr poskytovatelů; používá se jen bezplatný + schválený + s klientem
  + s klíčem, placené nikdy) → tři AI role (`app/ai/pipeline.py`: makro na silném modelu,
  technika na rychlém, hlavní analytik) → LONG / SHORT / NO TRADE se scénáři, potvrzením,
  invalidací a vztahem k pravidlovému verdiktu FTI → kontrola čísel a pravidel → uložení
  (`analyses`, kind `ai_trade`) → panel „Komplexní AI analýza“ na detailu zlata. Role kvůli
  limitu Groq Free 8 000 tokenů/min na model (celý kontext se do jednoho dotazu nevejde).
  Automaticky jen při skutečné změně (BIAS/skóre, trend, riziko titulků, zveřejněná událost),
  nejvýš 6× denně, a jen se zapnutými automatickými analýzami. Mezitrh (VIX, výnosy 10 let
  nominální i reálný, WTI, S&P 500) přidán do výpočtu jako data pro AI — vzhled beze změny.
  Ukázka 8. 11. na kopii DB: 3 volání Groq, 16 341 tokenů, 128 s, 0 Kč, výsledek NO TRADE.
  Známá slabina: kontrola hlídá vymyšlená čísla, ne špatně přiřazená (model zaměnil korelace
  a směr výnosů) — další krok je nezávislá kontrolní role.
- **2026-11-08 — Závazné architektonické principy (uživatel).** FTI je multi-provider:
  pro tržní data, kalendář, zprávy, makro data i AI musí jít zapojit 10+ nezávislých
  poskytovatelů bez přepisu jádra; zdroje se doplňují a vzájemně kontrolují, rozpory se
  ukazují, záloha nastupuje jen při srovnatelném typu a kvalitě dat. Konkrétně: Dukascopy
  zůstává hlavním zdrojem svíček, **TickBase je plánovaný záložní a kontrolní zdroj
  aktuálních cen** (ne náhrada Dukascopy; zdarma 5 000 dotazů/měsíc, bez OHLC). Kalendář:
  **Forex Factory hlavní**, **Myfxbook RSS záložní po ověření v pracovní den**, hodnoty
  Actual z oficiálních zdrojů (FRED, BEA, ECB, Eurostat …). AI: libovolný počet
  poskytovatelů přes AI Router, placený nikdy bez výslovného souhlasu. Implementace těchto
  zdrojů začne až po dokončení C1 a ověření AI analýzy.
- **2026-11-08 — C1: FTI bez PC.** Výpočet běží na GitHub Actions (veřejný repozitář,
  zdarma): data → výpočty → AI → výsledky do Cloudflare D1 (Workers Free + D1 Free, bez
  karty), Pages zůstává záloha. Worker `fti` na `fti.tomblazejj.workers.dev`, D1 `fti`
  (EEUR). Zápis do D1 jen s tokenem GitHub Actions (OIDC: podpis, repozitář, větev main,
  audience) nebo s tajnou hodnotou PC — žádné heslo ke cloudu v GitHubu. Klíč Groq jen jako
  šifrovaný GitHub Secret. Plán GitHubu `*/30` běžel ve skutečnosti 3–5× denně (medián
  mezery 106 min), proto Worker Cron každých 30 min spouští běh přes `workflow_dispatch`
  (potřebuje GitHub token jen s „Actions: Read and write“ pro tento repozitář jako tajnou
  hodnotu Workeru). Wrangler přihlášen jen se 4 oprávněními (workers_scripts:write,
  d1:write, account:read, user:read) a po nasazení odhlášen. Podmínky GitHubu: dávka,
  která počítá a publikuje data projektu (ne obsluha požadavků) — v souladu s „production,
  testing, deployment, or publication“; Actions nejsou CDN ani serverless backend.
- **2026-11-08 — Nezávislá kontrola AI** (`app/ai/check.py`, pravidla, ne AI): čísla bodu
  musí být v citovaných údajích, hodnota u indikátoru musí patřit tomu indikátoru,
  korelace té řadě, ke které je napsaná, a směr (roste/klesá) datům za 5 i 20 dní.
  Chybné body se vyřadí a zaznamenají; chyba v souhrnu označí analýzu za neověřenou.
- **2026-11-08 — C1 ověřeno časovačem Cloudflare.** Worker Cron `*/30` volá GitHub API
  (`workflow_dispatch`) tokenem `GITHUB_DISPATCH_TOKEN` (jen repozitář fti, Actions R/W).
  První běh od časovače 42490163736: založen 14:30:47 UTC, data + AI 5 min 8 s, zápis do D1
  7 s, úspěch. První AI analýza v cloudu přes Groq (gpt-oss-120b / 20b, 13 844 tokenů,
  NO TRADE, kontrola bez nálezu). Zjištění: (1) „EMA20/50“ v textu technické role počítala
  kontrola čísel jako neznámé číslo 50 a celou roli zahodila → opraveno (`validate.INDICATOR`,
  jedno pravidlo i pro `check.py`); (2) Dukascopy z GitHubu dodává historii jen postupně
  (první běh: pátek 6. 11.), karta zlata tak může mít orientační cenu gold-api a horní pruh
  cenu Dukascopy — oba údaje jsou správně označené, sjednotí se, až se historie doplní.
- **2026-11-08 — TickBase zapojen jako kontrola a záloha ceny zlata**
  (`app/connectors/tickbase.py`; Dukascopy zůstává hlavní). Ověřeno v dokumentaci a dotazy:
  ceny jen s klíčem z účtu zdarma (`tb_live_…`, hlavička Authorization), `/v1/status` a
  `/v1/symbols` veřejné; zdarma 5 000 dotazů/měsíc, 30/min, 30 dní historie, OHLC placené
  (nepoužívá se). FTI: nejvýš 1 dotaz na cenu za 15 min, strop 2 400/měsíc na instalaci
  (PC + cloud na jednom klíči < 5 000), počítadlo v DB. Kontrola v každém cyklu: TickBase
  bid proti svíčce Dukascopy M1 ze stejné minuty (≤ 0,05 % shoda, ≤ 0,15 % mírný rozdíl,
  víc ROZPOR) a čerstvost podle stavu trhu → „Zdroje“ a `/api/sources`. Záloha: když
  Dukascopy ani broker cenu nemají, `prices.quote` vezme TickBase s jeho časem kotace (před
  orientační gold-api), jen čerstvou a jen na PC. Podmínky zakazují sdílet surové odpovědi →
  veřejné soubory (cloud, Pages, synchronizace z PC) cenu TickBase nikdy neobsahují
  (`export_static._without_tickbase_prices`). **Zjištění 8. 11.:** veřejný stav TickBase
  hlásí poslední data zlata z 1. 11. 00:16 UTC, přestože trh obchodoval do 6. 11., a FX ze
  14. 8. — zdroj stojí. Ceny se ověří, až uživatel přidá klíč (účet nemůže zakládat AI).
- **2026-11-08 — TickBase autentizovaně ověřen: aktuální data zlata NEDODÁVÁ.** Skutečná
  odpověď `/v1/metals/latest?metal=XAU` (klíč zdarma) má pole metal, currency, price,
  unit `troy_ounce`, bid, ask a `as_of 2026-11-01T00:16:10Z` (čísla odpovědi se sem
  nepíšou — podmínky TickBase zakazují šířit surové odpovědi) — čas je víkend a od té doby se
  nezměnil, přestože trh obchodoval 2.–6. 11.; `/v1/metals/historical` pro 30. 10. i 6. 11.
  vrací 404 „No data for the requested date“; veřejný `/v1/status` (nezávislý na tarifu)
  hlásí totéž → stojí jejich zdroj, ne tarif. Cena je přesný střed bid/ask s
  rozpětím 58 USD (1,5 %), u zlata je skutečné rozpětí ~0,01 %; proti poslední svíčce
  pátku 30. 10. (Dukascopy H1 close 3874.585 bid, broker MT5 M15 3875.49) +13,66 USD
  (+0,35 %). Opravy po testu: (1) záloha brala čerstvost bez času posledního obchodu →
  teď z kalendáře trhu (`last_trading_moment`) a při nejistotě se cena odmítá (fail
  closed, nejvýš 4 dny); (2) párování hledalo jen minutovou svíčku Dukascopy, kterou FTI
  za 26.–31. 10. nemá (M1 se stahuje jen pro poslední dny) → M1, M5, M15, H1 a broker MT5
  jako druhý názor; (3) rozpětí bid/ask nad 0,1 % = není tržní kotace → kontrola ho
  hlásí a záloha ho nepoužije; jiná jednotka než USD/troy_ounce se odmítá. Výsledek:
  TickBase zůstává zapojený jen jako kontrola (1 dotaz za cyklus, odpovědi se hlídají),
  jako záloha ceny se teď nepoužije nikdy, dokud nezačne dodávat čerstvé a věrohodné
  kotace. Znovu ověřit při otevřeném trhu (veřejný `/v1/status` kvótu nespotřebuje).
- **2026-11-08 — Skutečné hodnoty (Actual) z oficiálních dat** (`app/market/actuals.py`).
  Forex Factory zůstává hlavním kalendářem (události, časy, prognóza, minule); FTI k
  vydaným událostem USD doplní skutečnost z ALFRED/FRED **ve stavu ke dni vydání**
  (pozdější revize ji nepřepíše), vydavatelé BLS, BEA, Census, DOL. Ověřeno živě: hodnoty
  ke dni vydání = přímé API BLS do poslední číslice (NFP 159 293 / 159 128, AHE 38,00 /
  37,86, JOLTS 7 523, nezaměstnanost 4,1 %); přepočty dávají „minule“ z FF u dalšího
  vydání (CPI m/m 0,6 %, jádro 0,3 %, PPI 1,3 %, jádro PPI 0,7 % = řada PPIFES, žádosti
  189K). Hodnota se uloží jednou (`series_cache` „actual:…“), před načtením do FRED se
  píše „čeká na oficiální data“, nic se neodhaduje. ISM, ADP a University of Michigan
  volný oficiální zdroj nemají — u nich to FTI napíše. Kalendář ukazuje „skutečnost X ·
  prognóza · minule (revize)“. Myfxbook RSS se ověří v pracovní den; do té doby záloha není.
- **2026-11-08 — TickBase: dotazy na ceny vypnuté, dokud zdroj nemá aktuální data.** Konektor
  i klíč zůstávají. Každý cyklus se ptá jen na veřejný `/v1/status` (bez klíče, kvótu
  nespotřebuje); dotaz na cenu (s klíčem) se pustí, jen když tam jsou data zlata tak čerstvá,
  jak trh dovoluje (`feed_gate`, pamatuje si 30 min, při chybě zavřeno). Zastaralá cena se
  nikdy nepoužije jako záloha.
- **2026-11-08 — Actual: záznam v2 s ověřením u vydavatele a historií.** Každá hodnota nese
  vydavatele (oficiální vládní zdroj), zprostředkovatele (ALFRED/FRED, institucionální),
  Forex Factory jako sekundární kalendář, referenční období, jednotku, den vydání (ALFRED),
  čas vydání (FF), „minule“ podle FF, „minule“ jak bylo oficiálně zveřejněno před vydáním
  a „minule“ revidované. Hodnoty BLS se jedním dotazem ověří přímo v API BLS („ověřeno u
  vydavatele“ jen při shodě úrovní); DOL (dol.gov 403) a Census (jen PDF) zůstávají
  „neověřeno u vydavatele“ a kalendář to u hodnoty napíše. Starší záznam se při doplnění
  polí nepřepisuje — jeho předchozí verze zůstává v `history`. Ověření 8. 11. na kopii živé
  DB: 6 z 8 ověřeno u BLS, 2 neověřeno; „minule“ FF = oficiální údaj v 7 z 8 (u nákladů na
  jednotku práce FF 1,3 %, oficiálně 1,2 % po revizi 3. 9.).
- **2026-11-08 — Kalendář: vydané události se skutečnou hodnotou 7 dní.** Ostatní okno beze
  změny (2 dny zpět, 21 dní dopředu, stejné měny a filtry). Forex Factory zůstává hlavní.
- **2026-11-08 — Kontrola dat pro Intermarket (kopie živé DB).** Dukascopy měl v FTI jen
  zlato a krátce (H1 od 25. 10., M15 jen týden, M1 s dírou 16. 10.–1. 11., M30 nikde).
  MT5 má uloženou historii (D1 ~1 000 od 12/2022, H1 ~1 115 od 9/2026, M15 ~1 460 od
  16. 10.) pro zlato, EUR/USD, USD/JPY, S&P CFD, WTI a Brent CFD — terminál neběží, takže
  jen nepřibývá. Výnosy (Treasury od 2021), VIX (CBOE od 1990), S&P (FRED od 2016) a WTI
  (EIA) jsou jen denní. DXY se neukládal. Kraken USD/JPY H1 má 72 skoků — nepoužívá se.
  ECB fixing (14:15 Frankfurt) a půlnoční D1 Dukascopy nejsou synchronní s uzávěrkami USA
  → v denních korelacích se nepoužívají. Duplicity 0, vadné OHLC 0. Ropa: CFD brokera na
  futures WTI klesl 30. 10. → 6. 11. o 12,4 % (2. 11. −6,6 %, 4. 11. −9,0 %, otevření vždy u
  předchozího zavření = žádný skok při rolování). EIA spot (Cushing) má data jen do 3. 11.:
  30. 10. → 3. 11. −7,4 % proti −6,1 % u CFD; pokles 4. 11. a dál EIA zatím nedokládá.
  (Opraveno 8. 11.: dřívější věta „EIA ho potvrzuje“ platila jen pro část do 3. 11.)
- **2026-11-08 — Dukascopy pro 8 dalších trhů** (ověřeno živě: EURUSD, USDJPY, WTI, Brent,
  S&P 500, dolarový index, VIX, T-Bond; index a komodity jsou CFD na futures, označené),
  měsíční soubory hodinových svíček (1 dotaz = měsíc). `intermarket_data` doplňuje historii
  po měsících a posledních dnech; výpadek (503, timeout) zastaví stahování a pokračuje se
  po pauze, nic neúplného se neuloží. **V živé aplikaci je vypnuté** (`intermarket.enabled`),
  dokud to uživatel nezapne — jinak by cyklus zapisoval do živé DB.
- **2026-11-08 — Intermarket Intelligence** (`app/market/intermarket_intel.py`,
  `/api/intermarket/intel?tf=D1|H1`). Korelace výnosů jen na synchronních obdobích: H1 =
  stejné hodiny UTC (návraty mezi po sobě jdoucími společnými hodinami, tedy stejný interval),
  D1 = uzávěrky téhož obchodního dne v USA (17:00 NY z hodinových svíček, MT5 den, S&P 16:00,
  VIX 16:15, Treasury ~15:30, WTI 14:30 — posun uvádí kvalita). Okna H1 48/120/480,
  D1 30/60/120/250 (každé ≥ minimum 30 pozorování). U každého vztahu r, okno, n, p (Fisher),
  95% interval, stabilita (klouzavá korelace), změna proti předchozímu oknu, rozpad/obrat,
  potvrzení pohybu zlata (vztah měřený PŘED pohybem), poslední společné období, zdroje,
  kvalita. Objevování všech párů s korekcí Benjamini–Hochberg a test předstihu. Korelace není
  kauzalita. Kontrola zdrojů: zlato Dukascopy × MT5 ve stejné dny r = 1,00.
- **2026-11-08 — Intermarket: metodika a provoz (verze 2).**
  Korelace jen z **výnosů** (log výnosy, u výnosů dluhopisů změna v b. b.), nikdy z úrovní —
  dva nezávislé trendy mají v úrovních r > 0,8, ve výnosech nic (test). Synchronizace:
  stejný okamžik zavření (UTC), M30/H4 jen když existuje poslední část svíčky, D1 jen
  svíčka končící přesně 17:00 NY (jinak by šlo o jiný okamžik). p-hodnoty a 95% intervaly
  Fisherovou transformací s **efektivním počtem pozorování** (Bartlett: n / (1 + 2 Σ ρx·ρy),
  10 zpoždění) — autokorelace snižuje počet nezávislých pozorování. Korekce Benjamini–
  Hochberg (q) pro hlavní tabulku, objevy i předstih. Bez pohledu do budoucnosti: `as_of`
  bere jen svíčky uzavřené do daného okamžiku (test: přidaná budoucí data nezmění výsledek),
  rozpad porovnává okna končící ve stejném bodě, „potvrzuje/odporuje“ měří vztah PŘED
  hodnoceným pohybem. Konstrukčně příbuzné páry (US10Y × reálný výnos, WTI × Brent, S&P ×
  VIX, euro × DXY) se označují a nevydávají za objevy. Rámce M15 (MT5/Dukascopy), M30 (z
  M15), H1, H4 (z H1), D1. DXY* = vzorec ICE z kurzů brokera MT5 (EUR, JPY, GBP, CAD, CHF)
  a SEK z fixingu ECB (4,2 % váhy) — vypočtený index, ne kotace; náhrada, dokud Dukascopy
  (dolarový index CFD) neodpovídá. Provoz: (1) data — plán chybějících souborů, priorita
  DXY, nejvýš 6 souborů a 90 s za běh, výpadek = konec běhu, hotové soubory se nestahují
  znovu; (2) kvalita a synchronizace — přehled řad; (3) výpočet jen při změně otisku dat;
  (4) uložení výsledku a historie (60 posledních) — vše jen se zapnutým modulem.
  Zdroj výnosů: US Treasury, denní nominální křivka (par yield curve, 2 a 10 let) a denní
  křivka reálných výnosů TIPS (home.treasury.gov). Nominální výnos ≈ reálný výnos +
  očekávaná inflace (breakeven), proto se jejich denní změny pohybují spolu (r +0,92) —
  to je stavba trhu, ne objev.
- **2026-11-08 — Intermarket jako součást FTI (ne samostatný endpoint).** AI kontext má
  oblasti `intermarket` (korelace zlata se synchronizovanými výnosy D1 a H1: okna, n,
  efektivní n, p, q, předchozí okno, stabilita, rozpad, poslední pohyb, kvalita, zdroj) a
  `intermarket_souhrn` (potvrzuje / odporuje poslednímu pohybu zlata). Synchronizované
  korelace jsou autoritativní — starší odhady korelací (FRED řady, DXY z Krakenu) se při
  nich neuvádějí, aby AI nedostala dvě čísla pro jeden vztah. Nová AI role **mezitrh**
  (Groq Free, jen když Intermarket má data), hlavní analytik vidí souhrn a pravidlo: LONG/
  SHORT navazující na pohyb, kterému mezitrh odporuje, musí rozpor uvést v „proti“ nebo
  „rizicích“ s odkazem na fakt — FTI nesmí hledat jen potvrzení. Nezávislá kontrola nově
  hlídá i znaménko korelace (regrese: „EUR/USD … negativní korelace“ při r = +0,48).
  Karta „Mezitrh – vztahy se zlatem“ na detailu zlata (D1/H1), export pro mobil
  (`intermarket-D1/H1.json`). Ověřeno 8. 11. na kopii DB: 4 role, 22 447 tokenů, 191 s,
  NO TRADE s citací rozporu mezitrhu; kontrola vyřadila 3 chybné směry (makro), 2 špatně
  přiřazené korelace (mezitrh) a vymyšlenou úroveň ATR 40 (technika). Aktivace v živé FTI:
  `tools/intermarket_activation.py` (zkouška na kopii = „připraveno“; zapnutí jen se
  souhlasem). Zdroje bez MT5: FRED (S&P, VIX, výnosy, WTI, Brent; DTWEXBGS jen polední
  fixing), US Treasury, CBOE, EIA; Stooq vrací jen HTML (nepoužitelné), oficiální ICE DXY
  zdarma není → DXY* vzorcem ICE; Dukascopy dnes střídavě dostupný.
- **2026-11-08 — Výpadky Dukascopy jsou na straně poskytovatele; druhý zdroj forexu FXCM.**
  Diagnostika (DNS, TCP, TLS, HTTP, hlavičky, časy): `datafeed.dukascopy.com` → CNAME
  `datafeed.cloud.dukascopy.com` → HAProxy `datafeed.66proxymity88.net`. Adresy 16.62.187.25
  a 16.62.244.190 odpovídaly HTTP 503 „No server is available to handle this request“
  (HAProxy nemá za sebou žádný živý server), 194.8.15.180 končila timeoutem TLS handshaku.
  DNS, TCP i certifikát v pořádku, limit dotazů (429) se neobjevil. Stahovač FTI chybu nemá
  (pauzy 2/5/15/30 min, hotové soubory v mezipaměti, `complete_until`, pokračuje podle
  plánu). Oficiální JForex API (Java SDK) vyžaduje registraci u Dukascopy (aspoň demo
  účet s omezenou platností) a běžící Java klient — bez účtu nepoužitelné; FTI účty nezakládá. Řešení je redundance, ne další opakování dotazů.
  **FXCM** (`candledata.fxcorporate.com/{H1|m1}/{pár}/{rok}/{týden}.csv.gz`, zdarma, bez
  účtu): vlastní ceny FXCM (bid i ask), UTC, EURUSD, GBPUSD, USDJPY, USDCAD, USDCHF; zlato,
  SEK, indexy ani ropa tam nejsou; týden vyjde až po skončení → historie, ne poslední dny.
  Proti MT5 brokera: stejné začátky hodin 120/120, medián rozdílu 0,15–0,19 b. b. Čísla
  týdnů nesedí na jedno kalendářní pravidlo → FTI bere časy ze svíček. Provoz: vlastní
  rozpočet 30 souborů a 90 s za běh; hotový týden se stáhne jednou a pak už nikdy
  (nezveřejněný se zkusí znovu za 6 h); soubory z disku, které databáze ještě nemá, se uloží
  bez stahování (kopie DB, obnova ze zálohy); poškozený soubor nebo chybová odpověď vyřadí
  jen svůj pár, druhý selhaný pár = výpadek hostitele → konec běhu FXCM. Dukascopy a FXCM
  běží každý zvlášť (`run_all`) — výpadek jednoho nezastaví druhý; poškozený soubor
  Dukascopy vyřadí jen svůj trh. Intermarket bere **jednu řadu na trh**: nejčerstvější zdroj
  (o víc než 1 den, u D1 3 dny pozadu = zastaralý), pak pořadí Dukascopy → FXCM → oficiální
  uzávěrky → MT5; DXY* (vzorec ICE ze spotových kurzů, nově i z FXCM) před CFD na futures.
  Ostatní zdroje téhož trhu jsou „kontrola zdroje“ (r ≈ 1), ne další vztah — dřív byl
  EUR/USD v tabulce i v AI dvakrát. Ostatní kandidáti: Twelve Data (zdarma jen s klíčem
  uživatele; demo klíč dal EUR/USD a USD/JPY, ne XAU/USD a GBP/USD) — možná záloha
  aktuálních cen; Alpha Vantage a EODHD mají v bezplatné verzi příliš malé limity;
  „EV Trading Labs“ a „AlgoSpecial“ nejsou poskytovatelé dat.
- **2026-11-09 — Ú1: denní historie zlata bez MT5, svíčky na mřížce brokera.**
  Příčina, proč se denní technika bez MT5 nikdy nespočítala: denní svíčky Dukascopy vznikaly z 200 dní
  minutových souborů ≈ 140 obchodních dní (SMA200 potřebuje 210) a každý týden měly nedělní hodinový pahýl.
  Nově: starší historie z měsíčních hodinových souborů (`BID_candles_hour_1.bi5`, jeden soubor na měsíc,
  ptá se až 3 dny po konci měsíce, pak trvale v mezipaměti), minutové soubory jen po posledním takovém měsíci;
  D1/W1 = 15 měsíců ≈ 330 obchodních dní. **Mřížka brokera** (MT5 = New York + 7 h): obchodní den 17:00 → 17:00
  New York, pojmenovaný druhým datem; H4 uvnitř dne (17, 21, 01, 05, 09, 13 h NY); týden od soboty 17:00 NY.
  Časové pásmo `America/New_York` z tzdata → platí i historická pravidla USA (do 2006 konec října / začátek dubna).
  Hodiny a kratší rámce zůstávají na mřížce UTC (offset NY je v celých hodinách, takže se do dne vnoří).
  Chybějící měsíc = chybějící svíčky, včetně dní, které do něj zasahují (nic se nesešívá). Na hodiny zavřeného
  trhu se Dukascopy neptá (prázdná odpověď za posledních 3 h se dřív opakovala při každém volání).
  Migrace `2026-11-09_dukascopy_ny_close_grid`: staré D1/W1/H4 s mřížkou UTC přesunuty pod `dukascopy-utc`
  (nic se nemaže, ceny beze změny; starou a novou mřížku rozliší přesně násobek 4 h / 1 dne v UTC).
  Ověřeno na kopii provozní DB: 328 D1, 67 W1, 186 H4; časy svíček totožné s MT5 brokera (D1 327/327, W1 66/66,
  H4 185/185); kratší týdny jen 25. 12., 1. 1. a Velký pátek (MT5 je nemá také); H1 a H4 skládají D1 přesně
  (rozdíl 0,0000 $); SMA200, SMA50 a RSI14 (Wilder) se shodují s nezávislým přepočtem. Rozdíl závěru D1 proti
  MT5 (medián 0,41 $) je vlastnost okamžiku 17:00 NY: poslední H4 dne 0,42 $, ostatní H4 0,11–0,18 $, maxima
  0,14 $ — kotace banky a brokera se při uzavření dne rozcházejí víc, skládání svíček je v pořádku.
  Popisky dní (technika, DXY, korelace, graf) bere FTI z obchodního dne (`market_hours.trading_date`), ne z
  kalendářního data začátku svíčky — týká se i MT5 (pondělní svíčka se dřív ukazovala jako neděle).
  Denní techniku (SMA50/200, RSI14, MACD, denní podpory a rezistence) dostává nově i AI; kontrola hlídá hodnoty
  u SMA50, SMA200 a RSI14 stejně jako u EMA, ADX a ATR.
- **2026-11-09 — Ú2: režim trhu zlata (`app/market/regime.py`).** Deterministický modul ze vstupů, které FTI už
  má (trendy MTF, denní technika, GVZ, oficiální VIX/S&P/výnosy, DXY, Intermarket D1) — čistá funkce, takže ji
  historický test (Ú6) spočítá pro libovolný den. Dimenze a pevné prahy: trend (ADX D1 20/25 Wilder, H4 jako
  potvrzení), volatilita (**percentil ATR v % ceny** za 250 uzavřených dní — v dolarech by rok, kdy zlato zdražilo
  o třetinu, dělal z dneška „klid“; nalezeno na kopii: 84,6 USD = 19. percentil v USD, 24. v % ceny), riziková
  nálada (VIX 15/20/30, S&P 500 20 dní, souběh zlata s akciemi z 60denní korelace — teď +0,38, tedy zlato teď
  bezpečným přístavem v datech není), dolar (DXY D1 × W1), reálné výnosy (±0,15 p. b. za 20 dní), vztahy
  (Intermarket: rozpad / obrat). Volatilita jen z uzavřených dní (rozpracovaný den by percentil i spouštěč AI
  měnil každý cyklus). **Kontext, ne hlas:** pravidlový verdikt se nemění, dokud Ú6 neukáže, že režim pomáhá.
  Změna trendu, volatility, nálady nebo dolaru je důvod nové komplexní AI analýzy. AI fakta v oblasti „rezim“
  (role makro, technika, syntéza), `/api/regime`, `regime.json` pro mobil, karta „Režim trhu“ na detailu zlata.
  Výsledek Intermarketu starší než 3 dny se nepoužije.
- **2026-11-09 — Aplikace na PC běží přímo z repozitáře.** Uživatel otevřel FTI v 9:42 během práce na Ú1/Ú2:
  migrace Ú1 proběhla na provozní DB (jen přesun 350 starých svíček pod `dukascopy-utc`, nic smazáno) a provozní
  výpočet už má denní techniku a režim. Důsledek pro další práci: **každá uložená změna kódu je pro PC „nasazená“
  při příštím otevření FTI** — nové migrace jen s čerstvou zálohou a vratným postupem; rozpracované změny
  nenechávat v pracovním stromu mezi úkoly.
- **2026-11-09 — LIVE DATA ENGINE (testovací verze, vypnutá) pro XAUUSD, EURUSD, US500, NAS100.** Srovnání zdrojů:
  `docs/LIVE-DATA-ZDROJE.md` (skutečné testy bez klíče + porovnání s historií Purple MT5). XTB xAPI zrušeno
  14. 3. 2025. **Nejlepší zdroj = Purple cTrader Open API** (bezplatné, WebSocket JSON, ceny brokera uživatele, i z
  cloudu) — potřebuje demo účet cTrader u Purple a registraci aplikace, kterou FTI nezaloží. Do té doby **Deriv**
  (veřejný WebSocket bez klíče, ~1 snímek/s s bid/ask a časem kotace, stáří při příjmu 0,3 s; proti Purple: zlato
  medián 0,24 USD, EUR/USD 0,4 pipu). Deriv US 500 / US Tech 100 kotuje jen 6–21 h UTC a v hodině uzavření zamrzne
  (rozdíl proti CFD Purple až 338 bodů) → mimo seanci HISTORICAL, nikdy LIVE. Kraken EUR/USD (jiný trh, 2 pipy) =
  kandidát zálohy, který kontrolu shody neprojde.
  Engine (`app/live/`): normalizovaný tick (bid, ask, čas kotace, čas příjmu, zdroj, produkt); stav LIVE (≤ 15 s) /
  DELAYED (trh otevřený, zdroj mlčí ≤ 15 min) / HISTORICAL (zavřeno, mimo seanci zdroje, starší) / UNAVAILABLE;
  záloha převezme cenu jen po ověřené shodě (≥ 30 souběžných kotací, medián rozdílu ≤ tolerance instrumentu; ceny se
  nikdy neposouvají o změřený rozdíl); svíčky M1–D1 na mřížce brokera z Ú1, každý zdroj svou historii (Deriv = střed
  bid/ask, `provider = deriv`); historie Deriv (M1 ~3,5 dne, H1 ~7–11 měsíců) jen jako začátek svíček, ne do DB;
  ticky po minutových blocích ve vlastní tabulce `live_tick_blocks` (vznikne až při zapnutí, 30 dní); změna ceny proti
  předchozímu závěru TÉHOŽ zdroje; monitoring zdrojů do stránky Data (`live:deriv`, `live:kraken`); SSE stream,
  stránka „Živě“. **Brána AI:** když engine běží a cena není LIVE, FTI LONG / SHORT nevydá (přepíše na NO TRADE
  s důvodem); fakt „Živá cena“ se stavem. Vypnuto (`live.enabled = false`) — zapnutí mění provozní DB a chování AI,
  proto až se souhlasem. Cloud bez PC: stejná logika jako Cloudflare Durable Object (free 13 000 GB-s/den) — vyžaduje
  nasazení, tedy souhlas.
  Ověřeno 9. 11. na kopii provozní DB (5 min skutečného streamu, 10:15–10:20 SEČ): všechny 4 instrumenty LIVE, Deriv
  1 159 ticků, latence medián 0,27 s / 95 % 0,36 s, 0 odpojení; živé svíčky M1 = vlastní historie Deriv za stejné minuty
  (rozdíl 0, u zlata 0,005 zaokrouhlením středu); 0 svíček mimo mřížku brokera, 0 duplicit; Kraken jako záloha EUR/USD
  odmítnut (210 souběžných kotací, medián rozdílu 3,2 pipu > 1,5). Nalezeno a opraveno: historie Deriv má jen ~1 den M1
  a ~6 týdnů H1 a začíná nezarovnaně (17:21:15) → useknuté první svíčky se vynechávají; při zastavení se ukládá i
  rozpracovaná minuta ticků. Stránka „Živě“ ověřena v prohlížeči nad kopií (ceny se mění bez obnovení, telefon bez
  přetékání, menu „Živě“ jen v aplikaci na PC).
- **2026-11-09 — Nové závazné zadání [fti-research.md](fti-research.md); kde je rozpor, platí zadání.** Pravidla stavby
  zapsána do `CLAUDE.md` v kořeni repozitáře. Hned upraveno v živém enginu na PC: svíčky z **bid** (dřív střed;
  svíčky Deriv ze středu přesunuty pod `deriv-mid`), **ticky ne do databáze** (hodinové soubory
  `cache/ticks/…/<instrument>@<zdroj>.jsonl.gz`, 30 dní; tabulka `live_tick_blocks` se už nezapisuje), **kontrola
  kotace** (bid > 0, ask ≥ bid, maximální spread instrumentu, skok > 5 × ATR(M1) jen po potvrzení 3 kotacemi; po
  pauze skok povolen), **MARKET STATUS z rozvrhu ≠ DATA STATUS z kotací** (LIVE / DELAYED = spojení je, kotace starší /
  UNAVAILABLE = bez spojení / HISTORICAL = jen uložená cena) a banner **„TRH OTEVŘEN – DATA NEAKTUÁLNÍ“**, **NO TRADE
  bez živé ceny rozhoduje kód před voláním AI**. Svíčky po restartu navazují na vlastní uložené svíčky zdroje (ne na
  historii Deriv ze středu). Ve shodě se zadáním a beze změny: hranice dne 17:00 NY a H4 zarovnané k ní (Ú1), jedna
  funkce `bucket` pro historii i živá data, Actual z oficiálních zdrojů, syntetický DXY vzorcem ICE, korelace
  výnosů se synchronizací, Fisherovým intervalem a rozpadem (Intermarket). W1: zadání „od neděle 17:00 NY“, FTI
  počítá týden od soboty 17:00 NY (čas svíčky jako MT5) — obsah svíčky je stejný, protože mezi tím trh neobchoduje.
  Rozpory odložené do svých etap podle zadání: AI bez čísel (odkazy `{{…}}`), stav NEUTRAL, režim podle ADX + ER +
  Choppiness + percentilů (Ú2 bude přepracován), fundamentální skóre −10 … +10 z 5–6 složek, tmavý terminál
  s Lightweight Charts, Cloudflare Access, cloudový `MarketStream` Durable Object s Capital.com jako hlavním zdrojem.
  Zdroje podle zadání: **Capital.com demo = hlavní**, OANDA = záloha 1, cTrader = záloha 2 (adaptér hotový), Deriv
  zůstává jako zdroj bez účtu, dokud Capital.com nepoběží.
