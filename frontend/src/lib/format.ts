import type { Bias, DataQuality, Direction, Horizon, Impact, PillarKey } from "./types";

export const LOCALE = "cs-CZ";

export const HORIZONS: Horizon[] = ["intraday", "1-3d", "1-10d", "1-4w", "1-3m"];
export const PRIMARY_HORIZON: Horizon = "1-10d";

export const HORIZON_LABELS: Record<Horizon, string> = {
  intraday: "Během dne",
  "1-3d": "1–3 dny",
  "1-10d": "1–10 dní",
  "1-4w": "1–4 týdny",
  "1-3m": "1–3 měsíce",
};

// Display order requested for the detail page.
export const PILLAR_ORDER: PillarKey[] = [
  "fed",
  "real_yields",
  "inflation",
  "usd",
  "economy",
  "central_banks",
  "geopolitics",
  "positioning",
];

export const PILLAR_LABELS: Record<PillarKey, string> = {
  fed: "Fed",
  real_yields: "Reálné výnosy",
  inflation: "Inflace",
  usd: "USD",
  economy: "Ekonomika",
  central_banks: "Centrální banky",
  geopolitics: "Geopolitika",
  positioning: "Pozicování",
};

export const QUALITY_LABELS: Record<DataQuality, string> = {
  ok: "Data v pořádku",
  partial: "Částečná data",
  unavailable: "Nedostupné",
};

// Enum values stay English in the API; only what the user reads is Czech.
export const DIRECTION_LABELS: Record<Direction, string> = {
  BULLISH: "BÝČÍ",
  BEARISH: "MEDVĚDÍ",
  NEUTRAL: "NEUTRÁLNÍ",
};

export const IMPACT_LABELS: Record<Impact, string> = {
  bullish: "býčí",
  bearish: "medvědí",
  neutral: "neutrální",
};

// Score thresholds used by the backend's bias_from_score (scoring/base.py).
export const LONG_THRESHOLD = 65;
export const SHORT_THRESHOLD = 35;

export function directionOf(bias: Bias): Direction {
  return bias === "LONG" ? "BULLISH" : bias === "SHORT" ? "BEARISH" : "NEUTRAL";
}

export function impactOfNumber(value: number, threshold = 0): Impact {
  if (value > threshold) return "bullish";
  if (value < -threshold) return "bearish";
  return "neutral";
}

const MINUS = "−";

function decimal(value: number, digits: number): string {
  return value.toLocaleString(LOCALE, { minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: false });
}

/** Signed number in Czech notation: "+3,1", "−3,1", never "−0,0". */
export function signed(value: number, digits = 1): string {
  const abs = decimal(Math.abs(value), digits);
  if (Number(Math.abs(value).toFixed(digits)) === 0) return decimal(0, digits);
  return `${value > 0 ? "+" : MINUS}${abs}`;
}

export function scoreText(score: number): string {
  return decimal(score, 1);
}

/** Plain number with Czech decimal comma. */
export function num(value: number, digits = 3): string {
  const text = decimal(Math.abs(value), digits);
  return value < 0 ? `${MINUS}${text}` : text;
}

/** The backend's 0–100 score maps linearly from a net pillar sum of −100…+100 (50 = neutral). */
export function netFromScore(score: number): number {
  return (score - 50) * 2;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(LOCALE, { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Calendar date only (e.g. an FOMC date) — no timezone conversion, it IS a date. */
export function formatDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  if (!y || !m || !d) return isoDate;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString(LOCALE, {
    weekday: "short",
    day: "numeric",
    month: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** "2026-09-25" -> "25. 9. 2026" */
export function shortDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  const [y, m, d] = isoDate.slice(0, 10).split("-").map(Number);
  return y && m && d ? `${d}. ${m}. ${y}` : isoDate;
}

/** Czech plural: 1 den, 2–4 dny, 5+ dní. */
export function plural(n: number, one: string, few: string, many: string): string {
  if (n === 1) return one;
  if (n >= 2 && n <= 4) return few;
  return many;
}

/** Older than two refresh intervals: the app was closed, the PC slept, or the download failed. */
export function isStale(iso: string | null | undefined, intervalMinutes = 30, now: Date = new Date()): boolean {
  if (!iso) return false;
  return now.getTime() - new Date(iso).getTime() > (2 * intervalMinutes + 5) * 60000;
}

export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "nikdy";
  const diffMs = now.getTime() - new Date(iso).getTime();
  const future = diffMs < 0;
  const mins = Math.round(Math.abs(diffMs) / 60000);
  if (mins < 1) return future ? "za chvíli" : "právě teď";
  let text: string;
  if (mins < 60) text = `${mins} min`;
  else if (mins < 60 * 48) text = `${Math.round(mins / 60)} h`;
  else {
    const days = Math.round(mins / 1440);
    text = future ? `${days} ${plural(days, "den", "dny", "dní")}` : `${days} ${plural(days, "dnem", "dny", "dny")}`;
  }
  return future ? `za ${text}` : `před ${text}`;
}

export function daysUntil(isoDate: string, now: Date = new Date()): number {
  const [y, m, d] = isoDate.split("-").map(Number);
  const target = Date.UTC(y, m - 1, d);
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((target - today) / 86400000);
}

/** Gold price in USD: "4 189,48 $". */
export function usd(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "—";
  return `${value.toLocaleString(LOCALE, { minimumFractionDigits: digits, maximumFractionDigits: digits })} $`;
}

export function inDays(days: number): string {
  if (days === 0) return "dnes";
  if (days === 1) return "zítra";
  if (days === -1) return "včera";
  if (days < 0) return `před ${-days} ${plural(-days, "dnem", "dny", "dny")}`;
  return `za ${days} ${plural(days, "den", "dny", "dní")}`;
}

export function sourceLabel(source: string): string {
  return source.startsWith("gdelt:") ? `${source.slice(6)} (přes GDELT)` : source;
}
