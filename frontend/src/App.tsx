import { useCallback, useEffect, useState } from "react";
import { MobileBar, MoreSheet, Sidebar, TopBar } from "./components/Shell";
import { STATIC } from "./lib/api";
import { CalendarPage } from "./pages/CalendarPage";
import { Dashboard } from "./pages/Dashboard";
import { DataPage } from "./pages/DataPage";
import { ChartsPage } from "./pages/ChartsPage";
import { AiAdvisor, MarketsPage, Placeholder, SettingsPage } from "./pages/Extra";
import { LivePage } from "./pages/LivePage";
import { MarketDetail } from "./pages/MarketDetail";
import { NewsPage } from "./pages/NewsPage";

// Hash routing: the built app is plain static files (FastAPI on the PC, static hosting
// for the phone), so no server-side route fallback is needed for deep links.
function useHashRoute(): string {
  const [hash, setHash] = useState(() => window.location.hash);
  useEffect(() => {
    const onChange = () => {
      setHash(window.location.hash);
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

const SIDE_KEY = "fti-side-collapsed";

function storedCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDE_KEY) === "1";
  } catch {
    return false;
  }
}

function Page({ hash }: { hash: string }) {
  const market = hash.match(/^#\/trh\/([A-Za-z0-9]+)(?:\/([a-z]+))?/);
  if (market) return <MarketDetail key={market[1]} code={market[1].toUpperCase()} tab={market[2]} />;
  if (hash.startsWith("#/zive")) return STATIC ? <Dashboard /> : <LivePage />;
  if (hash.startsWith("#/trhy")) return <MarketsPage />;
  if (hash.startsWith("#/grafy")) return <ChartsPage />;
  if (hash.startsWith("#/kalendar")) return <CalendarPage />;
  if (hash.startsWith("#/zpravy")) return <NewsPage />;
  if (hash.startsWith("#/data")) return <DataPage />;
  const ai = hash.match(/^#\/ai(?:\/([A-Za-z0-9]+))?/);
  if (ai) return <AiAdvisor key={ai[1] ?? "XAUUSD"} code={(ai[1] ?? "XAUUSD").toUpperCase()} />;
  const ph = hash.match(/^#\/(risk|backtest|signaly|denik)/);
  if (ph) return <Placeholder page={ph[1]} />;
  if (hash.startsWith("#/nastaveni")) return <SettingsPage />;
  return <Dashboard />;
}

export function App() {
  const hash = useHashRoute();
  const current = hash || "#/";
  const [collapsed, setCollapsed] = useState(storedCollapsed);
  const [more, setMore] = useState(false);
  const toggle = useCallback(() => {
    setCollapsed((c) => {
      try {
        localStorage.setItem(SIDE_KEY, c ? "0" : "1");
      } catch {
        /* storage blocked — the menu state lasts until reload */
      }
      return !c;
    });
  }, []);
  const closeMore = useCallback(() => setMore(false), []);
  useEffect(() => setMore(false), [hash]);
  return (
    <div className={`app${collapsed ? " is-collapsed" : ""}`}>
      <Sidebar current={current} collapsed={collapsed} onToggle={toggle} />
      <div className="main">
        <TopBar />
        <div key={hash.replace(/^#\/(trh\/\w+(?:\/[a-z]+)?|ai(?:\/\w+)?|zive|trhy|grafy|kalendar|zpravy|data|risk|backtest|signaly|denik|nastaveni).*$/, "$1")} className="page-enter">
          <Page hash={hash} />
        </div>
        <footer className="footer">
          <p>
            Zdroje (vše zdarma): ceny Dukascopy, Deriv, Kraken · kurzy ECB · FRED®, Federal Reserve Bank of St. Louis · ECB Data Portal · Eurostat ·
            ONS (Británie) · Ministerstvo financí Japonska · EIA · CFTC Commitments of Traders · Fed, ECB, BoE, BoJ · Světová banka · NBP ·
            kalendář ForexFactory · zprávy přes RSS: fxstreet.cz, FXStreet, Investing.com, CNBC, MarketWatch, centrální banky · technické
            výhledy: Investing.com, FXEmpire, FXStreet (titulky s odkazem na původní článek). Grafy: TradingView Lightweight Charts™.
            {STATIC && " Mobilní verze: data se obnovují každých 30 minut."}
          </p>
          <p>
            Tento produkt používá data FRED®, ale není schválen ani certifikován Federal Reserve Bank of St. Louis. Hodnocení skládají pevná
            pravidla z veřejných dat; AI jen vykládá výpočty FTI. Nejde o investiční doporučení.
          </p>
          <p className="app-version" title="Stejná verze všude, kde běží stejný build (web, aplikace na PC i v mobilu)">
            Verze <span className="num">{__FTI_COMMIT__}</span> · build{" "}
            {new Date(__FTI_BUILT__).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" })}
          </p>
        </footer>
      </div>
      <MobileBar current={current} onMore={() => setMore((m) => !m)} moreOpen={more} />
      {more && <MoreSheet current={current} onClose={closeMore} />}
    </div>
  );
}
