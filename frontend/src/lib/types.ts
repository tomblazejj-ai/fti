// Shapes of the backend's JSON answers (/api/markets, /api/calendar, /api/tickers, candles).

/** Market state of an instrument (backend app/data/market_hours.py). */
export interface MarketStateInfo {
  state: "OPEN" | "CLOSED" | "PRE_MARKET" | "POST_MARKET" | "TRADING_BREAK" | "HOLIDAY" | "UNKNOWN";
  label: string;
  reason: string;
  calendar: string;
  exchange_tz: string;
  next_change: string | null;
}

/** The last real price of an instrument and whether it is a tradable quote right now. */
export interface LastQuote {
  price: number;
  time: string | null;
  time_cs: string;
  age_minutes: number;
  tradable_now: boolean;
  kind_cs: string;
  note: string | null;
  time_verified?: boolean;
  reference?: boolean;
  fetched_at?: string;
  timezone?: string;
  indicative?: boolean;
  received_at?: string;
}

export interface Quote {
  symbol: string;
  label: string;
  price: number;
  digits: number;
  change_pct: number | null;
  source: string;
  live: boolean;
  as_of?: string;
  market?: MarketStateInfo;
  proxy?: boolean;
  kind_cs?: string;
  provider?: string;
  quote_time_cs?: string;
  reference?: boolean;
  indicative?: boolean;
  time_verified?: boolean;
  itype_cs?: string;
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
  unavailable?: { symbol: string; label: string; reason: string; market?: MarketStateInfo }[];
  error: string | null;
  fetched_at: string;
  market?: MarketState;
}

export type Tf = "M15" | "H1" | "H4" | "D1" | "W1";

/** [time (s), open, high, low, close, EMA20, EMA50] */
export type CandleRow = [number, number, number, number, number, number, number];

/** Data-quality label of one value (backend app/data/quality.py). */
export type QualityStatus = "LIVE" | "NEAR_REAL_TIME" | "DELAYED" | "HISTORICAL" | "STALE" | "UNAVAILABLE" | "PROXY" | "INDICATIVE";

export interface DataQuality {
  status: QualityStatus;
  label: string;
  as_of: string | null;
  age_hours: number | null;
  text: string;
}

export interface InstrumentIdentity {
  code: string;
  symbol: string;
  name: string;
  asset: string;
  itype: string;
  itype_cs: string;
  unit: string;
  quote_ccy: string;
  digits: number;
  proxy: boolean;
  proxy_note: string | null;
  underlying: string | null;
  venue: string | null;
  expiry: string | null;
  timezone: string;
  feeds: string[];
  cot_market: string | null;
  cot_note: string | null;
  notes: string[];
}

export interface CandlesResponse {
  tf: Tf;
  code?: string;
  source: string;
  provider?: string | null;
  candles: CandleRow[];
  /** D1 / W1: the trading day of each candle (YYYY-MM-DD) — a broker candle starts at 17:00 New York the evening before */
  days?: string[] | null;
  line_only?: boolean;
  quality?: DataQuality;
  proxy?: boolean;
  notes?: string[];
  kind_cs?: string;
  volume_note?: string | null;
  instrument?: InstrumentIdentity | null;
  market?: MarketStateInfo;
  last_quote?: LastQuote;
  fetched_at: string;
}

export interface AuditRow {
  code: string;
  symbol: string;
  name: string;
  itype_cs: string;
  gets: string;
  source: string;
  verdict: string;
  status: QualityStatus;
  limits: string;
  recommendation: string;
  market?: MarketStateInfo | Record<string, never>;
  last_quote?: LastQuote | Record<string, never>;
}

export interface ProbeRow {
  key: string;
  name: string;
  ok: boolean;
  ms: number;
  records: number;
  latest: string | null;
  quality: DataQuality;
  error: string | null;
}

export interface SourceRow {
  key: string;
  name: string;
  status: "ok" | "delayed" | "stale" | "outage" | "unavailable" | "unknown";
  last_ok: string | null;
  last_error_at: string | null;
  last_error: string | null;
  ok_count: number;
  error_count: number;
  last_ms: number | null;
  last_records: number | null;
  data_as_of: string | null;
  /** outages only (no unsupported timeframes, no rejected data), counted since `counting_since` */
  outage_count: number;
  rejected_count: number;
  last_rejected: string | null;
  unsupported_count: number;
  unsupported_tfs: string[];
  last_quality: string | null;
  expected_quality: string | null;
  counting_since: string | null;
}

