// Chart data feeds: the chart (components/LwChart) draws bars and knows nothing about where they come from. Each feed
// gives bars of ONE source with its label and state; a new source (cTrader later) is one more feed with the same shape.
// Sources are never mixed in one series: switching the source replaces the whole series and the chart says which one it is.
import { STATIC, api } from "./api";
import type { DataQuality, MarketStateInfo, Tf } from "./types";

export const ALL_TFS: Tf[] = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"];
export const DAILY_TFS = new Set<Tf>(["D1", "W1", "MN1"]);

export interface FeedBar {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  /** trading day of a D1 / W1 / MN1 candle (17:00 New York grid) */
  day?: string;
  e20?: number | null;
  e50?: number | null;
}

export interface FeedResult {
  bars: FeedBar[];
  feed: FeedId;
  /** who delivers the prices, as the backend names it */
  source: string;
  provider: string | null;
  priceType: string | null;
  /** LIVE / DELAYED / HISTORICAL / UNAVAILABLE … of this feed */
  status: string | null;
  quality?: DataQuality | null;
  market?: MarketStateInfo | null;
  kindCs?: string | null;
  notes: string[];
  lineOnly: boolean;
  fetchedAt: string | null;
  lastQuoteText?: string | null;
}

export type FeedId = "live" | "history";

export interface ChartFeed {
  id: FeedId;
  name: string;
  /** which timeframes this feed has for the instrument */
  tfs(code: string): Tf[];
  load(code: string, tf: Tf): Promise<FeedResult>;
  /** only the newest bars (for series.update), or null when the feed has no cheaper call than load() */
  tail: ((code: string, tf: Tf) => Promise<FeedResult>) | null;
}

/** instruments the live engine streams (PC app; in the cloud once the live service runs there) */
export const LIVE_CODES = new Set(["XAUUSD", "EURUSD", "US500.CFD", "US100.CFD"]);
/** instruments with history candles from FTI's data layer */
export const HISTORY_CODES = new Set(["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "USOIL", "PAXGUSD"]);

export const historyFeed: ChartFeed = {
  id: "history",
  name: "Historie FTI",
  tfs: (code) => (!HISTORY_CODES.has(code) ? [] : STATIC ? ["H4", "D1", "W1", "MN1"] : ["M15", "H1", "H4", "D1", "W1", "MN1"]),
  async load(code, tf) {
    const r = await api.candles(code, tf);
    const days = r.days && r.days.length === r.candles.length ? r.days : null;
    return {
      feed: "history",
      bars: r.candles.map((c, i) => ({ t: c[0], o: c[1], h: c[2], l: c[3], c: c[4], e20: c[5], e50: c[6], day: days?.[i] })),
      source: r.source,
      provider: r.provider ?? null,
      priceType: null,
      status: r.quality?.status ?? null,
      quality: r.quality ?? null,
      market: r.market ?? null,
      kindCs: r.kind_cs ?? null,
      notes: r.notes ?? [],
      lineOnly: !!r.line_only,
      fetchedAt: r.fetched_at,
      lastQuoteText: r.last_quote && !r.last_quote.tradable_now ? `poslední kotace ${r.last_quote.time_cs}` : null,
    };
  },
  tail: null,
};

async function liveLoad(code: string, tf: Tf, limit: number): Promise<FeedResult> {
  const r = await api.liveCandles(code, tf, limit);
  return {
    feed: "live",
    bars: r.candles.map((c) => ({ t: c[0], o: c[1], h: c[2], l: c[3], c: c[4] })),
    source: r.product ?? r.provider ?? "živý engine",
    provider: r.provider,
    priceType: r.price_type,
    status: r.quote?.data_status ?? r.quote?.status ?? null,
    market: null,
    notes: r.quote?.notes ?? [],
    lineOnly: false,
    fetchedAt: null,
  };
}

export const liveFeed: ChartFeed = {
  id: "live",
  name: "Živý engine",
  tfs: (code) => (STATIC || !LIVE_CODES.has(code) ? [] : ALL_TFS),
  load: (code, tf) => liveLoad(code, tf, 500),
  tail: (code, tf) => liveLoad(code, tf, 10),
};

export const FEEDS: Record<FeedId, ChartFeed> = { live: liveFeed, history: historyFeed };

/** Merge newer bars into the series: same start time = the bar was updated, a later time = a new bar. Older bars stay,
 * so the chart can update only the tail (series.update) instead of redrawing everything. */
export function mergeBars(prev: FeedBar[], next: FeedBar[]): FeedBar[] {
  if (!prev.length) return next;
  if (!next.length) return prev;
  const firstNew = next[0].t;
  if (firstNew < prev[0].t) return next; // a longer history arrived: take it as it is
  const keep = prev.filter((b) => b.t < firstNew);
  const merged = [...keep, ...next];
  // nothing changed → the same array, so nothing is redrawn
  if (merged.length === prev.length && merged.every((b, i) => sameBar(b, prev[i]))) return prev;
  return merged;
}

export function sameBar(a: FeedBar, b: FeedBar): boolean {
  return a.t === b.t && a.o === b.o && a.h === b.h && a.l === b.l && a.c === b.c && a.e20 === b.e20 && a.e50 === b.e50;
}
