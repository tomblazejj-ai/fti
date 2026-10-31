import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { TickersResponse } from "../lib/types";

// One shared live-quote poll (every 60 s) for the ticker strip, the header
// price and the market banner — however many components listen.
const POLL_MS = 60000;
let state: TickersResponse | undefined;
const listeners = new Set<(t: TickersResponse) => void>();
let timer: number | undefined;

async function load() {
  try {
    state = await api.tickers();
    listeners.forEach((l) => l(state!));
  } catch {
    /* keep the last good quotes; the strip shows nothing new */
  }
}

export function useTickers(): TickersResponse | undefined {
  const [t, setT] = useState(state);
  useEffect(() => {
    listeners.add(setT);
    if (listeners.size === 1) {
      void load();
      timer = window.setInterval(load, POLL_MS);
    } else if (state) {
      setT(state);
    }
    return () => {
      listeners.delete(setT);
      if (listeners.size === 0) {
        window.clearInterval(timer);
        state = undefined; // next mount starts fresh (also keeps tests isolated)
      }
    };
  }, []);
  return t;
}
