import { api } from "../lib/api";
import { sharedPoll } from "../lib/shared";
import type { MarketCard } from "../lib/types";

/** The market overview, re-read every 2 minutes (the backend recomputes it every 30); one request for all screens. */
export const useMarkets = sharedPoll(() => api.markets(), 120000);

/** Gold's engine output (technique, verdict, scorecard, COT …), re-read every 5 minutes — PC app only. */
export const useGoldAnalysis = sharedPoll(() => api.analysis("XAUUSD"), 300000);

/** Gold's market regime (also the source of the VIX value in the top bar). */
export const useRegime = sharedPoll(() => api.regime(), 300000);

/** The market's price exactly as the backend got it from THIS instrument's own feed, with its
 * data-quality label. No other instrument's quote is ever shown in its place (e.g. PAXG for XAUUSD). */
export function useLivePrice(m: MarketCard): { value: number | null; change: number | null; live: boolean } {
  return { value: m.price?.value ?? null, change: m.price?.change_pct ?? null, live: m.price?.quality?.status === "LIVE" };
}

export const SHORT_NAME: Record<string, string> = {
  XAUUSD: "Zlato",
  EURUSD: "EUR/USD",
  GBPUSD: "GBP/USD",
  USDJPY: "USD/JPY",
  USOIL: "Ropa WTI",
};
