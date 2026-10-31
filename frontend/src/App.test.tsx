import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { pillar, snapshot } from "./test/fixtures";
import type { Analysis, DashboardResponse, NewsEvent } from "./lib/types";

const STATUS = {
  last_cycle_started_at: "2026-09-28T10:00:00+00:00",
  last_cycle_finished_at: "2026-09-28T10:00:40+00:00",
  cycle_running: false,
  last_cycle_error: null,
  last_cycle_warnings: ["GDELT DOC API nedostupné pro dotaz 'gold': 429"],
  next_scheduled_run_at: "2026-09-28T10:30:00+00:00",
  refresh_interval_minutes: 30,
};

// Fixtures are stamped 2026-09-28 10:00 UTC; "now" is pinned 5 min later so
// the data counts as fresh unless a test moves the clock on.
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-28T10:05:00Z"));
});
afterEach(() => {
  vi.useRealTimers();
});

function dashboardResponse(): DashboardResponse {
  const soon = (code: string, name: string) => ({ code, name, asset_class: "Měny", status: "coming_soon" as const });
  return {
    status: STATUS,
    instruments: [
      {
        code: "XAUUSD", name: "Zlato", asset_class: "Komodita", status: "live",
        summary: {
          computed: true, computed_at: "2026-09-28T10:00:40+00:00", primary_horizon: "1-10d",
          bias: "SHORT", direction: "BEARISH", score: 27.7, score_change: -0.2,
          previous_computed_at: "2026-09-28T09:30:00+00:00",
          main_driver: { pillar: "real_yields", impact: "bearish", points: -20, reason: "výnosy rostou" },
          data_coverage: { backed: 7, ok: 7, partial: 1, unavailable: 0, total: 8 },
          horizons: [],
          next_event: {
            date: "2026-10-28", time: null, event: "Rozhodnutí FOMC o sazbách", importance: "vysoký",
            importance_basis: "b", instruments: ["XAUUSD"], factor: "fed", source_url: "https://www.federalreserve.gov/",
          },
          verdict: {
            action: "short", headline: "ZLATO: DOLŮ — Swing: hledat prodej (short).", direction_text: "ZLATO: DOLŮ",
            action_text: "Swing: hledat prodej (short).", summary: "4 z 5 faktorů ukazuje dolů, 1 nahoru.",
            confidence: "vysoká", trend: "down", trend_label: "Silný klesající trend", change_20d: -5.8,
          },
          mtf: {
            price: 4189.48, price_time: "2026-09-28T10:00:00+00:00",
            timeframes: [{ tf: "M15", direction: "up", word: "Nahoru" }, { tf: "D1", direction: "down", word: "Dolů" }],
            intraday: null, overall: null,
            swing: { key: "swing", label: "Swingový trend", direction: "down", lean: "down", word: "Dolů", score: -0.8, timeframes: [], agree: [] },
          },
          dxy: {
            price: 101.9, corr60: -0.5, effect_on_gold: -0.7, text: "Posilující dolar teď na zlato tlačí dolů.",
            swing: { key: "swing", label: "Swingový trend", direction: "up", lean: "up", word: "Nahoru", score: 0.8, timeframes: [], agree: [] },
          },
        },
      },
      soon("EURUSD", "Euro / americký dolar"), soon("GBPUSD", "Britská libra / americký dolar"), soon("USDJPY", "Americký dolar / japonský jen"),
      soon("US100", "Nasdaq 100"), soon("US500", "S&P 500"), soon("WTI", "Ropa WTI"), soon("BTCUSD", "Bitcoin"),
    ],
  };
}

