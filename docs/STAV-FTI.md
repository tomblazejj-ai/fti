# FTI — skutečný stav a zbývající práce

Živý dokument: inventura k 8. 11. 2026 22:30, aktualizováno 9. 11. (Ú1 hotov). Po každém dokončeném úkolu se tady přepíše stav.
Zdroj pravdy je provozní databáze na PC (čteno jen pro čtení), cloud (`fti.tomblazejj.workers.dev`) a kód.

**HOTOVO** = implementováno, propojené s ostatními moduly a ověřené v reálném provozu na skutečných datech.
Kód nebo zelené testy samy nestačí.

## 1. Inventura modulů

| # | Modul | Stav | Co skutečně běží (důkaz) | Propojení | Cloud | Co chybí / nefunguje |
|---|---|---|---|---|---|---|
| 1 | Cena a svíčky zlata | **HOTOVO** (Ú1, provoz od 9. 11.) | Dukascopy M15–W1; D1 328 svíček (15 měsíců) na mřížce brokera, časy totožné s MT5 | technika, MTF, AI, graf | ne (nasazení Ú7) | v cloudu se měsíční soubory doplní za ~5 běhů po nasazení |
| 2 | Forex a mezitržní data | **HOTOVO na PC** | FXCM 61 896 svíček (5 párů), FRED/Treasury/CBOE/EIA/ECB denně do 6. 11. | Intermarket, DXY* | jen oficiální denní | Dukascopy vnitrodenně nestabilní (poskytovatel) |
| 3 | MT5 (jen čtení) | HOTOVO jako volitelný | 72 995 svíček, terminál teď neběží | zlato, kontrola zdrojů | ne (Windows) | — (záměrně volitelný) |
| 4 | Fundamentální model, TRA, verdikt | **HOTOVO** | 650 snapshotů skóre, 616 TRA, každý cyklus | AI, přehled, mobil | ano | Actual/překvapení se do modelu nepromítají |
| 5 | Makro data (FRED, ECB, ONS, Eurostat, MOF) | **HOTOVO** | cache 8. 11. 19:56 | model, kalendář | ano | — |
| 6 | Ekonomický kalendář + Actual | **ČÁSTEČNĚ** | Forex Factory každý cyklus; Actual v2: 8 hodnot (6 ověřeno u BLS) | AI (události), trigger AI | kalendář ano, Actual v2 ne | Actual/překvapení ne v AI ani modelu; mimo USD nic; Myfxbook měření út 10. 11. |
| 7 | Zprávy (GDELT, RSS, překlad, riziko titulků) | **HOTOVO** | 2 630 zpráv, poslední 19:50 | AI, trigger AI | ano | FXStreet RSS vrací 403 |
| 8 | COT, sezónnost, GVZ | **HOTOVO** | v každém snapshotu | AI, model | ano | — |
| 9 | Intermarket Intelligence | **TÉMĚŘ HOTOVO** | zapnuto 8. 11.; 1 běh nad provozní DB (51 s, D1 10 trhů, H1 6) | AI role „mezitrh“, karta, export | ne | ještě neproběhl uvnitř cyklu otevřené aplikace; v cloudu chybí |
| 10 | Technika — trendy MTF | **HOTOVO** | M15/H1/H4/D1/W1 v každém snapshotu | AI, verdikt, trigger | ano | — |
| 11 | Technika — denní (SMA50/200, RSI, úrovně) | **HOTOVO** (Ú1) | provozní výpočty 9. 11. 8:44 a 8:48 UTC: D1 z Dukascopy 328 svíček, SMA200 4 456,59, RSI14 47,2 (= nezávislý přepočet) | verdikt, podmínky, AI fakta, graf | ne | nový frontend (popisky dní v grafu) na PC ještě nesestaven |
| 12 | Struktura trhu, zóny, FVG, likvidita | CHYBÍ | prázdné tabulky `user_zones`, `zone_events` | — | — | celé |
| 13 | Režim trhu (Market Regime) | **TÉMĚŘ HOTOVO** (Ú2) | provozní výpočet 9. 11. 8:48 UTC (`/api/regime` 200), ověřeno na kopii celým cyklem | AI (oblast „rezim“), spouštěč AI, API, mobil, karta | ne | provozní FTI běží s verzí před opravou volatility (restart FTI); karta se ukáže po sestavení frontendu na PC |
| 14 | AI analýza a Trading Advisor | **ČÁSTEČNĚ** | cloud: 1 komplexní analýza 8. 11. 14:33 (NO TRADE, stará verze); PC: automatika vypnutá, 0 komplexních analýz | čte vše výše, panel v aplikaci | ano (bez role mezitrh) | odpověď nové verze na kopii neprošla kontrolou (vymyšlená čísla) → „neověřená“ |
| 15 | Kontrola AI (čísla, atribuce, směr, znaménko) | **HOTOVO** | zachytila skutečné chyby v odpovědích 8. 11. | AI pipeline | starší verze | — |
| 16 | AI více modelů | ČÁSTEČNĚ | jen Groq Free (gpt-oss-120b/20b) | router | ano | Gemini / Mistral / Workers AI bez klíčů uživatele |
| 17 | Řízení rizika | CHYBÍ | jen nastavení (účet 10 000 USD, 1 %) | — | — | velikost pozice, brána událostí, limity |
| 18 | Watchlist, upozornění | CHYBÍ | prázdné tabulky | — | — | celé |
| 19 | Historická validace | CHYBÍ | `backtests` prázdná; point-in-time umí jen Intermarket a Actual | — | — | celé |
| 20 | Aplikace na PC | **HOTOVO** | launcher, stránky Přehled/Detail/Kalendář/Zprávy/Data, frontend sestaven 8. 11. 20:13 | vše | — | cyklus jen při otevřeném okně |
| 21 | Cloud bez PC (Actions + Worker + D1 + mobil) | **HOTOVO, starší verze** | běh každých 30 min, poslední 21:06 UTC, 0 problémů | mobil | `9967ab4` | o 21 commitů pozadu (čeká na souhlas) |
| 22 | Monitoring zdrojů, stránka Data | **HOTOVO** | 39 zdrojů, poslední kontrola 19:49 | — | ano | — |
| 23 | LIVE terminál (XAUUSD, EURUSD, US500, NAS100) | **TESTOVACÍ VERZE, VYPNUTÁ** | kopie provozní DB, 5 min skutečného streamu: 4× LIVE, latence 0,27 s (95 % 0,36), 0 výpadků, M1 = historie Deriv (rozdíl 0), 0 duplicit, Kraken jako záloha odmítnut (3,2 pipu) | AI brána, API, stránka „Živě“, monitoring | ne | zapnutí (souhlas); Purple cTrader (váš demo účet + aplikace); cloud (Durable Object, souhlas) |

