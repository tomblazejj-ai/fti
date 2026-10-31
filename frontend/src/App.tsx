import { useEffect, useState } from "react";
import { GoldMark, Icon, type IconName } from "./components/Icon";
import { TickerBar } from "./components/TickerBar";
import { STATIC } from "./lib/api";
import { Assistant } from "./pages/Assistant";
import { CalendarPage } from "./pages/CalendarPage";
import { InstrumentDetail, TABS, type Tab } from "./pages/InstrumentDetail";
import { MarketDetail } from "./pages/MarketDetail";
import { Markets } from "./pages/Markets";
import { Metodika } from "./pages/Metodika";
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

const isHome = (h: string) => h === "#/" || h === "#" || h === "" || h.startsWith("#/trh/");

const NAV: { href: string; label: string; icon: IconName; match: (h: string) => boolean }[] = [
  { href: "#/", label: "Trhy", icon: "chart", match: isHome },
  { href: "#/kalendar", label: "Kalendář", icon: "calendar", match: (h) => h.startsWith("#/kalendar") },
  { href: "#/zpravy", label: "Zprávy", icon: "news", match: (h) => h.startsWith("#/zpravy") },
  { href: "#/pomocnik", label: "Zlato", icon: "target", match: (h) => h.startsWith("#/pomocnik") || h.startsWith("#/instrument") },
  { href: "#/metodika", label: "Metodika", icon: "layers", match: (h) => h.startsWith("#/metodika") },
];

function Page({ hash }: { hash: string }) {
  const inst = hash.match(/^#\/instrument\/([A-Za-z0-9]+)(?:\/([a-z]+))?/);
  if (inst) {
    const tab = (TABS.some((t) => t.key === inst[2]) ? inst[2] : "overview") as Tab;
    return <InstrumentDetail key={inst[1].toUpperCase()} code={inst[1].toUpperCase()} tab={tab} />;
  }
  const market = hash.match(/^#\/trh\/([A-Za-z0-9]+)/);
  if (market) return <MarketDetail key={market[1]} code={market[1].toUpperCase()} />;
  if (hash.startsWith("#/kalendar")) return <CalendarPage />;
  if (hash.startsWith("#/zpravy")) return <NewsPage />;
  if (hash.startsWith("#/metodika")) return <Metodika />;
  if (hash.startsWith("#/pomocnik")) return <Assistant />;
  return <Markets />;
}

export function App() {
  const hash = useHashRoute();
  const current = hash || "#/";
  return (
    <>
      <header className="nav">
        <a href="#/" className="brand" aria-label="FTI — přehled trhů">
          <GoldMark size={26} />
          <span className="brand-name">FTI</span>
          <span className="brand-sub">Market Intelligence</span>
        </a>
        <nav className="nav-links" aria-label="Hlavní menu">
          {NAV.map((n) => (
            <a key={n.href} href={n.href} className={n.match(current) ? "is-active" : ""}>
              <Icon name={n.icon} size={15} /> {n.label}
            </a>
          ))}
        </nav>
      </header>
      <TickerBar />
      <Page hash={hash} />
      <nav className="tabbar" aria-label="Menu">
        {NAV.map((n) => (
          <a key={n.href} href={n.href} className={n.match(current) ? "is-active" : ""} aria-current={n.match(current) ? "page" : undefined}>
            <Icon name={n.icon} size={20} />
            <span>{n.label}</span>
          </a>
        ))}
      </nav>
      <footer className="footer">
        <p>
          Zdroje (vše zdarma, bez registrace): ceny Kraken · kurzy ECB · FRED®, Federal Reserve Bank of St. Louis · ECB Data Portal · ONS
          (Británie) · Ministerstvo financí Japonska · EIA · CFTC Commitments of Traders · BEA · Fed, ECB, BoE, BoJ · Světová banka · NBP ·
          kalendář ForexFactory · zprávy přes RSS: fxstreet.cz, FXStreet, Investing.com, CNBC, MarketWatch, centrální banky.
          {STATIC && " Mobilní verze: data se obnovují každých 30 minut, ceny zlata, EUR/USD a GBP/USD živě z Krakenu."}
        </p>
        <p>
          Tento produkt používá data FRED®, ale není schválen ani certifikován Federal Reserve Bank of St. Louis. Hodnocení skládají pevná
          pravidla, nejde o AI ani o investiční doporučení.
        </p>
      </footer>
    </>
  );
}