function analysisResponse(): Analysis {
  const history = Array.from({ length: 180 }, (_, i) => ({
    date: new Date(Date.UTC(2026, 3, 1) + i * 86400000).toISOString().slice(0, 10),
    close: 2700 - i * 0.5,
    sma50: 2720 - i * 0.4,
    sma200: 2800 - i * 0.2,
  }));
  return {
    computed_at: "2026-09-28T10:00:40+00:00",
    technical: {
      as_of: "2026-09-28", trend: "down", trend_label: "Silný klesající trend", trend_score: -70, tech_score: -68.9,
      components: [],
      groups: [
        { key: "trend", title: "Trend", items: [
          { name: "Týdenní trend", value: "dolů", signal: -1, text: "Na týdenním grafu je cena pod 40týdenním průměrem.", weight: 15 },
        ] },
        { key: "momentum", title: "Momentum", items: [
          { name: "MACD (12, 26, 9)", value: "pod signálem", signal: -1, text: "MACD je pod signální linkou už 20 dní — medvědí momentum sílí.", weight: 12 },
          { name: "RSI (14)", value: "39", signal: -1, text: "RSI 39 — prodávající mají mírnou převahu.", weight: 8 },
        ] },
        { key: "volatility", title: "Volatilita a natažení", items: [
          { name: "Bollingerova pásma (20, 2)", value: "7 %", signal: 0, text: "Cena je u dolního pásma.", weight: 0 },
        ] },
      ],
      trend_age_days: 5, trend_age_text: "Cena je pod 50denním průměrem už 5 obchodních dní.",
      last_cross: { type: "death", date: "2026-05-07", days_ago: 99 },
      rsi14: 39, rsi_state: "neutrální", divergence: null, macd_bullish: false, bollinger_pct_b: 7, squeeze: false,
      changes: { "1d": -3.71, "5d": -4.54, "20d": -5.8, "60d": -2.93, "250d": -16.75 },
      volatility20: 22.9,
      supports: [{ label: "Roční minimum", pct: -1.61, touches: 3 }],
      resistances: [{ label: "Cenová zóna", pct: 1.09, touches: 2 }, { label: "50denní průměr", pct: 3.47, touches: 3 }],
      fibonacci: [{ ratio: 0.382, pct: 6.22 }, { ratio: 0.618, pct: 11.4 }],
      fibonacci_text: "Poslední velký pohyb byl pokles o 18,3 %.",
      sma50_pct: 3.47, sma200_pct: 13.6,
      history,
    },
    correlations: [
      { key: "usd", label: "Americký dolar (index)", fred_id: "DTWEXBGS", unit: "%", available: true, corr_now: -0.5, corr_usual: -0.36,
        strength: "silná", move20: 1.67, effect: -1, unusual: false },
    ],
    gold_vol: null,
    cot: {
      as_of: "2026-09-22", spec_net: 225853, spec_long: 253982, spec_short: 28129, comm_net: -262903, open_interest: 412800,
      spec_long_share: 61.5, change_1w: -4485, change_4w: -17481, cot_index_3y: 63.3, cot_index_1y: 72.6, extreme: "neutral",
      signal: -0.308,
      source: "disaggregated", source_label: "CFTC podrobný report",
      schedule: { published: "2026-09-25T19:30:00+00:00", next_release: "2026-10-02T19:30:00+00:00", next_data_date: "2026-09-29", late: false },
      groups: [
        { key: "spec_net", label: "Hedgeové fondy (managed money)", who: "Spekulují na směr.", net: 127389, long: 135699, short: 8310,
          change_1w: -5727, change_4w: -17358, index_3y: 62.7 },
        { key: "swap_net", label: "Banky a swap dealeři", who: "Zajišťují obchody.", net: -236126, long: 14626, short: 250752,
          change_1w: -2466, change_4w: 100, index_3y: 14.8 },
      ],
      long_short_ratio: 16.3,
      texts: ["Pozice fondů mluví spíše pro pokles zlata.", "Fondy za poslední 4 týdny prodávají (−17 481 kontraktů, za týden −4 485).",
              "COT index 63/100: pozice fondů nejsou extrémní."],
      history: Array.from({ length: 156 }, (_, i) => ({ date: new Date(Date.UTC(2023, 9, 3) + i * 7 * 86400000).toISOString().slice(0, 10),
        spec_net: 150000 + i * 500, comm_net: -180000 })),
    },
    news: {
      hours: 72, count: 8, bullish: 2, bearish: 6, score: -0.4, top: [],
      key: [
        { title: "Zlato padá, Fed zůstává jestřábí", translated: true, source: "FXStreet", url: "https://x/1",
          published_at: "2026-09-28T09:00:00+00:00", impact: "bearish", factors: ["Fed a sazby"], gold: true },
      ],
    },
    mtf: {
      timeframes: (["M15", "H1", "H4", "D1", "W1"] as const).map((tf, i) => ({
        tf, tf_label: tf, direction: i < 2 ? ("up" as const) : ("down" as const), word: i < 2 ? "Nahoru" : "Dolů",
        score: i < 2 ? 0.6 : -0.8, strength: "střední", adx: 22, close: 4189.48, ema20: 4180, ema50: 4200, atr: 12.5,
        change_pct: i < 2 ? 0.4 : -2.1, change_bars: 20, swing_high: 4250, swing_low: 4120, text: "Cena pod EMA50.",
        as_of: "2026-09-28T10:00:00+00:00",
      })),
      intraday: { key: "intraday", label: "Intradenní trend", direction: "sideways", lean: "up", word: "Spíše nahoru", score: 0.25,
        timeframes: ["M15", "H1", "H4"], agree: [] },
      swing: { key: "swing", label: "Swingový trend", direction: "down", lean: "down", word: "Dolů", score: -0.8,
        timeframes: ["H4", "D1", "W1"], agree: ["H4", "D1", "W1"] },
      overall: { key: "overall", label: "Celkový trend", direction: "down", lean: "down", word: "Dolů", score: -0.45,
        timeframes: ["M15", "H1", "H4", "D1", "W1"], agree: ["H4", "D1", "W1"] },
      advice: "Hlavní trend je dolů, intradenně jde o korekci nahoru.",
      price: 4189.48, price_time: "2026-09-28T10:00:00+00:00", price_text: "4 189,48 $",
    },
    scorecard: {
      items: [
        { key: "fed", label: "Fed a sazby", score: -3, group: "fundament" },
        { key: "dxy", label: "Dolar (DXY)", score: -4, group: "trhy" },
        { key: "news", label: "Zprávy", score: null, group: "sentiment" },
      ],
      final: -5, final_label: "Medvědí", note: "Každý faktor −5 až +5.",
    },
    summary: {
      date: "2026-09-28", text: "ZLATO: DOLŮ. Cena 4 189,48 $, swingový trend je dolů.", bullets: ["Aktuální cena: 4 189,48 $"],
      outlook: ["Nejbližší odpor 4 235 $"], note: "Automaticky složeno podle pevných pravidel — není to AI.",
    },
    decision: {
      headline: "Teď platí 3 podmínek pro pokles a 0 pro růst (pro pokles).",
      bull: [{ kind: "price", title: "Průraz nad 4 235 $", detail: "nejbližší odpor", active: false }],
      bear: [{ kind: "cot", title: "Fondy dál prodávají", detail: "COT", active: true }],
      events: [{ name: "Inflace CPI (USA)", date: "2026-10-15", time: "14:30", importance: 3, up_if: "inflace zpomalí", down_if: "inflace bude vyšší" }],
      levels: {}, active_bull: 0, active_bear: 1,
    },
    seasonality: {
      months: Array.from({ length: 12 }, (_, i) => ({ month: i + 1, name: "měsíc", avg: i === 9 ? 1.0 : -0.2, median: 0, win_rate: 60, years: 6,
        by_year: [{ year: 2024, ret: i === 9 ? 2.5 : -0.4 }] })),
      current_month: 10, current_text: "Říjen bývá pro zlato silný: průměrně +1,0 %, růst v 67 % let.", next_text: "Listopad nemá výrazný sklon.",
      signal: 0.1, years_from: 2019, years_to: 2026, note: "Jen ~7 let.",
    },
    sources_status: [
      { key: "price", label: "Cena zlata a svíčky M15–W1", provider: "Kraken PAXG/USD", rhythm: "živě", as_of: "2026-10-02T20:45:00+00:00",
        status: "closed", note: "Spotový trh je zavřený." },
      { key: "gvz", label: "Volatilita zlata (GVZ)", provider: "FRED GVZCLS", rhythm: "denně", as_of: "2026-09-10", status: "late", note: "" },
    ],
    dxy: {
      price: 101.904,
      trends: {
        timeframes: [], intraday: null, overall: null, advice: "", price: 101.9, price_time: null, price_text: "101,90",
        swing: { key: "swing", label: "Swingový trend", direction: "up", lean: "up", word: "Nahoru", score: 0.8, timeframes: [], agree: [] },
      },
      correlation: { d60: { value: -0.5, beta: -2.89, bars: 60, label: "střední opačná" }, h1: { value: -0.34, beta: -1.6, bars: 120, label: "slabá opačná" } },
      effect_on_gold: -0.7, text: "Posilující dolar teď na zlato tlačí dolů.",
      overlay: [{ date: "2026-09-01", gold: 0, dxy: 0 }, { date: "2026-09-02", gold: -1, dxy: 0.5 }],
      levels: { swing_high: 102.2, swing_low: 101.49 }, source: "Přepočet podle vzorce ICE.", verified: "Ověřeno.",
    },
    calendar: {
      events: [
        { key: "cpi", up_if: "inflace zpomalí", down_if: "inflace bude vyšší", date: "2026-10-15", time: "14:30", datetime: "2026-10-15T12:30:00+00:00", name: "Inflace CPI (USA)", original: "Consumer Price Index",
          importance: 3, impact: "Vyšší inflace → zlato obvykle dolů.", previous: "jádrová inflace CPI 3,1 % r/r (za 8/2026)", forecast: null,
          source: "BLS", past: false },
      ],
      next_high: null, timezone: "Europe/Prague", notes: ["Prognózy (konsenzus trhu) zdarma a legálně k dispozici nejsou."], sources: [],
    },
    verdict: {
      action: "short", direction_text: "ZLATO: DOLŮ", action_text: "Swing: hledat prodej (short).",
      headline: "ZLATO: DOLŮ — Swing: hledat prodej (short).", summary: "4 z 5 faktorů ukazuje dolů, 1 nahoru.",
      confidence: "vysoká", combined: -0.55,
      factors: [
        { key: "fundament", label: "Fundament (makro)", score: -0.45, direction: "down", weight: 0.35, detail: "skóre 27,7/100",
          sentence: "Makro mluví pro pokles zlata — reálné výnosy rostou a Fed je jestřábí (vyšší sazby)." },
        { key: "technika", label: "Technická analýza", score: -0.69, direction: "down", weight: 0.35, detail: "skóre −69",
          sentence: "Silný klesající trend, MACD pod signálem, RSI 39 (neutrální)." },
        { key: "cot", label: "Fondy (COT)", score: -0.31, direction: "down", weight: 0.1, detail: "COT index 63/100",
          sentence: "Fondy za poslední 4 týdny prodávají (−17 481 kontraktů, za týden −4 485)." },
        { key: "zpravy", label: "Zprávy", score: -0.4, direction: "down", weight: 0.1, detail: "8 zpráv za 72 h",
          sentence: "Za poslední 3 dny 2 zpráv mluví pro růst a 6 pro pokles zlata." },
        { key: "trhy", label: "Ostatní trhy", score: 0.2, direction: "up", weight: 0.1, detail: "1 brzdí, 2 pomáhá",
          sentence: "Zlato brzdí: americký dolar; pomáhá: strach na akciích, bitcoin." },
      ],
      components: {}, weights: {},
      reasons: [],
      timing: "Prodej hledat při odrazu k odporu (+1,1 %), ne na minimech.",
      support: { label: "Roční minimum", pct: -1.61, price: 4122 },
      resistance: { label: "Cenová zóna", pct: 1.09, price: 4235 },
      risks: ["Rozhodnutí Fedu (FOMC) 28. 10. 2026 může výhled rychle změnit."],
      change_view: ["Návrat ceny nad 200denní průměr (+13,6 %)."],
    },
    sources: {},
  };
}

