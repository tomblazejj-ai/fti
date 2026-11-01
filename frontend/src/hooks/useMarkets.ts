import { useCallback } from "react";
import { api } from "../lib/api";
import type { MarketCard, Quote } from "../lib/types";
import { useAsync, useInterval } from "./useAsync";
import { useTickers } from "./useTickers";

/** The market overview, re-read every 2 minutes (the backend recomputes it every 30). */
export function useMarkets() {
  const data = useAsync(() => api.markets(), []);
  const reload = useCallback(() => data.reload(), [data.reload]);
  useInterval(reload, 120000);
  return data;
}

const LIVE_SYMBOL: Record<string, string> = { XAUUSD: "PAXGUSD", EURUSD: "EURUSD", GBPUSD: "GBPUSD" };

/** Live price of a market where Kraken has one, else the snapshot price. */
export function useLivePrice(m: MarketCard): { value: number | null; change: number | null; live: Quote | undefined } {
  const t = useTickers();
  const live = LIVE_SYMBOL[m.code] ? t?.live.find((q) => q.symbol === LIVE_SYMBOL[m.code]) : undefined;
  return { value: live?.price ?? m.price?.value ?? null, change: live?.change_pct ?? m.price?.change_pct ?? null, live };
}

export const SHORT_NAME: Record<string, string> = {
  XAUUSD: "Zlato",
  EURUSD: "EUR/USD",
  GBPUSD: "GBP/USD",
  USDJPY: "USD/JPY",
  USOIL: "Ropa WTI",
};
