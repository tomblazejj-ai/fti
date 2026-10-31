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

## Modul 6 — metodika Funded Mind / Trading Analyzer (2026-10-06)

Zdroj: 20 PDF ve složce Plocha → „Fundament Funded mind“ (Jan Šrajer, Daniel
Valchář). Souhrn a mapa „co je kde v aplikaci“: `docs/metodika/METODIKA.md`.
Pravidlo uživatele: **nic nepřepisovat, jen rozšířit** — všechny dosavadní
panely zůstávají, nové jsou vedle nich.

- **Skóre podle metodiky = součet 11 kategorií (±25).** Rozsahy přesně podle
  „Score overview“: COT ±3, retail ±1, sezónnost ±2, HDP ±2, inflace ±3, trh
  práce ±4, sazby ±2, PMI služby ±2, PMI průmysl ±2, tržby ±2, trend ±2.
  Makro kategorie se počítají pro USD a u XAU/USD mají opačné znaménko. PDF
  dávají rozsahy a směr vlivu, ne vzorce — prahy jsou naše, pevné a vypsané u
  každé položky (`app/market/tra.py`).
- **Náhrady placených dat (vždy označené „≈“ v UI).** ISM/S&P PMI → regionální
  průzkumy Fedu (NY, Philadelphia, Dallas; FRED). Brokerský retail sentiment →
  „malí obchodníci“ z CFTC COT. Pravděpodobnosti sazeb (FedWatch) → 2letý
  výnos vs. efektivní sazba Fedu. COT dolaru = CFTC TFF „USD INDEX - ICE“,
  skupina leveraged funds (přesně ta, kterou čte metodika).
- **Historie skóre se rekonstruuje se zpožděním zveřejnění.** Každá řada FRED
  má svůj typický odstup zveřejnění; zpětný bod smí použít jen data, která už
  byla venku. Rok historie se dopočítá při prvním spuštění, později jen díry,
  kdy aplikace neběžela (> 36 h). Živé body: při změně, jinak 1× za hodinu.
  V grafu je rozlišeno „živě“ vs. „rekonstrukce“.
- **Chybějící měsíc v datech USA (říjen 2025, shutdown).** FRED tam nemá CPI
  ani nezaměstnanost. Meziroční změny se proto počítají podle data, ne podle
  pozice v řadě, a jeden chybějící měsíc se překlene průměrem sousedů. Dřív
  se tím 12měsíční změna tiše počítala za 13 měsíců.
- **Momentum.** Změna za 24 h / 7 / 30 dní; obchodní nápad při změně ≥ 2 body
  za 24 h; modelová situace 1 (cena v pásmu, skóre se hýbe) a 2 (divergence
  ceny a skóre) s pevnými prahy v `momentum.py`.
- **Pravidlo 2 hodin.** Čas FOMC = 14:00 New York přepočtený na Prahu (kvůli
  různým přechodům na zimní čas 28. 10. = 19:00, jinak 20:00). Odpočet běží v
  prohlížeči; po zprávě 60 min „čekej na potvrzení“.
- **Detail události.** Frekvence, proč to trh sleduje, obvyklý vliv na dolar a
  zlato, posledních 6 hodnot z oficiální řady FRED (CPI, NFP, PCE, HDP, PPI,
  JOLTS, tržby, žádosti, ECI, sazba Fedu). Konsenzus trhu zdarma není → dál
  „n/a“.
- **Headline risk.** Klíčová slova v titulcích za 12 h + neobvykle velká
  svíčka M15 (≥ 3× medián) + blížící se víkendové uzavření. „Vysoké“ jen při
  svíčce nebo když o tématu píše víc zdrojů do 3 h — samotná slova často
  chytí i nesouvisející zprávy (proto UI říká, že jde o filtr).
- **Sezónnost 5/10/15 let ze Světové banky.** Pink Sheet (CC BY 4.0, zdarma,
  bez klíče); odkaz se mění s každou aktualizací, proto se čte z oficiální
  stránky. Měsíční průměry cen → vhodné na sezónnost, ne na úrovně. Dolar ze
  stejného vzorce DXY z kurzů ECB od 1999. Stará sezónnost z PAXG zůstává.
- **DXY: úrovně, filtr, zrcadlo, koš.** Úrovně z denních svíček DXY stejnou
  metodou jako u zlata; zrcadlo = zlato do 0,8 % od rezistence/supportu a DXY
  do 0,35 % od opačné úrovně, jen při záporné korelaci.
- **Metodika v aplikaci.** Stránka „Metodika“ čte složku jen lokálně (název,
  velikost, SHA-256 — nic se nikam neposílá). Seznam zapracovaných souborů:
  `backend/app/data/metodika.json`; nový nebo změněný soubor se ukáže jako
  „nový — zatím nezapracováno“.

## Modul 7 — Pomocník podle videa o swingové strategii (2026-10-17)

Uživatel poslal přepis videa o swingové strategii Funded Mind (autor Trading
Analyzeru) a sedm PDF. Všechna PDF jsou bajt po bajtu stejná jako ta už
zapracovaná (ověřeno SHA-256). Video přineslo nové prvky. Zároveň uživatel
chtěl „víc zjednodušit, ať nemusím nic hledat, má to být můj pomocník“ a
výrazně posunout design.

- **Hlavní obrazovka = Pomocník.** Odpověď jednou větou, checklist setupu,
  obchodní plán (vstup, SL, cíl, R:R), graf se zónami, plán na týden a šest
  dlaždic s odkazem do detailu. Původní přehled trhů je na `#/trhy` (odkaz
  dole), detailní rozbor zlata zůstal celý. Panel „Denní rutina“ z rozboru
  nahradil checklist v Pomocníku.
