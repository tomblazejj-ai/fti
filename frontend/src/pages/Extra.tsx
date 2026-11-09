import { AiPanel, AiTradePanel } from "../components/AiPanel";
import { LastSignals, NA } from "../components/GoldCards";
import { Icon, type IconName } from "../components/Icon";
import { TickerBar } from "../components/TickerBar";
import { Card, Empty } from "../components/ui";
import { SHORT_NAME } from "../hooks/useMarkets";
import { useTheme } from "../theme";
import { Home } from "./Home";

/** The overview of all five markets (the former start page) with every quote FTI reads. */
export function MarketsPage() {
  return (
    <>
      <TickerBar />
      <Home />
    </>
  );
}

const AI_MARKETS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "USOIL"];

/** AI Advisor: the complex AI analysis (LONG / SHORT / NO TRADE, gold) and the AI's reading of a market. */
export function AiAdvisor({ code = "XAUUSD" }: { code?: string }) {
  return (
    <main className="page page-wide">
      <header className="page-head">
        <h1>AI Advisor</h1>
        <p>AI vykládá jen to, co FTI spočítalo — každé číslo se kontroluje proti datům FTI. Obchody zadáváš ty, FTI nikdy neobchoduje.</p>
      </header>
      <nav className="itabs" aria-label="Trh">
        {AI_MARKETS.map((c) => (
          <a key={c} href={`#/ai/${c}`} className={c === code ? "is-active" : ""} aria-current={c === code ? "page" : undefined}>
            {SHORT_NAME[c] ?? c}
          </a>
        ))}
      </nav>
      <AiTradePanel code={code} i={1} />
      <AiPanel code={code} i={2} />
      <p className="note">AI se může mýlit, čísla pochází z dat FTI. Používají se jen bezplatné tarify (Gemini Free, záloha Groq Free).</p>
    </main>
  );
}

const PLACEHOLDER: Record<string, { title: string; icon: IconName; text: string; links?: { href: string; label: string }[] }> = {
  risk: {
    title: "Risk",
    icon: "shield",
    text: "Výpočet rizika (velikost pozice, riziko na obchod, celková expozice) FTI zatím nemá. Objeví se tu, až bude naprogramovaný a ověřený — do té doby tu žádná čísla nejsou.",
    links: [
      { href: "#/trh/XAUUSD/technika", label: "Kolísavost zlata a ATR (Technika)" },
      { href: "#/trh/XAUUSD/zony", label: "Podpory a rezistence (Zóny & likvidita)" },
    ],
  },
  backtest: {
    title: "Backtest",
    icon: "flask",
    text: "Backtest pravidel FTI zatím není naprogramovaný. Dokud není, FTI neukazuje žádnou úspěšnost ani pravděpodobnost.",
  },
  signaly: {
    title: "Historie signálů",
    icon: "history",
    text: "FTI zatím neukládá výsledky signálů (jestli došly k cíli, nebo ke stop-lossu). Níže je jen poslední AI analýza, bez vyhodnocení.",
  },
  denik: {
    title: "Deník obchodů",
    icon: "book",
    text: "Deník obchodů zatím není. FTI nemá přístup k tvému účtu a nikdy neobchoduje — deník bude jen pro tvůj ruční zápis.",
  },
};

/** A page whose function FTI does not have yet: says so, invents nothing. */
export function Placeholder({ page }: { page: string }) {
  const p = PLACEHOLDER[page];
  return (
    <main className="page">
      <header className="page-head">
        <h1>{p.title}</h1>
      </header>
      <Card title={`${p.title}: ${NA}`} icon={<Icon name={p.icon} size={16} />} id={`na-${page}`}>
        <Empty>{p.text}</Empty>
        {p.links && (
          <ul className="plain-list">
            {p.links.map((l) => (
              <li key={l.href}>
                <a className="card-link" href={l.href}>{l.label} <Icon name="chevronRight" size={14} /></a>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {page === "signaly" && <LastSignals i={1} />}
    </main>
  );
}

/** Settings of the look; data, keys, AI and the live engine stay on the data page. */
export function SettingsPage() {
  const [theme, setTheme] = useTheme();
  return (
    <main className="page">
      <header className="page-head">
        <h1>Nastavení</h1>
        <p>Vzhled se pamatuje v tomto prohlížeči. Klíče, AI a živá data jsou na stránce Zdroje dat.</p>
      </header>
      <Card title="Vzhled" icon={<Icon name={theme === "dark" ? "moon" : "sun"} size={16} />} id="vzhled">
        <div className="pills" role="group" aria-label="Režim">
          {(["dark", "light"] as const).map((t) => (
            <button key={t} type="button" className={`pill${theme === t ? " is-active" : ""}`} aria-pressed={theme === t} onClick={() => setTheme(t)}>
              {t === "dark" ? "Tmavý" : "Světlý"}
            </button>
          ))}
        </div>
        <p className="hint">Menu vlevo se sbalí na ikony tlačítkem dole v menu.</p>
      </Card>
      <Card title="Data, klíče, AI a živá data" icon={<Icon name="database" size={16} />} id="odkaz-data">
        <p>
          <a className="card-link" href="#/data">Zdroje dat <Icon name="chevronRight" size={14} /></a>
        </p>
      </Card>
    </main>
  );
}