## 2. Kde se dnes celek přerušuje

Cíl: každých 30 minut (i při vypnutém PC) data → technika + makro + mezitrh + režim → AI s ověřenou odpovědí →
LONG / SHORT / NO TRADE se scénáři, rizikem a velikostí pozice → aplikace a mobil. Řetěz se přerušuje na:

1. ~~denní technika zlata (modul 11) — chybí bez MT5~~ → Ú1 hotov, ověřeno na kopii;
2. ~~režim trhu (13) — neexistuje~~ → Ú2 v provozu (restart FTI a frontend na PC);
3. AI odpověď (14) — často neprojde kontrolou;
4. riziko (17) — neexistuje;
5. cloud (21) — běží starší verze;
6. historická validace (19) — neexistuje, takže nikdo neví, jestli verdikt něco umí.

## 3. Zbývající práce (pořadí podle závislostí)

| Úkol | Co přesně | Hotovo, když | Závisí na |
|---|---|---|---|
| **Ú1** Dlouhá denní historie zlata bez MT5 | D1/W1 z měsíčních hodinových souborů Dukascopy (jeden soubor na měsíc, trvale v mezipaměti), den končí v 17:00 New York jako u brokera (bez nedělních pahýlů) | provozní snapshot má `technical` ≠ null z Dukascopy, D1 ≥ 210 obchodních dní, 5 svíček týdně; testy | — |
| **Ú2** Režim trhu | deterministický modul: trend × konsolidace (ADX, sklon EMA, D1/H4), volatilita (ATR percentil, GVZ), riziková nálada (VIX, S&P), dolar (DXY), stav korelací (Intermarket); každá složka se zdrojem a časem | v provozním snapshotu je `regime`, AI fakta mají oblast „režim“, karta na detailu zlata; testy | Ú1 |
| **Ú3** Ověřitelná AI odpověď | omezit vymýšlení čísel (struktura odpovědi, oprava po kontrole); změřit na kopii DB | ≥ 4 z 5 komplexních analýz na kopii projdou kontrolou jako ověřené | Ú1, Ú2 |
| **Ú4** Řízení rizika v1 | velikost pozice v lotech z nastavení a vzdálenosti SL (invalidace scénáře / ATR); brána „žádný obchod“ kolem událostí 3/3; denní a týdenní limit z nastavení | na detailu zlata panel rizika s loty pro aktuální scénář a stav brány; verdikt i AI bránu respektují; testy | Ú2, Ú3 |
| **Ú5** Actual a překvapení do AI | poslední ověřené Actual × Forecast jako fakta AI a vstup triggeru | AI fakta obsahují překvapení s původem hodnoty | — |
| **Ú6** Historická validace v1 | bez pohledu dopředu: uložené snapshoty verdiktu a režimu × následný pohyb zlata (D1) | report: počet, průměrný výsledek, chyba odhadu, po režimech | Ú1, Ú2 |
| **Ú7** Nasazení do cloudu | plán v `PROVOZ-2026-11-08.md` (záloha D1, revert) | cloud běží na nové verzi, mobil ukazuje mezitrh a režim; **jen s výslovným souhlasem** | Ú1–Ú4 |
| **Ú8** Struktura trhu a zóny | swingová struktura, S/R zóny D1/H4, jejich test a průraz | zóny v snapshotu, AI a grafu; ověřeno na historii | Ú1 |
| **Ú9** Myfxbook | vyhodnotit měření z út 10. 11. | rozhodnutí: záloha ano / ne, s čísly | 10. 11. |
| **Ú10** Další AI modely | Gemini / Mistral zdarma — potřebují bezplatné klíče uživatele | druhý model odpovídá a projde stejnou kontrolou | klíče |
| **L1** LIVE — zapnutí na PC | `live.enabled = true` po vašem souhlasu (zálohovaná DB) | stránka „Živě“ v provozní FTI ukazuje 4 instrumenty LIVE, monitoring na stránce Data | souhlas |
| **L2** LIVE — Purple cTrader | adaptér cTrader Open API (WebSocket JSON) | kotace vašeho brokera 23 h, shoda s MT5 Purple | váš demo účet cTrader + registrace aplikace |
| **L3** LIVE — cloud bez PC | engine jako Cloudflare Durable Object, stream do mobilu | 24 h běhu v cloudu bez výpadku, spotřeba v bezplatném tarifu | L1, souhlas s nasazením |