- **Supply/demand zóny (týdenní → denní).** Zóna = malá základna před
  prudkým pohybem (≥ 1,25× ATR během 1–3 svíček), platí, dokud ji
  DOKONČENÁ svíčka neprorazí závěrem. Denní zóna uvnitř týdenní = upřesnění.
  Pevná pravidla v `app/market/zones.py`, ATR(14) daného timeframu.
- **Objem → čas na ceně (TPO).** Video čte objem z futures (POC). Objem
  futures zdarma ani legálně bez registrace k dispozici není, proto profil
  času na ceně ze svíček. V aplikaci je to vždy napsané.
- **Checklist a známka.** Šest bodů (týdenní zóna, denní zóna, aktivita,
  skóre, COT, sezónnost). A+ = 6/6, A = 5/6, B = 4/6, C = méně nebo zóna
  bez aktivity. „Nech být“, když skóre, COT i sezónnost jdou proti (věta z
  videa). Načasování navíc: 2 h před červenou zprávou a víkend.
- **Plán.** Vstup na hraně zóny, SL za vzdálenou hranou + 0,25× denní ATR,
  cíl = nejbližší protější zóna. Je to plán podle pravidel, ne doporučení.
- **COT u zlata: commercials a open interest.** Podle videa se u komodit
  čtou commercials (producenti a banky se zajišťují). 3letý index ≥ 90 / ≤ 10
  přidá ±1 do kategorie COT. Pokles open interestu o ≥ 3 % za 4 týdny
  oslabí tok fondů o jeden stupeň (zavírání pozic). Kvůli změně pravidel
  `tra.MODEL_VERSION = 2`: uložená historie skóre se přepočítá celá novými
  pravidly, aby graf nemíchal dva modely.
- **Denní zlato od 2013 z NBP.** Pro sezónní okna („od 11. 9. do 9. 10.“)
  jsou potřeba denní data za 10 let. Bundesbank řadu zlata v USD už nemá,
  Kraken má 2 roky. Polská centrální banka (api.nbp.pl, veřejné API bez
  klíče) publikuje cenu zlata v PLN/g; s kurzem USD/PLN téhož dne → USD/oz.
  Ověřeno: 16. 10. 2026 = 4 164 $, spot ~4 160 $. Historie se ukládá do
  `backend/cache/` a dál se stahují jen nové dny.
- **Sezónní okna.** Stejné kalendářní dny v posledních 10 letech, okna 14–42
  dní začínající do 3 týdnů. Zmíní se, jen když jde ≥ 7 z 10 let stejným
  směrem a průměr je aspoň 1 % (u dolaru 0,5 %). Linka „15 let“ se ukáže jen
  při skutečných ~15 letech dat (u zlata z NBP je jen 13).
- **Design.** Panely s nasvíceným okrajem, nová navigace s ikonami, hero
  s barvou podle směru, prstenec potvrzení, cenový žebřík plánu, zóny přímo
  v grafu. Animace respektují „omezit pohyb“.

## Modul 8 — Market Intelligence: všechny trhy, jednodušší, mobil (2026-10-31)

Zadání uživatele: platforma jako „Market Intelligence“ od ForexNation (seznam
trhů se skóre −10 až +10, detail s argumenty, riziky, „co dál sledovat“, retail
sentiment) + to, co už máme; zrušit korelace; mnohem jednodušší; mobilní
aplikace pro obchodování ve vlaku a ve škole. Vše zdarma.

- **Pět trhů:** XAU/USD, EUR/USD, GBP/USD, USD/JPY, ropa WTI. Hlavní obrazovka
  = přehled (seznam + detail vybraného), detail trhu = skóre, argumenty pro,
  protiargumenty a rizika, co dál sledovat, retail sentiment, rozpis skóre,
  graf, zprávy. Zlato si nechává skóre Funded Mind (±25 → přepočet na ±10) a
  obchodní plán (Pomocník je teď v menu „Zlato“).
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
  (`app/market/central_banks.py`, zkopírováno z jejich stránek 31. 10.) a
  kalendář dat USA. Názvy událostí přes slovník do češtiny; strojový překlad
  krátkých názvů byl nečitelný, neznámé zůstávají anglicky.
- **Retail sentiment = malí obchodníci z CFTC** (non-reportable). Brokerská
  data (Myfxbook, IG, DXM) zdarma bez registrace a bez scrapování nejsou.
  Sentiment neovlivňuje skóre, jen ho komentuje (kontrariánsky).
- **Zrušeno na přání uživatele:** korelace (výpočet i panely), záložka DXY,
  původní přehled trhů s „připravujeme“, ticker S&P/VIX/ropa z FRED, Bitcoin.
- **Mobil:** stejná webová aplikace jako PWA (manifest, ikona, offline přes
  service worker). Statický snímek všech API odpovědí
  (`python -m app.export_static <složka> --cycle`) + build s `VITE_STATIC=1`
  běží bez serveru; živé ceny bere telefon přímo z Krakenu (CORS povoleno).
  Hosting zdarma: GitHub Actions + GitHub Pages (`.github/workflows/mobil.yml`,
  každých 30 minut). Vyžaduje bezplatný účet uživatele na GitHubu a veřejný
  repozitář — rozhoduje uživatel, nic se nezveřejňuje bez jeho souhlasu.
