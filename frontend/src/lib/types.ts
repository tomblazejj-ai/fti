// Mirrors the FastAPI response shapes (backend/app/api/*). No DOM or React
// imports anywhere in src/lib — this folder is meant to be reusable as-is by
// a future React Native (iOS/Android) client talking to the same backend.

export type Bias = "LONG" | "NEUTRAL" | "SHORT";
export type Direction = "BULLISH" | "NEUTRAL" | "BEARISH";
export type Impact = "bullish" | "bearish" | "neutral";
export type DataQuality = "ok" | "partial" | "unavailable";
export type Horizon = "intraday" | "1-3d" | "1-10d" | "1-4w" | "1-3m";
export type PillarKey =
  | "fed"
  | "real_yields"
  | "inflation"
  | "usd"
  | "economy"
  | "central_banks"
  | "geopolitics"
  | "positioning";

export interface Pillar {
  weight: number;
  raw_signal: number;
  points: number;
  impact: Impact;
  reasons: string[];
  data_quality: DataQuality;
  source: string;
  as_of: string | null;
  gaps?: string[]; // what is missing when data_quality !== "ok"
}

export interface Scenario {
  narrative: string;
  supports: string[];
  would_change: string[];
  key_risks: string[];
}

export interface ScoreSnapshot {
  instrument: string;
  horizon: Horizon;
  computed_at: string;
  bias: Bias;
  direction: Direction;
  score: number;
  pillar_breakdown: Partial<Record<PillarKey, Pillar>>;
  drivers: string[];
  contrarian: string[];
  risks: string[];
  scenarios: Partial<Record<"base" | "bull" | "bear", Scenario>>;
  invalidation: string[];
}

export interface PillarDelta {
  old_points: number;
  new_points: number;
  old_impact: Impact;
  new_impact: Impact;
}

export interface HistoryEntry {
  id: number;
  changed_at: string;
  horizon: Horizon;
  old_score: number | null;
  new_score: number;
  old_bias: Bias | null;
  new_bias: Bias;
  reason: string;
  related_news_ids: number[];
  related_observation_ids: number[];
  pillar_deltas: Partial<Record<PillarKey, PillarDelta>>;
}

export interface HistoryDetail extends Omit<HistoryEntry, "related_news_ids" | "related_observation_ids"> {
  news: {
    id: number;
    title: string;
    source: string;
    url: string | null;
    published_at: string;
    factor_tags: string[];
    sentiment_scores: Record<string, number>;
  }[];
  observations: {
    id: number;
    source: string;
    series: string;
    label: string;
    unit: string;
    period: string;
    actual: number | null;
    previous: number | null;
    source_url: string;
  }[];
}

export interface NewsReport {
  id: number;
  title: string;
  title_original: string;
  translated: boolean;
  source: string;
  url: string | null;
  published_at: string;
}

export interface NewsEvent {
  event_id: number;
  headline: string;
  headline_original: string;
  translated: boolean;
  language: string;
  source: string;
  url: string | null;
  published_at: string;
  instrument_tags: string[];
  factors: { factor: string; pillar: PillarKey; sentiment: number }[];
  impact: Impact;
  report_count: number;
  reports: NewsReport[];
}

export interface UpcomingEvent {
  date: string;
  time: string | null;
  event: string;
  importance: string;
  importance_basis: string;
  instruments: string[];
  factor: string | null;
  source_url: string | null;
}

export interface MainDriver {
  pillar: PillarKey;
  impact: Impact;
  points: number;
  reason: string;
}

export interface DataCoverage {
  backed: number; // pillars whose score contribution rests on real data (ok, or partial that moved)
  ok: number;
  partial: number;
  unavailable: number;
  total: number;
}

