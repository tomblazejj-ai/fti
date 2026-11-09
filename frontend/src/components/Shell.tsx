import { useEffect, useRef, useState } from "react";
import { useLive } from "../hooks/useLive";
import { useGoldAnalysis, useMarkets, useRegime } from "../hooks/useMarkets";
import { useNow } from "../hooks/useNow";
import { useTickers } from "../hooks/useTickers";
import { STATIC } from "../lib/api";
import { countdown, formatDateTime, pct, price } from "../lib/format";
import { topQuotes, type FeedState, type TopQuote } from "../lib/quotes";
import { useTheme } from "../theme";
import { BrandMark, Icon, type IconName } from "./Icon";

export interface NavItem {
  href: string;
  label: string;
  icon: IconName;
  match: (h: string) => boolean;
}

const GOLD_OVERVIEW = /^#\/trh\/XAUUSD(\/(prehled|zony|sezonnost|zpravy|kalendar))?$/i;

export const GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: "Přehled",
    items: [
      { href: "#/", label: "Dashboard", icon: "grid", match: (h) => h === "" || h === "#" || h === "#/" },
      // the live terminal streams from the PC app's engine — the phone snapshot has no stream
      ...(STATIC ? [] : [{ href: "#/zive", label: "Live Markets", icon: "bolt" as IconName, match: (h: string) => h.startsWith("#/zive") }]),
      { href: "#/trhy", label: "Trhy", icon: "layers", match: (h) => h.startsWith("#/trhy") || (h.startsWith("#/trh/") && !/^#\/trh\/XAUUSD/i.test(h)) },
    ],
  },
  {
    title: "Analýza",
    items: [
      { href: "#/grafy", label: "Grafy", icon: "line", match: (h) => h.startsWith("#/grafy") },
      { href: "#/trh/XAUUSD", label: "Zlato", icon: "gold", match: (h) => GOLD_OVERVIEW.test(h) },
      { href: "#/trh/XAUUSD/technika", label: "Technika", icon: "chart", match: (h) => /^#\/trh\/XAUUSD\/technika/i.test(h) },
      { href: "#/trh/XAUUSD/intermarket", label: "Intermarket", icon: "globe", match: (h) => /^#\/trh\/XAUUSD\/intermarket/i.test(h) },
      { href: "#/trh/XAUUSD/makro", label: "Makro & COT", icon: "users", match: (h) => /^#\/trh\/XAUUSD\/makro/i.test(h) },
      { href: "#/zpravy", label: "Zprávy", icon: "news", match: (h) => h.startsWith("#/zpravy") },
      { href: "#/kalendar", label: "Kalendář", icon: "calendar", match: (h) => h.startsWith("#/kalendar") },
    ],
  },
  {
    title: "Rozhodnutí",
    items: [
      { href: "#/ai", label: "AI Advisor", icon: "spark", match: (h) => h.startsWith("#/ai") },
      { href: "#/risk", label: "Risk", icon: "shield", match: (h) => h.startsWith("#/risk") },
    ],
  },
  {
    title: "Vyhodnocení",
    items: [
      { href: "#/backtest", label: "Backtest", icon: "flask", match: (h) => h.startsWith("#/backtest") },
      { href: "#/signaly", label: "Historie signálů", icon: "history", match: (h) => h.startsWith("#/signaly") },
      { href: "#/denik", label: "Deník obchodů", icon: "book", match: (h) => h.startsWith("#/denik") },
    ],
  },
  {
    title: "Systém",
    items: [
      { href: "#/data", label: "Zdroje dat", icon: "database", match: (h) => h.startsWith("#/data") },
      { href: "#/nastaveni", label: "Nastavení", icon: "settings", match: (h) => h.startsWith("#/nastaveni") },
    ],
  },
];

function NavLinks({ current, onPick }: { current: string; onPick?: () => void }) {
  return (
    <>
      {GROUPS.map((g) => (
        <div key={g.title} className="side-group">
          <h3 className="side-title">{g.title}</h3>
          {g.items.map((n) => {
            const on = n.match(current);
            return (
              <a key={n.href} href={n.href} className={on ? "is-active" : ""} aria-current={on ? "page" : undefined} title={n.label} onClick={onPick}>
                <Icon name={n.icon} size={18} />
                <span className="side-label">{n.label}</span>
              </a>
            );
          })}
        </div>
      ))}
    </>
  );
}

export function Sidebar({ current, collapsed, onToggle }: { current: string; collapsed: boolean; onToggle: () => void }) {
  return (
    <aside className="side">
      <a href="#/" className="side-brand" aria-label="FTI – dashboard">
        <BrandMark size={30} />
        <span className="side-label">
          <strong>FTI</strong>
          <small>Trading Intelligence</small>
        </span>
      </a>
      <nav className="side-nav" aria-label="Hlavní menu">
        <NavLinks current={current} />
      </nav>
      <button type="button" className="side-toggle" onClick={onToggle} aria-pressed={collapsed}
              aria-label={collapsed ? "Rozbalit menu" : "Sbalit menu na ikony"} title={collapsed ? "Rozbalit menu" : "Sbalit menu"}>
        <Icon name="sidebar" size={18} />
        <span className="side-label">Sbalit menu</span>
      </button>
    </aside>
  );
}

const MOBILE: { href: string; label: string; icon: IconName; match: (h: string) => boolean }[] = [
  { href: "#/", label: "Přehled", icon: "grid", match: (h) => h === "" || h === "#" || h === "#/" },
  { href: "#/grafy", label: "Graf", icon: "chart", match: (h) => h.startsWith("#/grafy") || h.startsWith("#/trh/") },
  { href: "#/ai", label: "Rozhodnutí", icon: "target", match: (h) => h.startsWith("#/ai") },
  { href: "#/zpravy", label: "Feed", icon: "feed", match: (h) => h.startsWith("#/zpravy") },
];

export function MobileBar({ current, onMore, moreOpen }: { current: string; onMore: () => void; moreOpen: boolean }) {
  const inMain = MOBILE.some((m) => m.match(current));
  return (
    <nav className="tabbar" aria-label="Menu">
      {MOBILE.map((n) => {
        const on = n.match(current);
        return (
          <a key={n.href} href={n.href} className={on ? "is-active" : ""} aria-current={on ? "page" : undefined}>
            <Icon name={n.icon} size={22} />
            <span>{n.label}</span>
          </a>
        );
      })}
      <button type="button" className={moreOpen || !inMain ? "is-active" : ""} onClick={onMore} aria-expanded={moreOpen}>
        <Icon name="more" size={22} />
        <span>Více</span>
      </button>
    </nav>
  );
}

export function MoreSheet({ current, onClose }: { current: string; onClose: () => void }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="sheet-back" onClick={onClose}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label="Všechny stránky" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-head">
          <strong>Všechny stránky</strong>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Zavřít">
            <Icon name="close" size={20} />
          </button>
        </div>
        <nav className="sheet-nav" aria-label="Všechny stránky">
          <NavLinks current={current} onPick={onClose} />
        </nav>
      </div>
    </div>
  );
}

const ST_CLASS: Record<FeedState, string> = { LIVE: "live", DELAYED: "delayed", CLOSED: "closed", "N/A": "na" };

function TopTick({ q }: { q: TopQuote }) {
  const prev = useRef(q.price);
  const [flash, setFlash] = useState<"" | "up" | "down">("");
  useEffect(() => {
    const p = prev.current;
    prev.current = q.price;
    if (q.price === null || p === null || q.price === p) return;
    setFlash(q.price > p ? "up" : "down");
    const t = setTimeout(() => setFlash(""), 300);
    return () => clearTimeout(t);
  }, [q.price]);
  const tip = `${q.label} · ${q.state}\nZdroj: ${q.source}${q.time ? `\nČas: ${formatDateTime(q.time)}` : ""}\nMetoda: ${q.method}`;
  const ch = q.change_pct;
  return (
    <span className={`tq st-${ST_CLASS[q.state]}`} title={tip}>
      <span className="tq-top">
        <span className="tq-name">{q.label}</span>
        <span className="tq-st">{q.state}</span>
      </span>
      <span className="tq-row">
        <span className={`tq-price${flash ? ` flash-${flash}` : ""}`}>{q.price === null ? "—" : price(q.price, q.digits)}</span>
        <span className={`tq-ch ${ch === null ? "" : ch > 0 ? "pos" : ch < 0 ? "neg" : ""}`}>{ch === null ? "" : pct(ch)}</span>
      </span>
    </span>
  );
}

function Clocks() {
  const now = useNow(1000);
  const f = (tz: string) => now.toLocaleTimeString("cs-CZ", { timeZone: tz, hour: "2-digit", minute: "2-digit" });
  return (
    <span className="clocks" title="Čas v Praze a v New Yorku">
      <span><small>Praha</small> {f("Europe/Prague")}</span>
      <span><small>New York</small> {f("America/New_York")}</span>
    </span>
  );
}

function NextEvent() {
  const markets = useMarkets();
  const now = useNow(15000);
  const e = (markets.data?.next_events ?? []).find((x) => new Date(x.datetime).getTime() > now.getTime());
  if (!e) return null;
  const mins = (new Date(e.datetime).getTime() - now.getTime()) / 60000;
  return (
    <a href="#/kalendar" className={`tb-next${mins <= 60 ? " is-soon" : ""}`} title={`Další důležitá zpráva: ${e.title} (${e.currency}) · ${e.when} · zdroj: kalendář FTI`}>
      <Icon name="clock" size={15} />
      <span className="tb-next-what">{e.currency} · {e.title}</span>
      <strong>za {countdown(mins)}</strong>
    </a>
  );
}

export function ThemeToggle() {
  const [theme, set] = useTheme();
  const dark = theme === "dark";
  return (
    <button type="button" className="icon-btn" onClick={() => set(dark ? "light" : "dark")}
            aria-label={dark ? "Přepnout na světlý režim" : "Přepnout na tmavý režim"} title={dark ? "Světlý režim" : "Tmavý režim"}>
      <Icon name={dark ? "sun" : "moon"} size={18} />
    </button>
  );
}

function Notifications() {
  const live = useLive();
  const markets = useMarkets();
  const gold = useGoldAnalysis();
  const now = useNow(30000);
  const [open, setOpen] = useState(false);
  const items: { tone: "warn" | "info"; text: string; href: string }[] = [];
  for (const q of live.snap?.instruments ?? []) if (q.banner) items.push({ tone: "warn", text: `${q.label}: ${q.banner}`, href: "#/zive" });
  const e = (markets.data?.next_events ?? []).find((x) => new Date(x.datetime).getTime() > now.getTime());
  if (e) {
    const mins = (new Date(e.datetime).getTime() - now.getTime()) / 60000;
    if (mins <= 60) items.push({ tone: "info", text: `Za ${countdown(mins)}: ${e.title} (${e.currency})`, href: "#/kalendar" });
  }
  for (const s of gold.data?.sources_status ?? []) {
    if (s.status !== "ok") items.push({ tone: "warn", text: `${s.label}: ${s.note ?? s.status}`, href: "#/data" });
  }
  for (const err of markets.data?.errors ?? []) items.push({ tone: "warn", text: err, href: "#/data" });
  if (live.error && !STATIC) items.push({ tone: "info", text: `Živá data: ${live.error}`, href: "#/zive" });
  return (
    <div className="notif">
      <button type="button" className="icon-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open}
              aria-label={`Upozornění: ${items.length}`} title="Upozornění">
        <Icon name="bell" size={18} />
        {items.length > 0 && <span className="notif-n">{items.length}</span>}
      </button>
      {open && (
        <div className="notif-panel" role="region" aria-label="Upozornění">
          {items.length ? (
            <ul>
              {items.map((it) => (
                <li key={it.text} className={`notif-${it.tone}`}>
                  <a href={it.href} onClick={() => setOpen(false)}>{it.text}</a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Žádné upozornění.</p>
          )}
        </div>
      )}
    </div>
  );
}

export function TopBar() {
  const live = useLive();
  const tickers = useTickers();
  const gold = useGoldAnalysis();
  const regime = useRegime();
  const quotes = topQuotes(live.snap, tickers, gold.data, regime.data);
  return (
    <header className="topbar">
      <a href="#/" className="tb-brand" aria-label="FTI – dashboard">
        <BrandMark size={28} />
        <span>FTI</span>
      </a>
      <div className="tq-track" role="region" aria-label="Kurzy trhů">
        {quotes.map((q) => (
          <TopTick key={q.key} q={q} />
        ))}
      </div>
      <div className="tb-right">
        <Clocks />
        <NextEvent />
        <ThemeToggle />
        <Notifications />
      </div>
    </header>
  );
}
