import { useCallback } from "react";
import { api } from "../lib/api";
import type { MarketCard } from "../lib/types";
import { useAsync, useInterval } from "./useAsync";

/** The market overview, re-read every 2 minutes (the backend recomputes it every 30). */
export function useMarkets() {
  const data = useAsync(() => api.markets(), []);
  const reload = useCallback(() => data.reload(), [data.reload]);
  useInterval(reload, 120000);
  return data;
}

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