export type LiveSummary =
  | { computed: false }
  | {
      computed: true;
      computed_at: string;
      primary_horizon: Horizon;
      bias: Bias;
      direction: Direction;
      score: number;
      score_change: number | null;
      previous_computed_at: string | null;
      main_driver: MainDriver | null;
      data_coverage: DataCoverage;
      horizons: { horizon: Horizon; bias: Bias; direction: Direction; score: number }[];
      next_event: UpcomingEvent | null;
      verdict: VerdictBrief | null;
      mtf?: MtfBrief | null;
      dxy?: DxyBrief | null;
    };

export interface Level {
  label: string;
  pct: number; // % distance from the latest close (negative = below)
  price?: number | null; // USD, when the price source is a real gold price
  touches?: number;
}

export type Signal = -1 | 0 | 1;

export interface TechItem {
  name: string;
  value: string;
  signal: Signal;
  text: string;
  weight: number;
}

export interface Technical {
  as_of: string;
  trend: "up" | "down" | "sideways";
  trend_label: string;
  trend_score: number;
  tech_score: number;
  components: { points: number; text: string }[];
  groups: { key: string; title: string; items: TechItem[] }[];
  trend_age_days: number;
  trend_age_text: string;
  last_cross: { type: "golden" | "death"; date: string; days_ago: number } | null;
  rsi14: number | null;
  rsi_state: string;
  divergence: "bullish" | "bearish" | null;
  macd_bullish: boolean;
  bollinger_pct_b: number;
  squeeze: boolean;
  changes: Record<"1d" | "5d" | "20d" | "60d" | "250d", number | null>;
  volatility20: number;
  supports: Level[];
  resistances: Level[];
  fibonacci: { ratio: number; pct: number; price?: number | null }[];
  unit?: "USD" | "index";
  last_price?: number | null;
  fibonacci_text: string;
  sma50_pct: number;
  sma200_pct: number;
  history: { date: string; close: number; sma50: number | null; sma200: number | null }[];
}

export interface Correlation {
  key: string;
  label: string;
  fred_id: string;
  unit: string;
  available: boolean;
  note?: string;
  as_of?: string;
  corr_now?: number | null;
  corr_usual?: number | null;
  strength?: string;
  move20?: number;
  effect?: -1 | 0 | 1;
  unusual?: boolean;
}

export interface Cot {
  as_of: string;
  spec_net: number;
  spec_long: number;
  spec_short: number;
  comm_net: number;
  open_interest: number;
  spec_long_share: number | null;
  change_1w: number;
  change_4w: number;
  cot_index_3y: number | null;
  cot_index_1y: number | null;
  extreme: "crowded_long" | "light" | "neutral";
  signal: number;
  texts: string[];
  history: { date: string; spec_net: number; comm_net: number; spec_long?: number; spec_short?: number }[];
  source?: "disaggregated" | "legacy";
  source_label?: string;
  schedule?: { published: string; next_release: string; next_data_date: string; late: boolean };
  groups?: CotGroup[];
  long_short_ratio?: number | null;
  spec_short_share?: number | null;
  long_short?: LongShortView | null;
  retail?: LongShortView | null;
  commercials?: CotCommercials | null;
  open_interest_view?: CotOpenInterest | null;
}

export interface CotGroup {
  key: string;
  label: string;
  who: string;
  net: number;
  long: number | null;
  short: number | null;
  change_1w: number;
  change_4w: number;
  index_3y: number | null;
}

export interface Seasonality {
  months: { month: number; name: string; avg: number | null; median: number | null; win_rate: number | null; years: number;
    by_year: { year: number; ret: number }[] }[];
  current_month: number;
  current_text: string;
  next_text: string;
  signal: number;
  years_from: number;
  years_to: number;
  note: string;
}

export interface Scorecard {
  items: { key: string; label: string; score: number | null; group: string }[];
  final: number;
  final_label: string;
  note: string;
}

export interface WrittenSummary {
  date: string;
  text: string;
  bullets: string[];
  outlook: string[];
  note: string;
}

export interface DecisionItem {
  kind: "price" | "fund" | "cot" | "trend";
  title: string;
  detail: string;
  active: boolean;
}