export interface Mt5Terminal {
  name: string;
  path: string;
  servers: string[];
}

export interface SourcesResponse {
  sources: SourceRow[];
  stale_inputs: { label: string; fetched_at: string; error: string }[];
  fred_last_source: Record<string, string>;
  keys: { name: string; label: string; set: boolean; hint: string | null }[];
  mt5: { settings: { enabled: boolean; terminal_path: string; symbols: Record<string, string> }; terminals: Mt5Terminal[]; package: boolean };
  oanda: { settings: { environment: string }; token_set: boolean };
  legend: Record<string, string>;
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
  quality?: DataQuality;
  proxy?: boolean;
  kind?: string;
  market?: MarketStateInfo | null;
  last_quote?: LastQuote | null;
}

export interface MarketNews {
  title: string;
  source: string;
  url: string;
  published_at: string;
  /** where the time comes from: the source's publication time, GDELT's first sighting, or FTI's fetch time */
  time_basis?: "published" | "gdelt_seen" | "fetched" | null;
  translated: boolean;
  /** the machine translation changed a number, currency, percentage or scale — the original is shown instead */
  translation_failed?: boolean;
  /** the original headline (shown on hover when a translation is shown) */
  title_en?: string;
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
  /** released USD event: the official value on the release day (BLS, BEA, Census, DOL via ALFRED) */
  actual?: string | null;
  actual_source?: string;
  /** "ověřeno u vydavatele" only when the publisher's own numbers agree; otherwise said plainly */
  actual_status?: string;
  actual_note?: string;
  previous_revised?: string;
}

export interface CalendarAll {
  events: CalendarItem[];
  timezone: string;
  sources: string[];
  computed_at: string;
}

/* ---- AI (Groq Free): it only interprets FTI's engine output; every number is checked against the facts ---- */

export interface AiFact {
  id: string;
  co: string;
  hodnota: string | number | null;
  zdroj: string;
  k?: string;
  text?: string;
  volatile?: boolean;
  /** area of the common analytical context (trh, technika, fundament …) */
  oblast?: string;
  /** where the time of a news fact comes from (publication / GDELT capture / FTI fetch) */
  puvod_casu?: string;
}

export interface AiPoint {
  text: string;
  fakta: string[];
}

export interface AiValidation {
  ok: boolean;
  schema: string[];
  unknown_facts: string[];
  unknown_numbers: string[];
  /** rules a trading scenario must meet (confirmation and invalidation …) */
  rules?: string[];
  /** FTI's independent check: problems in texts that could not be removed */
  attribution?: string[];
  /** points the independent check removed (a number, direction or correlation that did not belong there) */
  removed?: { text: string; problem: string }[];
}

export interface AiStage {
  role: string;
  provider: string;
  model: string;
  validation: AiValidation | null;
  facts_used: string[];
  tokens: { in: number; out: number };
  seconds: number;
}

export interface AiAnalysis {
  id: number;
  task: string;
  code: string | null;
  created_at: string;
  model: string | null;
  reason: string | null;
  engine_computed_at: string | null;
  output: Record<string, unknown> | null;
  facts: AiFact[] | null;
  validation: AiValidation | null;
  tokens: { in: number; out: number } | null;
  confidence: string | null;
  stages?: AiStage[] | null;
  providers?: string[] | null;
  seconds?: number | null;
  missing?: string[] | null;
}

export interface AiRunResult {
  status: "ok" | "cached" | "cooldown" | "unavailable" | "invalid" | "not_ready";
  text: string;
  analysis?: AiAnalysis | null;
  until?: string | null;
  code?: string;
}

export interface AiGroqStatus {
  provider: string;
  key_set: boolean;
  state: string;
  text: string;
  until: string | null;
  auto_analyses: boolean;
  usage: { requests: number; tokens: number; failed: number; cap: number; token_cap: number; per_minute_cap: number; reserve_from: number };
  models: Record<string, { paused_until: string | null; reason: string | null; limits: Record<string, number | string> | null }>;
  limits_changed: { model: string; what: string; old: number; new: number; at: string } | null;
  terms_checked: string;
  cost: string;
}

