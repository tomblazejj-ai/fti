# Metodika Funded Mind v aplikaci FTI

Materiály: složka **Plocha → Fundament Funded mind** (20 PDF, kurz Funded Mind).
Autoři: **Jan Šrajer** (Swing trading strategie) a **Daniel Valchář** (Fundamentální analýza).
Nástroj, se kterým lekce pracují: **Trading Analyzer (TrA)** — podle něj je postavený vzhled
a logika nových panelů.

Seznam zapracovaných souborů (s otiskem SHA-256) je v `backend/app/data/metodika.json`.
Když do složky přibude nový soubor nebo se nějaký změní, stránka **Metodika** v aplikaci ho
označí jako „nový — zatím nezapracováno“.

## Video: swingová strategie (přepis, 17. 10. 2026)

- Swing místo daytradingu: **10 minut denně** a **1–2 hodiny o víkendu** na přípravu celého týdne.
- **Supply/demand zóny**: nejdřív týdenní graf (supply nad cenou, demand pod cenou), pak upřesnění na denním
  grafu uvnitř týdenní zóny.
- **Objem**: zóna musí mít za sebou obchodní aktivitu; nejpřesnější bod je POC. Aplikace místo objemu
  z futures (není zdarma) měří čas strávený na ceně.
- **Skóre Trading Analyzeru** musí ukazovat směr obchodu (z +2 na −1 = strany se prohodily → short).
- **COT**: u měn velcí spekulanti, **u zlata commercials**. Retail se čte opačně. **Open interest** ukazuje,
  jestli do trhu přitékají nové peníze.
- **Sezónnost**: 5, 10 a 15 let, opakující se okna (např. „od 11. 9. do 9. 10. ve všech 10 letech dolů“),
  tolerance jeden až tři týdny.
- **Plán**: vstup na hraně zóny, stop-loss za zónou, cíl minimálně protější zóna.
- **Kdy obchod nechat být**: když makro, COT i sezónnost jdou proti, nebo když zóna nemá objem.

V aplikaci: **Pomocník** (hlavní obrazovka) — odpověď, checklist, plán, graf se zónami, plán na týden.

## Hlavní myšlenka

> Skóre = makro kompas, momentum = jeho směr.

1. Ráno zkontroluj skóre.
2. Změna skóre o **2 a více bodů** za den = obchodní nápad.
3. Zóny hledej ve směru nového biasu (TradingView).
4. Urči cíl — další zónu ve směru obchodu.
5. Vstup na menším pullbacku, stop-loss za zónu.
6. Nech obchod běžet, nedrž přes víkend a velké události.

## Co je kde v aplikaci

| Materiál | Autor | Kde v aplikaci |
|---|---|---|
| Score overview | Šrajer | Přehled → Score Overview, Denní rutina; DXY → skóre dolaru |
| TrA Score Momentum | Valchář | Přehled → Score History, momentum, modelové situace |
| Úvod do TrA | Valchář | rozvržení přehledu |
| COT | Šrajer | COT → long/short podíl zlata i dolaru; skóre → COT bias |
| COT, jak je vnímat a používat | Valchář | COT → signály: extrém, prudká změna, divergence |
| Dollar a DXY | Valchář | DXY → klíčové úrovně, filtr, zrcadlo se zlatem, složení koše |
| News | Valchář | Kalendář → pravidlo 2 hodin, filtr dopadu, detail události s historií |
| Headline Risk | Valchář | Přehled → Headline risk, varování před víkendem |
| Seasonality | Šrajer | Sezónnost → průměry 5/10/15 let; skóre → sezónnost |
| Seasonality (1) | Valchář | Sezónnost → heatmapa s průměrem |
| Retail sentiment – DXM | Šrajer | skóre → retail sentiment; COT → malí obchodníci |
| Trend | Šrajer | skóre → trend |
| GDP, Inflace, Inflation + GDP | Šrajer, Valchář | skóre → HDP a inflace |
| Interest Rates | Šrajer | skóre → úrokové sazby (očekávání) |
| Labor Market | Šrajer | skóre → trh práce |
| Manufacturing PMI, Services PMI | Šrajer | skóre → PMI průmysl a služby |
| Retail Sales | Šrajer | skóre → maloobchodní tržby |

## Skóre (Score Overview)

Součet 11 kategorií, rozsah −25 až +25:

| Kategorie | Rozsah | Čím se počítá (zdarma, bez registrace) |
|---|---|---|
| COT bias | ±3 | CFTC: hedgeové fondy ve zlatě (managed money) proti fondům v dolaru (leveraged funds) |
| Retail sentiment | ±1 | CFTC „malí obchodníci“, kontrariánsky (náhrada brokerských dat) |
| Sezónnost | ±2 | Světová banka, 10 let, aktuální měsíc |
| HDP | ±2 | FRED: reálné HDP, index aktivity Chicago Fed |
| Inflace | ±3 | FRED: jádrová a celková inflace CPI, úroveň i vývoj |
| Trh práce | ±4 | FRED: NFP, nezaměstnanost, mzdy, Sahmovo pravidlo |
| Úrokové sazby | ±2 | FRED: 2letý výnos vs. sazba Fedu = očekávání trhu |
| PMI služby | ±2 | FRED: průzkumy Fedu ve službách (Philadelphia, Dallas) |
| PMI průmysl | ±2 | FRED: průzkumy Fedu v průmyslu (NY, Philadelphia, Dallas) |
| Maloobchodní tržby | ±2 | FRED: tržby, průměr m/m za 3 měsíce |
| Trend | ±2 | denní a týdenní trend ceny, kontrola obratu přes divergenci RSI |

Makro kategorie hodnotí **americký dolar**. U XAU/USD mají opačné znaménko: silnější dolar
je pro zlato horší. Lekce dávají rozsahy a směr vlivu, ne vzorce. Prahy proto volí
aplikace, jsou pevné a u každé položky se po kliknutí ukáže přesné pravidlo a čísla.

## Pravidla, která aplikace hlídá

- **2 hodiny před červenou zprávou žádný nový vstup.** Po zprávě se čeká na potvrzení
  směru. Odpočet běží živě v kalendáři i v přehledu.
- **Headline risk.** Nečekané zprávy mimo kalendář (cla, válka, sankce, krize, mimořádné
  kroky centrálních bank). Headline není signál, s pozicemi se nezůstává přes víkend.
- **COT.** Extrémy bývají blízko obratu. Prudká změna v jednom reportu ohlašuje nový pohyb.
  Divergence ceny a COT je varování.
- **Sezónnost.** Je to filtr pro swingové obchody, ne signál a ne nástroj pro intraday.
- **DXY.** Klíčové úrovně dávají bias, trend je filtr. Zlato u rezistence a dolar u
  supportu tvoří zrcadlo.

## Jak přidat nové materiály

Ulož soubor do složky **Fundament Funded mind**. Stránka **Metodika** ho hned ukáže jako nový.
Při další úpravě aplikace se zapracuje a doplní do `metodika.json`.