export interface Decision {
  headline: string;
  bull: DecisionItem[];
  bear: DecisionItem[];
  events: { name: string; date: string; time: string | null; importance: number; up_if: string; down_if: string }[];
  levels: { up?: { price: number | null; pct: number; label: string }; down?: { price: number | null; pct: number; label: string } };
  active_bull: number;
  active_bear: number;
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
}

export interface MarketState {
  open: boolean;
  reason: "víkend" | "denní pauza" | null;
  next_open: string | null;
  closes_at: string | null;
  weekly_close: boolean;
}

export interface PriceCheck {
  quotes: Record<string, number>;
  gaps_pct?: Record<string, number>;
  max_gap_pct: number | null;
  ok: boolean | null;
  text: string;
  paxg_vs_physical?: number | null;
}

export interface TickersResponse {
  live: Quote[];
  daily: Quote[];
  error: string | null;
  fetched_at: string;
  market?: MarketState;
  price_check?: PriceCheck;
  weekend?: { spot_close: number; spot_close_time: string; paxg_now: number; change_pct: number } | null;
}

export interface SourceStatus {
  key: string;
  label: string;
  provider: string;
  rhythm: string;
  as_of: string | null;
  status: "ok" | "closed" | "late" | "missing";
  note: string;
}

/** [unix seconds, open, high, low, close, ema20, ema50] */
export type CandleRow = [number, number, number, number, number, number, number];

export interface CandlesResponse {
  tf: TfTrend["tf"];
  source: string;
  candles: CandleRow[];
  trend: Omit<TfTrend, "candles">;
  fetched_at: string;
}

export interface NewsMood {
  hours: number;
  count: number;
  bullish: number;
  bearish: number;
  score: number | null;
  top: { title: string; translated: boolean; source: string; url: string; published_at: string; impact: Impact }[];
  key?: KeyNews[];
}

export interface KeyNews {
  title: string;
  translated: boolean;
  source: string;
  url: string;
  published_at: string;
  impact: Impact;
  factors: string[];
  gold: boolean;
}

export type TrendDir = "up" | "down" | "sideways";

export interface TfTrend {
  tf: "M15" | "H1" | "H4" | "D1" | "W1";
  tf_label: string;
  direction: TrendDir;
  word: string;
  score: number;
  strength: string;
  adx: number | null;
  close: number;
  ema20: number;
  ema50: number;
  atr: number;
  change_pct: number;
  change_bars: number;
  swing_high: number | null;
  swing_low: number | null;
  text: string;
  as_of: string;
  candles?: CandleRow[];
}

export interface TrendBlend {
  key: "intraday" | "swing" | "overall";
  label: string;
  direction: TrendDir;
  lean: TrendDir;
  word: string;
  score: number;
  timeframes: string[];
  agree: string[];
}

export interface Mtf {
  timeframes: TfTrend[];
  intraday: TrendBlend | null;
  swing: TrendBlend | null;
  overall: TrendBlend | null;
  advice: string;
  price: number | null;
  price_time: string | null;
  price_text: string | null;
}

export interface MtfBrief {
  price: number | null;
  price_time: string | null;
  timeframes: { tf: TfTrend["tf"]; direction: TrendDir; word: string }[];
  intraday: TrendBlend | null;
  swing: TrendBlend | null;
  overall: TrendBlend | null;
}

export interface CalendarEvent {
  key?: string;
  up_if?: string;
  down_if?: string;
  instruments?: string[];
  date: string;
  time: string | null; // Prague time
  datetime: string | null;
  name: string;
  original: string;
  importance: 1 | 2 | 3;
  impact: string;
  previous: string | null;
  forecast: string | null;
  source: string;
  past: boolean;
  detail?: EventDetail | null;
}

export interface EconCalendar {
  instrument?: string;
  events: CalendarEvent[];
  next_high: CalendarEvent | null;
  lock?: NewsLockState;
  rules?: { lock_hours: number; confirm_minutes: number };
  timezone: string;
  notes: string[];
  sources: string[];
}

