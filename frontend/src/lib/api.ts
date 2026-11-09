import { guardStale } from "./staleGuard";
import type {
  AiAnalysis,
  AiGroqStatus,
  AiRunResult,
  AiStatus,
  AiTestResult,
  AuditRow,
  CalendarAll,
  CandlesResponse,
  MarketsResponse,
  ProbeRow,
  SourcesResponse,
  TickersResponse, IntermarketResult, MarketRegime, GoldAnalysis, LiveCandles } from "./types";

// Same-origin by default (the web build is served by FastAPI itself).
let baseUrl = "";

export function configureApi(url: string): void {
  baseUrl = url.replace(/\/$/, "");
}

/** The API's base URL (same origin unless configured) — for the live stream, which is not a JSON request. */
export function apiBase(): string {
  return baseUrl;
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
  "/api/regime": "data/regime.json",
  "/api/calendar": "data/calendar.json",
  "/api/tickers": "data/tickers.json",
  "/api/data/audit": "data/audit.json",
  "/api/sources": "data/sources.json",
  "/api/ai/analyses": "data/ai.json", // the last AI analyses the cloud made
};

export function staticPath(path: string): string | null {
  const [p, q] = path.split("?");
  const m = p.match(/^\/api\/instruments\/([A-Z0-9.]+)\/candles$/);
  if (m) return `data/candles-${m[1]}-${new URLSearchParams(q ?? "").get("tf")}.json`;
  if (p === "/api/intermarket/intel") return `data/intermarket-${new URLSearchParams(q ?? "").get("tf") ?? "D1"}.json`;
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
  const body = (await response.json()) as T;
  return STATIC ? guardStale(body) : body; // the phone may show a snapshot from hours ago
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
  intermarket: (tf: string) => request<IntermarketResult>(`/api/intermarket/intel?tf=${tf}`),
  regime: () => request<MarketRegime>("/api/regime"),
  /** gold's engine output (technique, verdict, scorecard, COT, seasonality …) — PC app only */
  analysis: (code: string) => request<GoldAnalysis>(`/api/instruments/${code}/analysis`),
  /** candles the live engine builds from ticks (M1 … D1) — PC app only */
  liveCandles: (code: string, tf: string, limit = 500) =>
    request<LiveCandles>(`/api/live/candles?code=${encodeURIComponent(code)}&tf=${tf}&limit=${limit}`),
  tickers: () => (STATIC ? staticTickers() : request<TickersResponse>("/api/tickers")),
  candles: (code: string, tf: string) => request<CandlesResponse>(`/api/instruments/${code}/candles?tf=${encodeURIComponent(tf)}`),
  audit: () => request<{ computed_at: string; rows: AuditRow[] }>("/api/data/audit"),
  sources: () => request<SourcesResponse>("/api/sources"),
  setKey: (name: string, value: string) => post<{ keys: SourcesResponse["keys"] }>("/api/keys", { name, value }),
  updateSettings: (patch: Record<string, unknown>) => post<Record<string, unknown>>("/api/settings", { patch }),
  dataTest: () => post<{ tested_at: string; rows: ProbeRow[] }>("/api/data/test", {}),
  mt5Test: () => post<{ ok: boolean; bars: number; symbol: string; broker: string; server: string }>("/api/mt5/test", {}),
  aiStatus: () => request<AiStatus>("/api/ai/status"),
  aiTest: () => post<AiTestResult>("/api/ai/test", {}),
  aiTestGemini: () => post<AiTestResult>("/api/ai/test-gemini", {}),
  aiAnalyze: (task: string, code?: string) => post<AiRunResult>("/api/ai/analyze", { task, code }),
  aiAnalyses: (code: string, task?: string) =>
    STATIC
      ? request<{ analyses: AiAnalysis[] }>("/api/ai/analyses").then((b) => ({
          analyses: (b.analyses ?? []).filter((a) => a.code === code && (!task || a.task === task)).slice(0, 1),
        }))
      : request<{ analyses: AiAnalysis[] }>(`/api/ai/analyses?code=${encodeURIComponent(code)}${task ? `&task=${encodeURIComponent(task)}` : ""}&limit=1`),
  aiResume: () => post<AiGroqStatus>("/api/ai/resume", {}),
};

// The phone version shows the snapshot quotes exactly as the central price layer produced them
// (with their real quote times). It no longer patches prices in the browser from another call:
// that price would have had no verified quote time and would bypass the central layer.
async function staticTickers(): Promise<TickersResponse> {
  return request<TickersResponse>("/api/tickers");
}
