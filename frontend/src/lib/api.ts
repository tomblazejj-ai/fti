import type {
  Analysis,
  CandlesResponse,
  DashboardResponse,
  HistoryDetail,
  HistoryEntry,
  Horizon,
  CalendarAll,
  MarketsResponse,
  Metodika,
  NewsEvent,
  ScoreSnapshot,
  SystemStatus,
  TickersResponse,
  TraHistory,
  UpcomingEvent,
} from "./types";

// Same-origin by default (the web build is served by FastAPI itself). A
// native app would call configureApi("https://your-host") once at startup.
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
  "/api/status": "data/status.json",
  "/api/dashboard": "data/dashboard.json",
  "/api/tickers": "data/tickers.json",
  "/api/metodika": "data/metodika.json",
};

export function staticPath(path: string): string | null {
  const [p, q] = path.split("?");
  const params = new URLSearchParams(q ?? "");
  const m = p.match(/^\/api\/instruments\/([A-Z]+)\/(analysis|scores|news|candles|tra-history)$/);
  if (m) {
    const [, code, what] = m;
    if (what === "candles") return `data/candles-${code}-${params.get("tf")}.json`;
    if (what === "tra-history") return `data/tra-${code}.json`;
    return `data/${what}-${code}.json`;
  }
  return STATIC_FILES[p] ?? null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  let url = `${baseUrl}${path}`;
  if (STATIC) {
    const file = staticPath(path);
    if (!file || (init?.method && init.method !== "GET")) throw new ApiError(404, "V mobilní verzi tahle část není — otevři ji v aplikaci na PC.");
    url = file;
  }
  try {
    response = await fetch(url, STATIC ? { cache: "no-cache" } : init);
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

export const api = {
  dashboard: () => request<DashboardResponse>("/api/dashboard"),
  status: () => request<SystemStatus>("/api/status"),
  scores: (code: string) => request<Record<Horizon, ScoreSnapshot>>(`/api/instruments/${code}/scores`),
  analysis: (code: string) => request<Analysis>(`/api/instruments/${code}/analysis`),
  news: (code: string) => request<{ events: NewsEvent[]; total_events: number }>(`/api/instruments/${code}/news`),
  upcomingEvents: () => request<{ events: UpcomingEvent[]; coverage_note: string }>("/api/events/upcoming"),
  history: (code: string, horizon: Horizon) =>
    request<HistoryEntry[]>(`/api/instruments/${code}/history?horizon=${encodeURIComponent(horizon)}`),
  historyEntry: (code: string, id: number) => request<HistoryDetail>(`/api/instruments/${code}/history/${id}`),
  tickers: () => (STATIC ? staticTickers() : request<TickersResponse>("/api/tickers")),
  candles: (code: string, tf: string) => request<CandlesResponse>(`/api/instruments/${code}/candles?tf=${encodeURIComponent(tf)}`),
  refresh: (code: string) => request<ScoreSnapshot>(`/api/instruments/${code}/refresh`, { method: "POST" }),
  traHistory: async (code: string, days: number) => {
    const h = await request<TraHistory>(`/api/instruments/${code}/tra-history?days=${days}`);
    if (!STATIC) return h;
    const from = Date.now() - days * 86400000;
    return { ...h, points: h.points.filter((p) => Date.parse(p.t) >= from) };
  },
  metodika: () => request<Metodika>("/api/metodika"),
  markets: () => request<MarketsResponse>("/api/markets"),
  calendar: () => request<CalendarAll>("/api/calendar"),
};

// Kraken's public API allows browser requests, so the phone version shows live prices
// on top of the snapshot (which is at most ~30 minutes old).
const KRAKEN = { PAXGUSD: "PAXGUSD", EURUSD: "ZEURZUSD", GBPUSD: "ZGBPZUSD" } as const;

async function staticTickers(): Promise<TickersResponse> {
  const snap = await request<TickersResponse>("/api/tickers");
  try {
    const r = await fetch(`https://api.kraken.com/0/public/Ticker?pair=${Object.keys(KRAKEN).join(",")}`);
    const body = await r.json();
    const result = body?.result ?? {};
    const live = snap.live.map((q) => {
      const key = KRAKEN[q.symbol as keyof typeof KRAKEN];
      const row = key ? result[key] : undefined;
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
