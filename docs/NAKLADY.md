# FTI — co by mohlo stát peníze (audit 9. 11. 2026)

**Tvrdá podmínka: 0 Kč.** Žádná placená služba, žádná platební karta ani jiná platební metoda, žádné automatické
přechody na placené tarify — bez výslovného souhlasu uživatele nic. Vyčerpaná bezplatná kvóta = bezpečná pauza a
záznam (u AI výsledek **NO TRADE „AI nedostupná“**), nikdy placená náhrada.

## 1. Kde FTI běží a na jakém tarifu

| Služba | Tarif | Jak ověřeno | Co by stálo peníze |
|---|---|---|---|
| **Cloudflare Workers** (Worker `fti`, `fti.tomblazejj.workers.dev`) + **Cron Trigger** | **Workers Free** | účet nemá platební metodu (rozhodnutí uživatele „bez karty“); tarif Workers Paid (5 USD/měsíc) se bez platební metody aktivovat nedá; na Free se při překročení limitu (100 000 požadavků/den, 10 ms CPU) požadavek odmítne, nic se neúčtuje. Přímé ověření: dashboard Cloudflare → Workers & Pages → Plans = „Free“ | ruční přechod na Workers Paid |
| **Cloudflare D1** (databáze `fti`) | **D1 Free** (součást Workers Free) | stejně; na Free se po limitu (100 000 zápisů / 5 mil. čtení denně, 5 GB) operace odmítnou | jen s Workers Paid |
| **GitHub Actions** (výpočet každých 30 min) | zdarma pro **veřejný** repozitář | API GitHubu 9. 11. 2026: `tomblazejj-ai/fti` je `public` | kdyby se repozitář změnil na soukromý: Free účet má jen 2 000 min/měsíc (FTI spotřebuje ~350 min/den) — bez platební metody by se běhy zastavily, s ní by se platilo |
| **GitHub Pages** (záloha mobilní verze) | zdarma (veřejný repozitář) | totéž | — |
| **Aplikace na PC** | vlastní PC | — | jen elektřina |

## 2. AI

| Poskytovatel | Tarif v FTI | Ochrana | Co by stálo peníze |
|---|---|---|---|
| **Google Gemini** (Flash, hlavní) | Free — klíč z Google AI Studio **bez billingu** | bez billingu Google nic neúčtuje; limit = HTTP 429 → pauza modelu, pak Groq; denní strop FTI | **zapnutí billingu** v projektu Google (pak je každé volání placené) — nikdy nezapínat. Pozor na podmínky: od 23. 3. 2026 smí API klienti pro uživatele v EHP používat jen placené služby (otázka podmínek, ne peněz) |
| **Groq** (záloha) | Free plán bez karty | HTTP 402 („platba“) zastaví AI natrvalo; 429 → pauza | přechod na Developer tarif (vyžaduje kartu) |
| OpenAI, Anthropic | v registru, **nikdy volány** | `free=False` → router je nepoužije | zadání klíče a schválení rozpočtu |
| OpenRouter, Mistral, Workers AI | neschváleno, bez klienta | — | OpenRouter: kredity (nákup); Mistral: ověření telefonem; Workers AI: na Free plánu po 10 000 neuronů chyba, ne účet |
| Cerebras | nepoužito | — | vyžaduje platební metodu → vyloučeno |

**Denní strop FTI:** nejvýš 80 volání AI denně dohromady (Gemini + Groq, natvrdo v `app/ai/guard.py`, nastavení ho
může jen snížit), 100 000 tokenů, 6 za minutu; posledních 20 % jen pro důležité události. Počítadlo: stránka Data →
karta AI („Volání AI dnes X / 80“). Cloud má vlastní stejný strop.

## 3. Data (vše zdarma)

Bez klíče: Dukascopy, FXCM archiv, Deriv (veřejný stream), Kraken, ECB, Eurostat, OECD, SNB, NBP, CFTC, EIA, US Treasury,
CBOE, BLS v1, BEA, Census, DOL, Fed RSS, BoE, BoC, BoJ, MOF, ONS, World Bank, gold-api.com, Forex Factory (kalendář),
GDELT, RSS médií (FXStreet, CNBC, Investing, FXEmpire, Dow Jones), BullionVault.
S bezplatným klíčem (zadává uživatel): FRED, TickBase, Groq, Gemini, cTrader Open API (demo), Capital.com (demo),
OANDA (practice). MT5 terminál Purple je zdarma (jen čtení).

| Co by stálo peníze | Stav |
|---|---|
| Twelve Data Pro (streaming), Polygon, Finnhub placené tarify | nepoužito |
| oficiální ICE DXY, indexy S&P / Nasdaq v reálném čase, ISM | nepoužito — FTI ukazuje náhrady s označením |
| živé (real-money) brokerské účty | FTI jen čte demo účty a nikdy neobchoduje |

## 4. Doporučení z technického průzkumu, která by vyžadovala kartu → nepoužít

| Návrh | Proč ne | Náhrada |
|---|---|---|
| **Cloudflare Access / Zero Trust** (přihlášení do aplikace) | i bezplatný tarif chce při zakládání platební údaje | vlastní jednoduché přihlášení ve Workeru (tajný klíč), zdarma |
| **Cloudflare R2** (soubory ticků) | před prvním bucketem chce platební metodu; nad bezplatný limit automaticky účtuje | ticky jako soubory na PC (už tak) nebo v repozitáři; v cloudu jen svíčky v D1 |
| vlastní doména | roční poplatek | `*.workers.dev` |

Zdroje: [Gemini API podmínky](https://aistudio.google.com/docs/terms), [Cloudflare Zero Trust setup](https://developers.cloudflare.com/cloudflare-one/setup),
[R2 pricing](https://developers.cloudflare.com/r2/pricing/index.md), [Durable Objects pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/).

## 5. Co hlídá kód

- AI: jen poskytovatelé s `free=True` a schválením; 402 → AI stop; 429 → pauza; oba vyčerpané → NO TRADE „AI nedostupná“.
- Denní strop volání AI napříč poskytovateli + počítadlo v aplikaci.
- Žádný kód nevolá placené API; v repozitáři nejsou klíče (`backend/.env` mimo git).
- Cloud: bez platební metody na účtu nelze nic naúčtovat — překročení limitu znamená odmítnutý požadavek.