const NEWS: NewsEvent[] = [
  {
    event_id: 1, headline: "Fed zvažuje další zvýšení sazeb", headline_original: "Fed weighs another rate hike", translated: true, language: "en",
    source: "FXStreet", url: "https://www.fxstreet.com/a",
    published_at: "2026-09-28T08:00:00+00:00", instrument_tags: [], factors: [{ factor: "fed_tone", pillar: "fed", sentiment: -1 }],
    impact: "bearish", report_count: 2,
    reports: [
      { id: 1, title: "Fed zvažuje další zvýšení sazeb", title_original: "Fed weighs another rate hike", translated: true, source: "FXStreet",
        url: "https://www.fxstreet.com/a", published_at: "2026-09-28T08:00:00+00:00" },
      { id: 2, title: "Fed hike talk", title_original: "Fed hike talk", translated: false, source: "gdelt:reuters.com",
        url: "https://reuters.com/b", published_at: "2026-09-28T09:00:00+00:00" },
    ],
  },
  {
    event_id: 3, headline: "Zlato se drží u minim", headline_original: "Zlato se drží u minim", translated: false, language: "cs",
    source: "fxstreet.cz", url: "https://www.fxstreet.cz/c", published_at: "2026-09-28T07:00:00+00:00",
    instrument_tags: ["XAUUSD"], factors: [], impact: "neutral", report_count: 1, reports: [],
  },
];

