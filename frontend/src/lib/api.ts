import type { AuditRow, CalendarAll, CandlesResponse, MarketsResponse, ProbeRow, SourcesResponse, TickersResponse } from "./types";

// Same-origin by default (the web build is served by FastAPI itself).
let baseUrl = "";

export function configureApi(url: string): void {
  baseUrl = url.replace(/\/$/, "");
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** The phone version (VITE_STATIC=1) reads a snapshot of every API answer from data/*.json. */
export const STATIC = import.meta.env.VITE_STATIC === "1";

const STATIC_FILES: Record<string, string> = {
  "/api/markets": "data/markets.json",
  "/api/calendar": "data/calendar.json",
  "/api/tickers": "data/tickers.json",
  "/api/data/audit": "data/audit.json",
  "/api/sources": "data/sources.json",
};

export function staticPath(path: string): string | null {
  const [p, q] = path.split("?");
  const m = p.match(/^\/api\/instruments\/([A-Z0-9.]+)\/candles$/);
  if (m) return `data/candles-${m[1]}-${new URLSearchParams(q ?? "").get("tf")}.json`;
  return STATIC_FILES[p] ?? null;
}

async function request<T>(path: string): Promise<T> {
  let response: Response;
  let url = `${baseUrl}${path}`;
  if (STATIC) {
    const file = staticPath(path);
    if (!file) throw new ApiError(404, "V mobilní verzi tahle část není — otevři ji v aplikaci na PC.");
    url = file;
  }
  try {
    response = await fetch(url, STATIC ? { cache: "no-cache" } : undefined);
  } catch {
    throw new ApiError(
      0,
      STATIC
        ? "Bez připojení k internetu — zobrazují se poslední uložená data, pokud nějaká jsou."
        : "Aplikace neběží nebo se teprve spouští. Otevři ji ikonou FTI na ploše a chvíli počkej.",
    );
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* non-JSON error body — keep the status line */
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  if (STATIC) throw new ApiError(404, "Nastavení jde měnit jen v aplikaci na PC.");
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "Aplikace neběží.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, String(data?.detail ?? response.statusText));
  return data as T;
}

export const api = {
  markets: () => request<MarketsResponse>("/api/markets"),
  calendar: () => request<CalendarAll>("/api/calendar"),
  tickers: () => (STATIC ? staticTickers() : request<TickersResponse>("/api/tickers")),
  candles: (code: string, tf: string) => request<CandlesResponse>(`/api/instruments/${code}/candles?tf=${encodeURIComponent(tf)}`),
  audit: () => request<{ computed_at: string; rows: AuditRow[] }>("/api/data/audit"),
  sources: () => request<SourcesResponse>("/api/sources"),
  setKey: (name: string, value: string) => post<{ keys: SourcesResponse["keys"] }>("/api/keys", { name, value }),
  updateSettings: (patch: Record<string, unknown>) => post<Record<string, unknown>>("/api/settings", { patch }),
  dataTest: () => post<{ tested_at: string; rows: ProbeRow[] }>("/api/data/test", {}),
  mt5Test: () => post<{ ok: boolean; bars: number; symbol: string; broker: string; server: string }>("/api/mt5/test", {}),
};

// Kraken's public API allows browser requests, so the phone version shows live prices
// on top of the snapshot (which is at most ~30 minutes old).
const KRAKEN = { PAXGUSD: "PAXGUSD", EURUSD: "ZEURZUSD", GBPUSD: "ZGBPZUSD", BTCUSD: "XXBTZUSD", ETHUSD: "XETHZUSD" } as const;

async function staticTickers(): Promise<TickersResponse> {
  const snap = await request<TickersResponse>("/api/tickers");
  try {
    const r = await fetch(`https://api.kraken.com/0/public/Ticker?pair=${Object.values(KRAKEN).join(",")}`);
    const body = await r.json();
    const result = body?.result ?? {};
    const live = snap.live.map((q) => {
      const key = KRAKEN[q.symbol as keyof typeof KRAKEN];
      const row = key && q.provider === "kraken" ? result[key] : undefined;  // only refresh a quote from its own feed
      if (!row) return q;
      const last = Number(row.c[0]);
      const open = Number(row.o);
      return { ...q, price: last, change_pct: open ? Math.round((last / open - 1) * 10000) / 100 : q.change_pct };
    });
    return { ...snap, live, fetched_at: new Date().toISOString() };
  } catch {
    return snap; // offline or blocked: the snapshot prices, marked by their time
  }
}
