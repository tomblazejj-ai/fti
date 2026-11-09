# FTI — pravidla pro práci na projektu

FTI (Financial Trading Intelligence) je osobní analytický systém pro **manuální obchod XAU/USD** (dál EUR/USD, US500,
NAS100). Z ověřených dat skládá rozhodovací podporu LONG / SHORT / NEUTRAL / NO TRADE. Sám nikdy neobchoduje.
Tři vrstvy: **data** (kód) → **výpočty** (kód) → **interpretace** (AI vykládá hotová čísla). Aplikace na PC (Python
FastAPI + SQLite `backend/fti.db`, React/Vite), cloud = Cloudflare Worker `fti` + D1 (Free) + GitHub Actions.

## Stav projektu (načte se při každém startu)

@docs/PROGRESS.md

## Dokumenty a pořadí platnosti

1. `docs/fti-master-spec.md` — **master specifikace (nejnovější, má přednost)**: cTrader, živé grafy M1–MN1, více zdrojů,
   technika + SMC, MTF, fundament, AI analytik, validace AI, Data Quality, fáze 1–8.
2. `docs/fti-spec.md` — produktová specifikace (etapy 1–10, kritéria HOTOVO L1/L2/L3).
3. `docs/fti-research.md` — technický návod, jak věci postavit.

- Kde si odporují, platí master spec. **0 Kč má přednost před všemi třemi.**
- Hlavní změna master spec: **primární živý zdroj = cTrader Open API (Purple Trading demo)**, ne Capital.com.
  Dukascopy zůstává pro historii (a backtest, validaci), MT5 jen jako nepovinný doplněk (jen čtení).
- Dokumenty jsou dlouhé: **neimportovat celé**. Při práci na modulu přečíst jen jeho kapitolu.
- Audit a plán fází: `docs/gap-analysis.md`.
- Další: `docs/DECISIONS.md` (deník rozhodnutí), `docs/NAKLADY.md` (co by mohlo stát peníze), `docs/LIVE-DATA-ZDROJE.md`.
  `docs/STAV-FTI.md`, `docs/AUDIT-*`, `docs/REPORT-*` jsou historie; zdroj pravdy o stavu je `docs/PROGRESS.md`.

## Tvrdá pravidla

1. **0 Kč, vždy.** Žádná placená služba, API, AI, hosting, doména ani platební karta či jiná platební metoda — ani
   „jen na ověření“. Vyčerpaný bezplatný limit = bezpečná pauza (u AI výsledek NO TRADE „AI nedostupná“), nikdy placená
   náhrada. Co v průzkumu vyžaduje kartu, se nepoužije a nahradí: Cloudflare Access → vlastní přihlášení; R2 → soubory;
   OpenRouter kredity, Cerebras, Workers Paid → ne. Každou novou službu nejdřív prověřit, jestli nechce kartu.
2. **Žádné automatické obchodování, brokerské integrace jen READ-ONLY.** FTI nikdy neposílá obchodní příkaz (otevření,
   uzavření, úprava pozice), nemění účty ani obchodní nastavení; cTrader jen scope „accounts“ (čtení), MT5 jen čtecí funkce.
   Funkce pro exekuci se neimplementuje ani „pro budoucnost“.
3. **AI nikdy nepíše ani nepočítá čísla.** Čísla počítá kód, AI je vykládá. Validátor (kód) kontroluje, že každé číslo
   ve výstupu AI je ve vstupních datech; cíl: AI píše jen odkazy typu `{{tech.H1.rsi14}}`, čísla dosadí kód.
4. **Nic nevymýšlet.** Chybějící data = `UNAVAILABLE` / „zatím nedostupné“, nikdy odhad nebo doplnění. Zastaralé nebo
   proxy hodnoty vždy označené (DELAYED, HISTORICAL, CFD, syntetický DXY). Žádné pravděpodobnosti bez backtestu.
5. **Ticky se neukládají do D1 ani do SQLite.** Ukládají se svíčky od M1 výš; syrové ticky jen jako soubory
   (`backend/cache/ticks/`, hodinové dávky). Minuta bez ticku = žádná svíčka; mezera se zaznamená, nedoplní.
6. **Jedna funkce `bucketStart`** pro hranice svíček historie i živých dat (Python `app/connectors/dukascopy.bucket`,
   v cloudu `bucketStart`). D1/W1 končí 17:00 New York (zóna `America/New_York`, nikdy pevný posun), H4 zarovnané k 17:00 NY.
   Svíčky se staví z **bid**; ask a spread zvlášť.
7. **Bez živé ceny žádný obchodní signál** — kód rozhodne NO TRADE ještě před voláním AI a uvede důvod.
8. **Stav trhu ≠ stav dat.** MARKET STATUS z rozvrhu instrumentu (a stavu u brokera), DATA STATUS z kotací
   (LIVE ≤ 15 s / DELAYED / UNAVAILABLE / HISTORICAL). Trh otevřený + data neaktuální = banner
   „TRH OTEVŘEN – DATA NEAKTUÁLNÍ“.
9. **Instrument = zdroj + symbol** (`XAUUSD@CTRADER`). CFD kotace se nikdy nevydává za oficiální index ani „spot zlato“.
   Záloha převezme cenu jen po ověřené shodě s hlavním zdrojem.
   **Zdroje se nesmíchají do jedné svíčky** — každá svíčka má jeden zdroj; historie Dukascopy a živá cena Purple se nespojí
   do jedné zdánlivě jednotné řady bez viditelného upozornění.