function candles(base: number, url = "") {
  const rows = Array.from({ length: 120 }, (_, i) => {
    const c = base * (1 - (120 - i) * 0.0005);
    return [1790000000 + i * 14400, c * 0.999, c * 1.002, c * 0.997, c, c * 1.001, c * 1.003];
  });
  return { tf: new URL(url, "http://x").searchParams.get("tf") ?? "H4", source: "Kraken PAXG/USD", candles: rows, trend: {}, fetched_at: "2026-09-28T10:04:00+00:00" };
}

function mockBackend(overrides: Record<string, (url?: string) => Response> = {}) {
  const positioning = pillar({ weight: 7, points: -1.03, raw_signal: -0.147, impact: "bearish", reasons: ["CFTC net long kleslo"], source: "CFTC COT" });
  const scores = Object.fromEntries(
    (["intraday", "1-3d", "1-10d", "1-4w", "1-3m"] as const).map((h) => [h, snapshot({ horizon: h, score: 49.49 }, { positioning })]),
  );
  const routes: Record<string, (url?: string) => Response> = {
    "/api/dashboard": () => Response.json(dashboardResponse()),
    "/api/instruments/XAUUSD/scores": () => Response.json(scores),
    "/api/instruments/XAUUSD/news": () => Response.json({ events: NEWS, total_events: 2 }),
    "/api/events/upcoming": () => {
      const summary = dashboardResponse().instruments[0].summary;
      return Response.json({ events: summary?.computed ? [summary.next_event] : [], coverage_note: "Jen FOMC." });
    },
    "/api/instruments/XAUUSD/history": () => Response.json([]),
    "/api/instruments/XAUUSD/analysis": () => Response.json(analysisResponse()),
    "/api/tickers": () => Response.json({
      live: [{ symbol: "PAXGUSD", label: "Zlato", price: 4189.48, digits: 2, change_pct: -0.98, source: "Kraken", live: true }],
      daily: [{ symbol: "spx", label: "S&P 500", price: 6771.24, digits: 2, change_pct: 0.19, source: "FRED", live: false, as_of: "2026-09-25" }],
      error: null, fetched_at: "2026-09-28T10:04:00+00:00",
      market: { open: false, reason: "víkend", next_open: "2026-10-04T22:00:00+00:00", closes_at: null, weekly_close: false },
      price_check: { quotes: { "PAXG (Kraken)": 4142.83, "BullionVault (fyzické zlato, Londýn)": 4143.92 }, gaps_pct: { "PAXG (Kraken)": 0, "BullionVault (fyzické zlato, Londýn)": 0.03 },
        max_gap_pct: 0.03, ok: true, text: "Zdroje se shodují (největší rozdíl 0,03 %)." },
      weekend: { spot_close: 4150.26, spot_close_time: "2026-10-02T21:00:00+00:00", paxg_now: 4142.83, change_pct: -0.18 },
    }),
    "/api/instruments/XAUUSD/candles": (url?: string) => Response.json(candles(4189, url)),
    "/api/instruments/DXY/candles": (url?: string) => Response.json(candles(101.9, url)),
    ...overrides,
  };
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input).split("?")[0];
    const handler = routes[path];
    return handler ? handler(String(input)) : new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
  });
}