export type VerdictAction = "long" | "short" | "wait";
export type FactorKey = "fundament" | "technika" | "cot" | "zpravy" | "trhy";

export interface VerdictFactor {
  key: FactorKey;
  label: string;
  score: number;
  direction: "up" | "down" | "flat";
  weight: number;
  detail: string;
  sentence: string;
}

export interface Verdict {
  action: VerdictAction;
  direction_text: string;
  action_text: string;
  headline: string;
  summary: string;
  confidence: string;
  combined: number;
  factors: VerdictFactor[];
  components: Partial<Record<FactorKey, number>>;
  weights: Partial<Record<FactorKey, number>>;
  reasons: string[];
  timing: string | null;
  support: Level | null;
  resistance: Level | null;
  risks: string[];
  change_view: string[];
}

export interface Analysis {
  computed_at: string;
  technical: Technical | null;
  correlations: Correlation[] | null;
  gold_vol: { last: number; median: number; p75: number; elevated: boolean; as_of: string } | null;
  cot: Cot | null;
  news: NewsMood | null;
  mtf?: Mtf | null;
  calendar?: EconCalendar | null;
  decision?: Decision | null;
  seasonality?: Seasonality | null;
  scorecard?: Scorecard | null;
  summary?: WrittenSummary | null;
  daily_markets?: Quote[];
  dxy?: Dxy | null;
  market?: MarketState;
  sources_status?: SourceStatus[];
  verdict: Verdict;
  sources: Record<string, string>;
  tra?: Tra | null;
  seasonality_long?: SeasonalityLong | null;
  cot_usd?: CotUsd | null;
  headline_risk?: HeadlineRisk | null;
  zones?: Zones | null;
  setup?: AssistantView | null;
  season_daily?: { gold?: SeasonDaily | null; usd?: SeasonDaily | null } | null;
  weekly?: WeeklyPlan | null;
}

export interface VerdictBrief {
  action: VerdictAction;
  headline: string;
  direction_text: string | null;
  action_text: string | null;
  summary: string | null;
  confidence: string;
  trend: Technical["trend"] | null;
  trend_label: string | null;
  change_20d: number | null;
}

export interface DashboardInstrument {
  code: string;
  name: string;
  asset_class: string;
  status: "live" | "coming_soon";
  summary?: LiveSummary;
}

export interface SystemStatus {
  last_cycle_started_at: string | null;
  last_cycle_finished_at: string | null;
  cycle_running: boolean;
  last_cycle_error: string | null;
  last_cycle_warnings: string[];
  next_scheduled_run_at: string | null;
  refresh_interval_minutes: number;
}

export interface DashboardResponse {
  instruments: DashboardInstrument[];
  status: SystemStatus;
}

export interface CorrStat {
  value: number | null;
  beta: number | null;
  bars: number;
  label: string;
}

export interface Dxy {
  price: number | null;
  trends: Mtf;
  correlation: { d20?: CorrStat; d60?: CorrStat; d250?: CorrStat; h1?: CorrStat };
  effect_on_gold: number;
  text: string;
  overlay: { date: string; gold: number; dxy: number }[];
  levels: { swing_high: number | null; swing_low: number | null };
  source: string;
  verified: string;
  key_levels?: DxyKeyLevels | null;
  mirror?: DxyMirror | null;
  weights?: { code: string; name: string; weight: number }[];
  usd_score?: TraPack | null;
}

export interface DxyBrief {
  price: number | null;
  swing: TrendBlend | null;
  corr60: number | null;
  effect_on_gold: number;
  text: string;
}

// ---------------------------------------------------------------------------
// Funded Mind / Trading Analyzer methodology (2026-10)

export interface TraInput {
  name: string;
  value: string;
  as_of: string;
}

export interface TraComponent {
  key: string;
  label: string;
  score: number | null;
  max: number;
  reason: string;
  inputs: TraInput[];
  usd_score: number | null;
  proxy: string | null;
}

