import { useEffect, useState } from "react";
import { STATIC, apiBase } from "../lib/api";
import type { LiveSnapshot } from "../lib/types";

export interface LiveState {
  snap: LiveSnapshot | null;
  error: string | null;
  connected: boolean;
}

// One live stream (Server-Sent Events) for the whole app — the top bar, the dashboard and the live terminal share it.
const EMPTY: LiveState = { snap: null, error: null, connected: false };
let state: LiveState = EMPTY;
let stop: (() => void) | null = null;
const listeners = new Set<(s: LiveState) => void>();

function set(p: Partial<LiveState>) {
  state = { ...state, ...p };
  listeners.forEach((l) => l(state));
}

function start(): () => void {
  if (STATIC) {
    set({ error: "Živý terminál zatím běží jen v aplikaci na PC." });
    return () => undefined;
  }
  if (typeof EventSource === "undefined") {
    set({ error: "Tento prohlížeč živý stream neumí." });
    return () => undefined;
  }
  let es: EventSource | null = null;
  let closed = false;
  let retry: ReturnType<typeof setTimeout> | undefined;
  const open = () => {
    es = new EventSource(`${apiBase()}/api/live/stream`);
    es.onopen = () => set({ connected: true, error: null });
    es.onmessage = (e) => set({ snap: JSON.parse(e.data) as LiveSnapshot });
    es.onerror = () => {
      set({ connected: false });
      es?.close();
      fetch(`${apiBase()}/api/live/snapshot`)
        .then(async (r) => (r.ok ? null : ((await r.json()) as { detail?: string }).detail ?? `chyba ${r.status}`))
        .then((msg) => {
          if (closed) return;
          set({ error: msg ?? "Spojení se přerušilo — připojuji znovu…" });
          // the engine is switched off: ask again in a minute, not every 5 s
          retry = setTimeout(open, msg ? 60000 : 5000);
        })
        .catch(() => {
          if (closed) return;
          set({ error: "FTI neodpovídá — připojuji znovu…" });
          retry = setTimeout(open, 5000);
        });
    };
  };
  open();
  return () => {
    closed = true;
    clearTimeout(retry);
    es?.close();
  };
}

export function useLive(): LiveState {
  const [s, setS] = useState(state);
  useEffect(() => {
    listeners.add(setS);
    if (listeners.size === 1) stop = start();
    else setS(state);
    return () => {
      listeners.delete(setS);
      if (listeners.size === 0) {
        stop?.();
        stop = null;
        state = EMPTY;
      }
    };
  }, []);
  return s;
}