Mimo pořadí, otevřené rozhodnutí uživatele: automatický běh FTI na PC (dnes jen při otevřeném okně; cloud běží 24/7).

## 4. Dokončené úkoly

### Ú1 — denní historie zlata bez MT5 (9. 11. 2026, commity `5c4d1c0`, `ff42f24`)

Splněno podle kritéria „Hotovo, když“ — na **kopii** provozní DB (provozní DB a cloud beze změny):

| Kritérium | Výsledek |
|---|---|
| D1 ≥ 210 obchodních dní bez MT5 | 328 (2025-08-04 → 2026-11-09), jen po–pá, každý den jednou |
| hranice dne 17:00 New York, EST i EDT | přechody 2. 11. 2025, 8. 3. 2026, 1. 11. 2026 správně; testy i pro pravidla před 2007 |
| proti brokerovi | časy D1 327/327, W1 66/66, H4 185/185 totožné s MT5; kratší týdny jen svátky (25. 12., 1. 1., Velký pátek) |
| návaznost rámců | H1 a H4 skládají D1 přesně, W1 = složení D1, žádná H4 přes konec dne |
| opakované načtení, chybějící měsíc | beze změny a bez duplicit; chybějící měsíc = žádná svíčka (test) |
| SMA200 a RSI | SMA200 4 456,59, SMA50 4 188,90, RSI14 47,2 — shoda s nezávislým přepočtem |
| předání dalším modulům | snapshot `technical`, verdikt (složka technika −0,556), podmínky, AI fakta F14–F16, graf (popisky obchodních dní) |
| testy | backend 486/486, frontend 17/17 |

Nalezené a opravené vedlejší chyby:
- dotazy na hodiny zavřeného trhu se opakovaly při každém volání;
- začátek týdne o víkendu ukazoval předchozí týden;
- H4 přes hranici dne;
- graf a technika pojmenovávaly denní svíčku brokera předchozím dnem (týkalo se i MT5);
- AI denní techniku vůbec nedostávala.

### Ú2 — režim trhu (9. 11. 2026, commit `ddb58a9`)

| Kritérium | Výsledek |
|---|---|
| `regime` v provozním snapshotu | ano, 9. 11. 8:44 a 8:48 UTC (FTI otevřená uživatelem) |
| každá dimenze se zdrojem a časem | 6 dimenzí, vstupy s původem (Dukascopy, FRED, CBOE, přepočet DXY, Intermarket) |
| AI | fakta F17–F23 (oblast „rezim“) pro role makro, technika, syntéza; změna režimu spouští novou analýzu |
| karta v aplikaci | ověřeno v prohlížeči nad kopií (desktop i šířka telefonu, bez chyb v konzoli) |
| testy | backend 505/505, frontend 18/18, Worker 14/14 |

Zbývá: restart FTI (načíst verzi s volatilitou v % ceny) a sestavení frontendu na PC (karta, popisky dní).