export interface TraPack {
  components: TraComponent[];
  total: number;
  max: number;
  missing: string[];
  word: "Býčí" | "Medvědí" | "Neutrální";
  strength: string;
  arrow: "up" | "down" | "flat";
}

export interface TraSituation {
  key: "consolidation" | "divergence";
  title: string;
  text: string;
}

export interface TraMomentum {
  current: number;
  changes: { "24h": number | null; "7d": number | null; "30d": number | null };
  speed_text: string;
  idea: { direction: "up" | "down"; from: number; to: number; text: string } | null;
  situations: TraSituation[];
}

export interface Tra {
  as_of: string;
  xau: TraPack;
  usd: TraPack;
  proxies_note?: string;
  momentum?: { xau: TraMomentum | null; usd: TraMomentum | null };
}

export interface TraHistory {
  instrument: string;
  points: { t: string; total: number; source: "live" | "backfill" }[];
  backfill_note: string;
}

export interface CotFlag {
  kind: "sharp" | "extreme_long" | "extreme_short" | "divergence";
  level: "warn";
  text: string;
}

export interface LongShortView {
  long_pct: number;
  short_pct: number;
  change_1w: number;
  change_4w: number;
  index_3y: number | null;
  as_of: string;
  flags: CotFlag[];
  history: { date: string; long_pct: number }[];
}

export interface CotUsd {
  source_label: string;
  schedule: { published: string; next_release: string; next_data_date: string; late: boolean };
  as_of: string;
  open_interest: number;
  leveraged: LongShortView | null;
  groups: CotGroup[];
  texts: string[];
  retail?: LongShortView | null;
}

export interface SeasonalityLongSide {
  label: string;
  months: { month: number; name: string; avg5: number | null; avg10: number | null; avg15: number | null; win10: number | null; n10: number }[];
  path: { labels: string[]; lines: { "5": number[]; "10": number[]; "15": number[] } };
  heatmap: { year: number; months: (number | null)[] }[];
  current_text: string;
  next_text: string;
  score: number;
  source: string;
  updated: string | null;
  note: string;
}

export interface SeasonalityLong {
  gold?: SeasonalityLongSide;
  usd?: SeasonalityLongSide;
}

export interface HeadlineItem {
  title: string;
  source: string;
  url: string;
  published_at: string;
  translated: boolean;
  topic: string;
}

export interface HeadlineRisk {
  level: 0 | 1 | 2;
  word: string;
  items: HeadlineItem[];
  spike: { time: string; range: number; usual: number; factor: number; direction: "up" | "down" } | null;
  weekend: { closes_at: string; hours: number; text: string } | null;
  hours: number;
  cluster?: boolean;
  note?: string;
  advice: string[];
}

export interface EventDetail {
  freq: string;
  why: string;
  usd: string;
  history_label: string;
  history_unit: string;
  history: { period: string; value: number; text: string }[];
  series: string | null;
  series_url: string | null;
  link: string;
}

export interface NewsLockState {
  state: "lock" | "after" | "clear";
  event?: string;
  datetime?: string;
  minutes?: number;
  text: string;
}

export interface DxyLevel {
  label: string;
  pct: number;
  price: number | null;
  touches?: number;
}

export interface DxyKeyLevels {
  supports: DxyLevel[];
  resistances: DxyLevel[];
  text: string;
  filter: string;
  trend: string | null;
}

export interface DxyMirror {
  state: "short" | "long" | "conflict" | "none";
  text: string;
  linked: boolean;
  gold: { support: DxyLevel | null; resistance: DxyLevel | null };
  dxy: { support: DxyLevel | null; resistance: DxyLevel | null };
  gold_at?: "support" | "resistance" | null;
  dxy_at?: "support" | "resistance" | null;
  near_pct: { gold: number; dxy: number };
}