export interface AiTaskInfo {
  id: string;
  name: string;
  ready: boolean;
  why_not: string | null;
  cooldown_min: number;
}

export interface AiStatus {
  provider: string;
  groq: AiGroqStatus;
  tasks: AiTaskInfo[];
}

export interface AiTestResult {
  ok: boolean;
  text: string;
  models?: string[];
  seconds?: number;
  limits?: Record<string, number>;
  until?: string | null;
}

/* ---- Intermarket Intelligence: gold's correlations with other markets on synchronised returns (not causation) ---- */
export interface ImWindow {
  window: number;
  n: number;
  n_eff: number | null;
  r: number | null;
  p: number | null;
  ci95: number[] | null;
  strength: string;
  sufficiency: string;
}

export interface ImRelation {
  b: string;
  b_code: string;
  label: string;
  category: string;
  tf: string;
  observations_total: number;
  windows: ImWindow[];
  last_common: string | null;
  sources: string[];
  proxy: boolean;
  related: string | null;
  q_main?: number;
  stability?: { verdict: string; same_sign_share: number; mean: number };
  change?: { r_now: number; r_prev: number; delta: number; p: number; significant: boolean };
  breakdown?: { state: string; r_short?: number; r_long?: number; text?: string };
  move?: { bars: number; gold_pct: number; other: number; other_unit: string; verdict: string; text: string; from?: string; until: string };
  quality: { label: string; issues: string[] };
}

export interface IntermarketResult {
  tf: string;
  target?: string;
  target_label?: string;
  computed_at: string;
  error?: string;
  main_window?: number;
  windows?: number[];
  relations: ImRelation[];
  source_checks?: ImRelation[];
  discovered?: { a: string; b: string; r: number; n: number; q: number; related: string | null }[];
  method?: string;
  causality?: string;
}

// Market regime of gold (Ú2) — /api/regime
export interface RegimeInput {
  name: string;
  value: number | string | null;
  unit?: string | null;
  source?: string | null;
  as_of?: string | null;
}

export interface RegimeDimension {
  key: string;
  label: string;
  state: string;
  word: string;
  detail: string;
  implication: string | null;
  inputs: RegimeInput[];
  available: boolean;
}

export interface MarketRegime {
  as_of: string;
  computed_at: string;
  label: string;
  summary: string;
  dimensions: RegimeDimension[];
  atr?: { d1: number; pct_of_price: number; percentile: number; window: number; as_of: string | null } | null;
  missing: string[];
  method: string;
  note: string;
}

// LIVE terminal (test version) — /api/live/*
export type LiveStatus = "LIVE" | "DELAYED" | "HISTORICAL" | "UNAVAILABLE";

export interface LiveProviderRow {
  provider: string;
  symbol: string;
  role: "primary" | "backup" | "check";
  product: string;
  age_s: number | null;
  fresh: boolean;
  in_session: boolean;
  compat: { pairs: number; ok: boolean; text: string; median_abs?: number; offset?: number; tolerance?: number } | null;
}

export interface LiveQuote {
  code: string;
  label: string;
  name: string;
  kind: string;
  digits: number;
  status: LiveStatus;
  data_status?: LiveStatus;
  status_cs: string;
  /** MARKET STATUS from the instrument's schedule (OPEN, CLOSED, …) — never from whether data arrive */
  market_status?: string;
  market_status_cs?: string;
  /** "TRH OTEVŘEN – DATA NEAKTUÁLNÍ" when the market is open and the data are not LIVE */
  banner?: string | null;
  failover: boolean;
  notes: string[];
  providers: LiveProviderRow[];
  provider?: string;
  symbol?: string;
  product?: string;
  price_type?: string;
  bid?: number | null;
  ask?: number | null;
  spread?: number | null;
  mid?: number | null;
  last_trade?: number | null;
  time_basis?: "quote" | "receive";
  quote_time?: string;
  received_at?: string;
  age_s?: number | null;
  prev_close?: number | null;
  prev_close_day?: string | null;
  change?: number | null;
  change_pct?: number | null;
}

export interface LiveSnapshot {
  version: number;
  at: string;
  running: boolean;
  instruments: LiveQuote[];
}

export interface LiveCandles {
  code: string;
  tf: string;
  provider: string | null;
  product: string | null;
  price_type: string | null;
  candles: [number, number, number, number, number][];
  quote: LiveQuote;
}
