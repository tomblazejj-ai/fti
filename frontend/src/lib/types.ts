// Shapes of the backend's JSON answers (/api/markets, /api/calendar, /api/tickers, candles).

export interface Quote {
  symbol: string;
  label: string;
  price: number;
  digits: number;
  change_pct: number | null;
  source: string;
  live: boolean;
  as_of?: string;
}

export interface MarketState {
  open: boolean;
  reason: "víkend" | "denní pauza" | null;
  next_open: string | null;
  closes_at: string | null;
  weekly_close: boolean;
}

export interface TickersResponse {
  live: Quote[];
  daily: Quote[];
  error: string | null;
  fetched_at: string;
  market?: MarketState;
}

export type Tf = "M15" | "H1" | "H4" | "D1" | "W1";

/** [time (s), open, high, low, close, EMA20, EMA50] */
export type CandleRow = [number, number, number, number, number, number, number];

export interface CandlesResponse {
  tf: Tf;
  source: string;
  candles: CandleRow[];
  fetched_at: string;
}

export interface MarketComponent {
  key: string;
  label: string;
  score: number | null;
  max: number;
  text: string;
  details: string[];
}

export interface MarketArgument {
  label: string;
  text: string;
  score: number;
}

export interface WatchItem {
  when: string;
  datetime: string;
  currency: string;
  title: string;
  impact: 1 | 2 | 3;
  impact_text: string;
  forecast: string | null;
  previous: string | null;
}

export interface RetailSentiment {
  long_pct: number;
  short_pct: number;
  change_4w: number | null;
  as_of: string | null;
  head: string;
  text: string;
  tone: "support" | "warn" | "neutral";
  source: string;
}

export interface MarketPrice {
  value: number;
  change_pct: number | null;
  as_of: string;
  live: boolean;
  source: string;
}

export interface MarketNews {
  title: string;
  source: string;
  url: string;
  published_at: string;
  translated: boolean;
}

export interface MarketCard {
  code: string;
  name: string;
  subtitle: string;
  kind: "fx" | "gold" | "oil";
  digits: number;
  score10: number;
  word: string;
  bias: "LONG" | "SHORT" | "NEUTRÁLNÍ";
  raw: number;
  possible: number;
  components: MarketComponent[];
  missing: string[];
  for: MarketArgument[];
  against: MarketArgument[];
  price: MarketPrice | null;
  trend: string | null;
  retail: RetailSentiment | null;
  watch: WatchItem[];
  change_text: string;
  news: MarketNews[];
  /** technical outlooks written by public portals (Investing.com, FXEmpire, FXStreet) */
  technical: MarketNews[];
}

export interface Highlight extends MarketNews {
  market: string;
  impact?: "bullish" | "bearish" | "neutral" | null;
}

export interface NextEvent {
  datetime: string;
  when: string;
  currency: string;
  title: string;
  forecast: string | null;
  previous: string | null;
}

export interface MarketsResponse {
  computed_at: string;
  markets: MarketCard[];
  method: string;
  errors: string[];
  market?: MarketState;
  highlights?: Highlight[];
  next_events?: NextEvent[];
}

export interface CalendarItem {
  datetime: string;
  timed?: boolean;
  currency: string;
  title_cs: string;
  title_en: string;
  impact: 0 | 1 | 2 | 3;
  forecast: string | null;
  previous: string | null;
  source: string;
  url?: string;
}

export interface CalendarAll {
  events: CalendarItem[];
  timezone: string;
  sources: string[];
  computed_at: string;
}