export interface MetodikaFile {
  file: string;
  status: "done" | "changed" | "new";
  status_text: string;
  title: string | null;
  author: string | null;
  summary: string | null;
  used_in: string[];
  size_kb: number;
  modified: string;
  preview: string | null;
}

export interface Metodika {
  course: string;
  folder: string;
  folder_exists: boolean;
  files: MetodikaFile[];
  counts: { new: number; changed: number; done: number };
  missing: string[];
  principles: string[];
  extras?: { title: string; author: string; source: string; summary: string; used_in: string[]; added: string }[];
  checked_at: string;
  how_to: string;
}

// ---------------------------------------------------------------------------
// Trading assistant (Funded Mind swing strategy, 2026-10-17)

export interface Zone {
  tf: "W1" | "D1";
  kind: "demand" | "supply";
  lo: number;
  hi: number;
  proximal: number;
  distal: number;
  formed: string;
  touches: number;
  fresh: boolean;
  last_touch: string | null;
  pivots: number;
  strength: number;
  departure_atr: number;
  distance_pct: number;
  inside: boolean;
  activity: "active" | "some" | "none" | null;
  activity_ratio: number | null;
  poc: number | null;
  in_weekly?: boolean;
}

export interface ZoneSides {
  demand: Zone[];
  supply: Zone[];
}

export interface Zones {
  price: number;
  atr_d1: number | null;
  tf: { W1?: ZoneSides; D1?: ZoneSides };
  method: string;
}

export interface SetupCheck {
  key: string;
  label: string;
  state: "ok" | "bad" | "na";
  text: string;
}

export interface TradeSetup {
  side: "long" | "short";
  zone: Zone;
  weekly: Zone | null;
  checks: SetupCheck[];
  ok: number;
  total_checks: number;
  grade: "A+" | "A" | "B" | "C" | "skip";
  verdict: string;
  plan: { entry: number; poc: number | null; stop: number; target: number | null; target_zone: Zone | null; rr: number | null; risk_usd: number };
  state: "in_zone" | "near" | "waiting";
  where: string;
}

export interface AssistantView {
  action: "long" | "short" | "wait";
  headline: string;
  primary: "long" | "short" | null;
  setups: { long: TradeSetup | null; short: TradeSetup | null };
  other_text: string | null;
  timing: { key: string; state: "ok" | "bad" | "na"; text: string }[];
  bias: "long" | "short" | null;
  note: string;
  computed_at: string;
}

export interface WeeklyPlan {
  monday: string;
  friday: string;
  next_week: boolean;
  days: { date: string; events: { name: string; time: string | null; importance: 1 | 2 | 3; past: boolean }[] }[];
  lines: string[];
  title: string;
}

export interface SeasonWindow {
  avg: number;
  win: number;
  up: number;
  n: number;
  by_year: { year: number; ret: number }[];
  from: string;
  to: string;
  from_text: string;
  to_text: string;
  days: number;
}

export interface SeasonDaily {
  label: string;
  next30: SeasonWindow | null;
  lean: -1 | 0 | 1;
  best_up: SeasonWindow | null;
  best_down: SeasonWindow | null;
  texts: string[];
  path: { offsets: number[]; dates: string[]; lines: Record<string, number[]>; years_used: Record<string, number> };
  years_from: number;
  source: string;
  note: string;
}

export interface CotCommercials {
  net: number;
  change_4w: number | null;
  index_3y: number | null;
  extreme: "bullish" | "bearish" | null;
  text: string;
}

export interface CotOpenInterest {
  last: number;
  change_4w_pct: number;
  state: "rising" | "falling" | "flat";
  text: string;
}

// ---------------------------------------------------------------------------
// Market overview for all instruments (2026-10-31, Market Intelligence style)

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
  gold?: { headline: string; action: "long" | "short" | "wait"; grade: string | null };
}

export interface MarketsResponse {
  computed_at: string;
  markets: MarketCard[];
  method: string;
  errors: string[];
  market?: MarketState;
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
