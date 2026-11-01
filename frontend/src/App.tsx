import { useEffect, useState } from "react";
import { BrandMark, Icon, type IconName } from "./components/Icon";
import { TickerBar } from "./components/TickerBar";
import { STATIC } from "./lib/api";
import { CalendarPage } from "./pages/CalendarPage";
import { Home } from "./pages/Home";
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

const isHome = (h: string) => h === "#/" || h === "#" || h === "" || h.startsWith("#/trh/");

const NAV: { href: string; label: string; icon: IconName; match: (h: string) => boolean }[] = [
  { href: "#/", label: "Přehled", icon: "home", match: isHome },
  { href: "#/kalendar", label: "Kalendář", icon: "calendar", match: (h) => h.startsWith("#/kalendar") },
  { href: "#/zpravy", label: "Zprávy", icon: "news", match: (h) => h.startsWith("#/zpravy") },
];

function Page({ hash }: { hash: string }) {
  const market = hash.match(/^#\/trh\/([A-Za-z0-9]+)/);
  if (market) return <MarketDetail key={market[1]} code={market[1].toUpperCase()} />;
  if (hash.startsWith("#/kalendar")) return <CalendarPage />;
  if (hash.startsWith("#/zpravy")) return <NewsPage />;
  return <Home />;
}

export function App() {
  const hash = useHashRoute();
  const current = hash || "#/";
  return (
    <>
      <header className="nav">
        <a href="#/" className="brand" aria-label="FTI – přehled trhů">
          <BrandMark size={32} />
          <span className="brand-name">FTI</span>
          <span className="brand-sub">Financial Trading Intelligence</span>
        </a>
        <nav className="nav-links" aria-label="Hlavní menu">
          {NAV.map((n) => (
            <a key={n.href} href={n.href} className={n.match(current) ? "is-active" : ""}>
              <Icon name={n.icon} size={16} /> {n.label}
            </a>
          ))}
        </nav>
      </header>
      <TickerBar />
      <div key={hash.replace(/^#\/(trh\/\w+|kalendar|zpravy).*$/, "$1")} className="page-enter">
        <Page hash={hash} />
      </div>
      <nav className="tabbar" aria-label="Menu">
        {NAV.map((n) => (
          <a key={n.href} href={n.href} className={n.match(current) ? "is-active" : ""} aria-current={n.match(current) ? "page" : undefined}>
            <Icon name={n.icon} size={22} />
            <span>{n.label}</span>
          </a>
        ))}
      </nav>
      <footer className="footer">
        <p>
          Zdroje (vše zdarma, bez registrace): ceny Kraken · kurzy ECB · FRED®, Federal Reserve Bank of St. Louis · ECB Data Portal · Eurostat ·
          ONS (Británie) · Ministerstvo financí Japonska · EIA · CFTC Commitments of Traders · Fed, ECB, BoE, BoJ · Světová banka · NBP ·
          kalendář ForexFactory · zprávy přes RSS: fxstreet.cz, FXStreet, Investing.com, CNBC, MarketWatch, centrální banky · technické
          výhledy: Investing.com, FXEmpire, FXStreet (titulky s odkazem na původní článek).
          {STATIC && " Mobilní verze: data se obnovují každých 30 minut, ceny zlata, EUR/USD a GBP/USD živě z Krakenu."}
        </p>
        <p>
          Tento produkt používá data FRED®, ale není schválen ani certifikován Federal Reserve Bank of St. Louis. Hodnocení skládají pevná
          pravidla z veřejných dat, nejde o AI ani o investiční doporučení.
        </p>
      </footer>
    </>
  );
}
