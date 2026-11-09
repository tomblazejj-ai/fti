# FTI — pravidla pro práci na projektu

Závazné zadání: [docs/fti-research.md](docs/fti-research.md) (technický průzkum 9. 11. 2026). Kde se s dosavadním
stavem shoduje, nic se nemění; **kde je rozpor, platí toto zadání** (rozhodnutí uživatele 9. 11. 2026).
Stav a úkoly: [docs/STAV-FTI.md](docs/STAV-FTI.md). Deník rozhodnutí: [docs/DECISIONS.md](docs/DECISIONS.md).

## Pravidla stavby (ze zadání)

- **AI nepočítá ani nepíše čísla.** Čísla počítá kód; AI je vykládá. Validátor (kód) kontroluje, že každé číslo ve
  výstupu AI existuje ve vstupních datech; cílový stav: AI píše jen odkazy typu `{{tech.H1.rsi14}}`, čísla dosadí kód.
- **Bez živé ceny žádný obchodní signál** — rozhoduje kód ještě před voláním AI (NO TRADE s důvodem).
- **Ticky se do databáze neukládají**, ukládají se svíčky od M1 výš. Syrové ticky jen jako soubory (hodinové dávky).
- **Jedna funkce pro hranice svíček** pro historii i živá data (`app/connectors/dukascopy.bucket`, v cloudu `bucketStart`):
  D1 a W1 podle 17:00 New York (zóna `America/New_York`, nikdy pevný posun), H4 zarovnané k 17:00 NY.
- **Svíčky se staví z bid** (jako grafy brokera); ask a spread zvlášť.
- Minuta bez ticku = žádná svíčka; mezera se zaznamená, nikdy nedoplní.
- **Stav trhu ≠ stav dat:** MARKET STATUS z rozvrhu instrumentu (a stavu u brokera), DATA STATUS z kotací
  (LIVE / DELAYED / UNAVAILABLE / HISTORICAL). Trh otevřený + data neaktuální = banner „TRH OTEVŘEN – DATA NEAKTUÁLNÍ“.
- Každý instrument = zdroj + symbol (`XAUUSD@CAPITAL`); brokerová CFD kotace se nikdy nevydává za oficiální index
  ani „spot zlato“. Záloha převezme cenu jen po ověřené shodě s hlavním zdrojem; svíčky dvou zdrojů se nespojují.
- **0 Kč:** žádné placené služby, API, AI, hosting, platební karta. Limity bezplatných tarifů v konfiguraci, ne v kódu.
- FTI nikdy neobchoduje. Brokerová data jen pro osobní použití uživatele — aplikace za přihlášením, ceny ne veřejně.

## Pravidla provozu (od uživatele)

- Bez výslovného souhlasu žádný GitHub push, nasazení do cloudu ani změna provozní databáze; před změnou provozu
  záloha a vyzkoušený návrat. Veřejný strom se publikuje bez `docs/VIZE.md`, `docs/fti-research.md` a `docs/REPORT-*`
  (osobní dokumenty) a nikdy s historií obsahující e-mail uživatele.
- Aplikace na PC běží přímo z tohoto repozitáře: uložená změna je „nasazená“ při příštím otevření FTI. Nové chování,
  které mění provozní DB, je ve výchozím stavu vypnuté.
- E-mail a osobní údaje uživatele nikam neposílat; klíče jen v `backend/.env` (zadává je uživatel v aplikaci).
- HOTOVO = implementováno, propojeno a ověřeno ve skutečném provozu. Před každým úkolem zkontrolovat závislosti.
- Testy nikdy nečtou nastavení uživatele ani nespouští živý engine (conftest).
- Komunikace s uživatelem česky, srozumitelně pro obchodníka, ne programátora.
