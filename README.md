# FTI – Financial Trading Intelligence

Kam míří trhy: fundament, zprávy a kalendář na jednom místě — **0 Kč, žádné registrace,
žádné API klíče**. Zdroje a jejich ověření: [ARCHITECTURE.md](ARCHITECTURE.md),
rozhodnutí a proč: [docs/DECISIONS.md](docs/DECISIONS.md).

## Spuštění (každodenní použití)

Dvojklik na ikonu **FTI** na ploše. Otevře se okno aplikace (bez příkazového
řádku — server běží skrytě na pozadí). Aplikaci ukončíš zavřením okna.
Ikona spouští `backend/.venv/Scripts/pythonw.exe desktop.py`; záznam běhu
serveru se ukládá do `backend/fti.log`.

`start.bat` zůstává pro řešení problémů: spustí server v konzoli, kde jsou
vidět průběžné zprávy, a aplikaci otevře v prohlížeči na
http://127.0.0.1:8000.

První výpočet po startu trvá asi minutu (stahuje FRED, CFTC, RSS centrálních
bank a GDELT se zpožděními, které tyto zdroje vyžadují). Pak se data obnovují
automaticky každých 30 minut.

## Co aplikace umí

- **Přehled** — nahoře odpočet do další důležité zprávy, pak zlato, EUR/USD,
  GBP/USD, USD/JPY a ropa WTI se skóre −10 až +10 (ručičkový ukazatel, směr,
  jedna věta proč), pod tím „Co hýbe trhy“ a „Co může trh ovlivnit“.
- **Detail trhu** — proč (3 hlavní důvody a co jde proti), co může trh
  ovlivnit, technický výhled z veřejných webů (Investing.com, FXEmpire,
  FXStreet — převzaté titulky s odkazem), zprávy, graf, drobní obchodníci a
  rozpis skóre.
- **Kalendář** — USD, EUR, GBP a JPY, barvy podle dopadu, prognózy.
- **Zprávy** — zprávy a technické výhledy podle trhu.
- **Mobil** — stejná aplikace jako aplikace v telefonu (viz `docs/MOBIL.md`).

## Zdroje dat (vše zdarma, bez klíčů)

FRED (veřejný CSV download a kalendář zveřejnění), CFTC Commitments of Traders
(Disaggregated pro zlato, TFF pro dolar), Kraken (PAXG/USD, EUR/USD, GBP/USD), kurzy
ECB, Eurostat, ONS, ministerstvo financí Japonska, EIA, kalendář ForexFactory, BullionVault, Světová banka (měsíční ceny zlata), NBP (denní cena zlata od 2013), BEA, RSS portálů a
centrálních bank, GDELT DOC API, kalendář FOMC z federalreserve.gov.

## První instalace na novém počítači

Potřebuješ Python 3.12+ a (jen pro build frontendu) Node.js 20+.

```bash
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..\frontend
npm install
npm run build
```

## Vývoj

```bash
cd backend && .venv\Scripts\python.exe -m pytest -q
cd frontend && npm test
cd frontend && npm run dev    # Vite na :5173, API proxy na :8000
```

Soubor `backend/.env` není potřeba; `.env.example` popisuje volitelné
přepínače (vlastní FRED klíč, interval obnovy, jiná databáze).

## Známá omezení

- **GDELT** často vrací HTTP 429 (rate limit) — UI přesně ukazuje, kolik
  dotazů selhalo; nic se nedoplňuje odhadem.
- **Kalendář** bere termíny z FRED, BEA a Fedu; FOMC data jsou ručně ověřená
  na rok 2026 (rok 2027 doplnit, až ho Fed zveřejní). Čas se nikdy nevymýšlí.
- **Konsensus (forecast)** nemá legální bezplatný zdroj → „surprise“ je
  Actual vs Previous.
- **ISM PMI** nemá spolehlivý bezplatný zdroj — ve skóre ho nahrazují
  regionální průzkumy Fedu (v aplikaci označené „≈“).
- Celá aplikace je česky. Anglické titulky zpráv překládá lokálně Argos
  Translate (bez internetové služby) a jsou označené jako strojový překlad.
- Změny schématu DB zatím nemají migrace (Alembic) — při změně modelu se
  lokální `backend/fti.db` smaže a vytvoří znovu.