describe("Home", () => {
  it("shows an error state with retry when the backend is down", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    window.location.hash = "#/";
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Aplikace neběží");
    expect(screen.getByRole("button", { name: "Zkusit znovu" })).toBeInTheDocument();
  });
});

function openTab(tab = "") {
  mockBackend();
  window.location.hash = `#/instrument/XAUUSD${tab ? `/${tab}` : ""}`;
  render(<App />);
}

describe("XAUUSD detail", () => {
  it("answers first: direction, what to do, final score, written summary and factor scores", async () => {
    openTab();
    const verdict = (await screen.findByRole("heading", { name: /ZLATO: DOLŮ/ })).closest("section")!;
    expect(within(verdict).getByText("Swing: hledat prodej (short).")).toBeInTheDocument();
    expect(within(verdict).getByText("Medvědí")).toBeInTheDocument();
    const summary = screen.getByRole("heading", { name: /Shrnutí/ }).closest("section")!;
    expect(within(summary).getByText(/swingový trend je dolů/)).toBeInTheDocument();
    expect(within(summary).getByText(/není to AI/)).toBeInTheDocument();
    const scores = screen.getByRole("heading", { name: /Skóre faktorů/ }).closest("section")!;
    expect(within(scores).getByText("Dolar (DXY)")).toBeInTheDocument();
    expect(within(scores).getByText("−4")).toBeInTheDocument();
    expect(within(scores).getByTitle("data nejsou k dispozici")).toBeInTheDocument();
  });

  it("draws a live candlestick chart and switches timeframe", async () => {
    openTab();
    const chart = await screen.findByRole("img", { name: /Graf XAUUSD, timeframe H4, posledních 120 svíček/ });
    expect(chart.querySelectorAll(".cc-candles g").length).toBe(120);
    fireEvent.click(screen.getAllByRole("button", { name: "D1" })[0]);
    expect(await screen.findByRole("img", { name: /Graf XAUUSD, timeframe D1/ })).toBeInTheDocument();
  });

  it("shows the trend on every timeframe plus intraday, swing and overall", async () => {
    openTab();
    const board = (await screen.findByRole("heading", { name: /Trend podle timeframu/ })).closest("section")!;
    expect(within(board).getByRole("group", { name: /^M15: Nahoru/ })).toBeInTheDocument();
    expect(within(board).getByRole("group", { name: /^W1: Dolů/ })).toBeInTheDocument();
    expect(within(board).getByText("Spíše nahoru")).toBeInTheDocument();
    expect(within(board).getByText(/korekci nahoru/)).toBeInTheDocument();
  });

  it("lists what decides the direction, marking what holds right now", async () => {
    openTab();
    const dec = (await screen.findByRole("heading", { name: /Co rozhodne o směru/ })).closest("section")!;
    expect(within(dec).getByText("Průraz nad 4 235 $")).toBeInTheDocument();
    expect(within(dec).getByText("Fondy dál prodávají")).toBeInTheDocument();
    expect(within(dec).getByText("platí teď")).toBeInTheDocument();
    expect(within(dec).getByText(/inflace zpomalí/)).toBeInTheDocument();
  });

  it("shows the economic calendar as a table; a click explains how the release moves gold", async () => {
    openTab("calendar");
    const cal = (await screen.findByRole("heading", { name: /Ekonomický kalendář/ })).closest("section")!;
    expect(within(cal).getByText("14:30")).toBeInTheDocument();
    expect(within(cal).getByText(/3,1 % r\/r/)).toBeInTheDocument();
    fireEvent.click(within(cal).getByRole("button", { name: "Inflace CPI (USA)" }));
    expect(within(cal).getByText(/zlato nahoru, když inflace zpomalí/)).toBeInTheDocument();
  });

  it("shows the technical tab as chart + gauge + signal lights, details folded away", async () => {
    openTab("tech");
    expect(await screen.findByRole("figure", { name: /−7 z ±10, Silně medvědí/ })).toBeInTheDocument();
    expect(screen.getAllByText("Momentum").length).toBeGreaterThan(0);
    expect(screen.getByText("Podrobně: všechny ukazatele, Fibonacci, změny ceny")).toBeInTheDocument();
  });

  it("shows COT per trader group with long/short rings and the report schedule", async () => {
    openTab("cot");
    expect(await screen.findByRole("figure", { name: /Hedgeové fondy \(managed money\): long 94 %/ })).toBeInTheDocument();
    expect(screen.getByRole("figure", { name: /Banky a swap dealeři: long 6 %/ })).toBeInTheDocument();
    expect(screen.getByText("Další report (obvykle)")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Vývoj čisté pozice fondů/ })).toBeInTheDocument();
  });

  it("shows gold's seasonality by month", async () => {
    openTab("season");
    expect(await screen.findByText(/Říjen bývá pro zlato silný/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Průměrná měsíční změna ceny zlata" })).toBeInTheDocument();
  });

  it("shows news in Czech, marks machine translation and keeps context-only news separate", async () => {
    openTab("news");
    expect(await screen.findByText("Fed zvažuje další zvýšení sazeb")).toBeInTheDocument();
    expect(screen.getAllByText(/strojový překlad/).length).toBeGreaterThan(0);
    expect(screen.getByText(/2 zdroje o téže události/)).toBeInTheDocument();
    expect(screen.getByText(/Další zprávy o zlatě \(1\)/)).toBeInTheDocument();
  });

  it("keeps the full fundamental breakdown in its own tab", async () => {
    openTab("fund");
    expect(await screen.findByRole("heading", { name: "Fundament" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Korelace" })).not.toBeInTheDocument(); // removed on request
    expect(screen.getByText("Podrobný rozbor fundamentu")).toBeInTheDocument();
  });

  it("shows live quotes in the ticker strip, daily closes marked as such", async () => {
    openTab();
    const strip = await screen.findByRole("region", { name: "Kurzy trhů" });
    expect(within(strip).getByText("Zlato")).toBeInTheDocument();
    expect(within(strip).getByText("D")).toBeInTheDocument();
  });

  it("says plainly when the spot market is closed and what the weekend token price does", async () => {
    openTab();
    const banner = await screen.findByText(/Spotový trh se zlatem je zavřený \(víkend\)/);
    expect(banner.closest("[role=status]")).toHaveTextContent("−0,18 %");
    expect(await screen.findByRole("button", { name: /1 zdroj zpožděný/ })).toBeInTheDocument();
  });

  it("lists every source with its date and status, and cross-checks the gold price", async () => {
    openTab("sources");
    expect(await screen.findByText("Cena zlata a svíčky M15–W1")).toBeInTheDocument();
    expect(screen.getByText("trh zavřen")).toBeInTheDocument();
    expect(screen.getByText("zpožděné")).toBeInTheDocument();
    expect(await screen.findByText(/Zdroje se shodují/)).toBeInTheDocument();
  });

  it("says when the analysis is not computed yet", async () => {
    mockBackend({ "/api/instruments/XAUUSD/analysis": () => new Response(JSON.stringify({ detail: "x" }), { status: 404 }) });
    window.location.hash = "#/instrument/XAUUSD";
    render(<App />);
    expect(await screen.findByText(/Rozbor se spočítá při první aktualizaci dat/)).toBeInTheDocument();
  });

  it("shows coming soon for an instrument without an engine", async () => {
    mockBackend();
    window.location.hash = "#/instrument/EURUSD";
    render(<App />);
    expect(await screen.findByText(/Připravujeme — rozbor pro EURUSD zatím není hotový/)).toBeInTheDocument();
    expect(screen.queryByText(/\/100/)).not.toBeInTheDocument();
  });
});