10. **Skóre není pravděpodobnost.** Žádné „75 % na růst“, dokud model neprojde historickým testem a kalibrací.
11. **Submitted neznamená schváleno.** Neověřené API, oprávnění ani data se nepředstírají; integrace se připraví tak, aby šla
    otestovat po schválení bez přepisování.
12. **Nepřepisovat fungující moduly.** Opravovat adresně, navázat na existující kód a testy (Dukascopy, MT5 zachovat).
    Žádná druhá paralelní databáze bez důvodu.
13. **Před rizikovou změnou produkce záloha** (DB, nastavení, cloudová data) a vyzkoušený návrat.

## Tajné údaje (secrets)

- Lokálně jen v `backend/.env` a `cloud/worker/.dev.vars` — oba v `.gitignore`. Zadává je uživatel na stránce Zdroje dat
  (nikdy přes chat).
- V cloudu jen přes `wrangler secret` (Worker) nebo GitHub Secrets — nikdy v `wrangler.jsonc`, repu ani na GitHubu.
- **Nikdy ve frontendu** (API vrací jen „nastaveno ano/ne“), **nikdy v logu** ani v chybové hlášce.
- Refresh tokeny ukládat bezpečně (stejně jako klíče, nikdy do DB exportované do cloudu).

## Jedna verze všude (pravidlo uživatele 9. 11. 2026)

- **Zdroj pravdy je cloud** (`cloud.url` z konfigurace, dnes `fti.tomblazejj.workers.dev`). Uživatel FTI používá jen přes
  webovou adresu; lokální verze na PC je jen pro vývoj.
- PC i mobil = **stejná webová aplikace (PWA)**, stejný vzhled i funkce. Žádný druhý frontend, žádné funkce jen pro PC.
  Rozdíl smí být jen v tom, co server zatím umí — a ten se v aplikaci ukáže jako „zatím nedostupné“.
- V patičce vždy verze: commit a datum buildu.
- Nic natvrdo svázané s `workers.dev`: adresy, CORS, přesměrování i návratová adresa cTraderu z konfigurace
  (počítá se s vlastní doménou).
- Nastavení a data uživatele (téma, sledované instrumenty, deník …) na serveru v D1, v prohlížeči jen jako mezipaměť.

## Provoz a souhlasy

- **Nasazení do cloudu po každém dokončeném a otestovaném kroku** (build i testy prošly) — souhlas uživatele 9. 11. 2026.
  Před nasazením záloha D1 (export + Time Travel), migrace jen přidávací a s vyzkoušeným návratem.
- Bez výslovného souhlasu uživatele: změna provozní databáze mimo bezpečnou migraci, smazání dat, nová služba.
- Lokální historie gitu obsahuje e-mail uživatele → **nikdy ji nepushovat**. Veřejný strom se publikuje přes
  `git commit-tree` na ref `github-publish` (autor `tomblazejj-ai <tomblazejj-ai@users.noreply.github.com>`) a **bez**
  `docs/VIZE.md`, `docs/fti-master-spec.md`, `docs/fti-spec.md`, `docs/fti-research.md`, `docs/gap-analysis.md`,
  `docs/PROGRESS.md` a `docs/REPORT-*` (osobní dokumenty a stav projektu).
- Aplikace na PC běží přímo z tohoto repozitáře: uložená změna backendu se projeví po restartu FTI, změna frontendu
  po sestavení `frontend/dist`. Nové chování, které mění provozní DB, je ve výchozím stavu vypnuté.
- E-mail a osobní údaje uživatele nikam neposílat (výjimka: přihlášení Capital.com jen do API Capital.com).
- Neprovádět automatické spouštění MT5 ani změny jeho profilů.
- Testy nikdy nečtou nastavení uživatele ani nespouští živý engine (`backend/tests/conftest.py`).
- Wrangler: přihlásit jen s `--device --scopes account:read user:read workers_scripts:write d1:write`, po práci `logout`.

## Postup u každé úlohy

1. Na začátku zkontrolovat `docs/PROGRESS.md` (stav, další kroky, známé problémy) a závislosti úlohy.
2. Přečíst kapitolu master spec (a případně specifikace a průzkumu) k danému modulu.
3. Implementovat, otestovat (`backend`: `.venv/Scripts/python.exe -m pytest -q`; `frontend`: `npm test`), ověřit na
   kopii DB nebo v provozu podle rizika.
4. Stav psát jen podle ověření v kódu a datech: NEZAČATO / ROZPRACOVÁNO / L1 IMPLEMENTACE / L2 INTEGRACE /
   L3 PROVOZ (= HOTOVO). Co nejde ověřit = „neověřeno“.
5. Po dokončení aktualizovat `docs/PROGRESS.md` (tabulka, další kroky, problémy, řádek do Logu), commitnout a poslat
   uživateli krátké shrnutí.

## Komunikace

- Česky, srozumitelně pro obchodníka, ne programátora; žádné příkazy do konzole pro uživatele.
- Neříkat „hotovo“ bez důkazu z provozu. Neúspěchy a vynechané kroky říct přímo.
