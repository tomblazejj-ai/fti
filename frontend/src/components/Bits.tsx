import type { CSSProperties, ReactNode } from "react";
import { useLivePrice } from "../hooks/useMarkets";
import { countdown, pct, price, relativeTime } from "../lib/format";
import type { DataQuality, MarketCard, MarketNews, NextEvent, QualityStatus, WatchItem } from "../lib/types";
import { Icon } from "./Icon";
import { tone } from "./Visual";

export const BIAS_TEXT: Record<MarketCard["bias"], string> = {
  LONG: "Spíš růst",
  SHORT: "Spíš pokles",
  NEUTRÁLNÍ: "Bez jasného směru",
};

export function BiasChip({ m }: { m: MarketCard }) {
  const t = m.bias === "LONG" ? "pos" : m.bias === "SHORT" ? "neg" : "zero";
  return (
    <span className={`bias bias-${t}`}>
      {m.bias === "LONG" ? <Icon name="arrowUp" size={14} /> : m.bias === "SHORT" ? <Icon name="arrowDown" size={14} /> : <span aria-hidden="true">↔</span>}
      {BIAS_TEXT[m.bias]}
    </span>
  );
}

const Q_LABEL: Record<QualityStatus, string> = {
  LIVE: "živě",
  NEAR_REAL_TIME: "téměř živě",
  DELAYED: "se zpožděním",
  HISTORICAL: "historická",
  STALE: "zastaralé",
  UNAVAILABLE: "nedostupné",
  PROXY: "proxy",
};

/** Data-quality chip: what kind of data this is and how fresh — text, not only colour. */
export function QualityBadge({ q, source }: { q?: DataQuality | null; source?: string }) {
  if (!q) return null;
  const when = q.as_of ? ` · data k ${new Date(q.as_of).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" })}` : "";
  return (
    <span className={`qb qb-${q.status.toLowerCase()}`} title={`${source ? source + " — " : ""}${q.text}${when}`}>
      {Q_LABEL[q.status] ?? q.label}
    </span>
  );
}

/** Price of a market from its own feed, with its quality label; flashes when it moves. */
export function LivePrice({ m, big = false }: { m: MarketCard; big?: boolean }) {
  const p = useLivePrice(m);
  return (
    <span className={`lprice${big ? " is-big" : ""}`} title={m.price?.source}>
      <span key={p.value ?? "na"} className="lprice-v flash">{price(p.value, m.digits)}</span>
      {p.change !== null && <span className={`lprice-ch ${tone(p.change)}`}>{pct(p.change)}</span>}
      {p.live && <span className="live-dot" title="živá cena" aria-label="živá cena" />}
      {big && <QualityBadge q={m.price?.quality} source={m.price?.source} />}
    </span>
  );
}

/** One news headline with its source and age. */
export function NewsList({ items, start = 0, tags }: { items: MarketNews[]; start?: number; tags?: (n: MarketNews) => ReactNode }) {
  return (
    <ul className="news">
      {items.map((n, i) => (
        <li key={n.url} className="rise" style={{ "--i": start + i } as CSSProperties}>
          <a href={n.url} target="_blank" rel="noreferrer">
            {tags && <span className="news-tags">{tags(n)}</span>}
            <span className="news-title">{n.title}</span>
            <span className="news-meta">
              {n.source} · {relativeTime(n.published_at)}
              {n.translated && " · strojový překlad"}
              <Icon name="external" size={12} />
            </span>
          </a>
        </li>
      ))}
    </ul>
  );
}

const FLAG: Record<string, string> = { USD: "🇺🇸", EUR: "🇪🇺", GBP: "🇬🇧", JPY: "🇯🇵", CNY: "🇨🇳", CAD: "🇨🇦", AUD: "🇦🇺", CHF: "🇨🇭" };

/** Upcoming releases with a live countdown; the first one is highlighted. */
export function EventList({ items, now, highlightFirst = true }: { items: (NextEvent | WatchItem)[]; now: Date; highlightFirst?: boolean }) {
  return (
    <ul className="events">
      {items.map((e, i) => {
        const mins = (new Date(e.datetime).getTime() - now.getTime()) / 60000;
        const soon = mins > 0 && mins <= 180;
        const done = mins <= 0;
        return (
          <li key={`${e.datetime}-${e.title}`} className={`ev rise${i === 0 && highlightFirst ? " is-first" : ""}${soon ? " is-soon" : ""}${done ? " is-done" : ""}`}
              style={{ "--i": i } as CSSProperties}>
            <span className="ev-flag" aria-hidden="true">{FLAG[e.currency] ?? "🌐"}</span>
            <span className="ev-body">
              <strong>{e.title}</strong>
              <small>
                {e.when} · {e.currency}
                {e.forecast ? ` · prognóza ${e.forecast}` : ""}
                {e.previous ? ` · minule ${e.previous}` : ""}
              </small>
            </span>
            <span className="ev-count">{done ? "právě vyšlo" : `za ${countdown(mins)}`}</span>
          </li>
        );
      })}
    </ul>
  );
}
