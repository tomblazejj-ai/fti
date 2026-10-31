import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { Analysis, TradeSetup, Zone } from "./lib/types";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-17T10:05:00Z"));
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function zone(o: Partial<Zone>): Zone {
  return {
    tf: "D1", kind: "supply", lo: 4259, hi: 4308, proximal: 4259, distal: 4308, formed: "2026-09-25T00:00:00+00:00", touches: 0,
    fresh: true, last_touch: null, pivots: 3, strength: 70, departure_atr: 1.6, distance_pct: 2.5, inside: false, activity: "active",
    activity_ratio: 1.3, poc: 4300, in_weekly: false, ...o,
  };
}

function setup(o: Partial<TradeSetup>): TradeSetup {
  return {
    side: "short", zone: zone({}), weekly: null, ok: 4, total_checks: 6, grade: "B", verdict: "Použitelný setup, ale něco chybí.",
    checks: [
      { key: "weekly", label: "Týdenní zóna", state: "bad", text: "Zóna je jen na denním grafu — metodika začíná na týdenním, setup je proto slabší." },
      { key: "daily", label: "Denní zóna pro přesný vstup", state: "ok", text: "Denní zóna 4 259–4 308 $." },
      { key: "activity", label: "Aktivita v zóně", state: "ok", text: "Cena tu v minulosti strávila hodně času. (Čas na ceně místo objemu z futures.)" },
      { key: "score", label: "Fundament (skóre)", state: "ok", text: "Skóre −7 — fundament směr potvrzuje." },
      { key: "cot", label: "COT", state: "ok", text: "COT −1 z ±3. Open interest za 4 týdny −3,3 %." },
      { key: "season", label: "Sezónnost", state: "na", text: "Příštích 30 dní: zlato rostlo v 4 z 10 let, průměr +0,1 %." },
    ],
    plan: { entry: 4259, poc: 4300, stop: 4326, target: 4126, target_zone: null, rr: 2, risk_usd: 67 },
    state: "waiting", where: "Cena je 2,5 % od vstupu — čekej, až k zóně dojde.", ...o,
  };
}

function analysis(): Analysis {
  return {
    computed_at: "2026-10-17T10:00:00+00:00",
    verdict: { support: null, resistance: null },
    technical: null, correlations: null, gold_vol: null, cot: null, news: { count: 12 }, sources: {},
    calendar: {
      events: [{ key: "fomc", date: "2026-10-28", time: "19:00", datetime: "2026-10-28T18:00:00+00:00", name: "Rozhodnutí Fedu o sazbách (FOMC)",
        original: "FOMC", importance: 3, impact: "", previous: null, forecast: null, source: "Fed", past: false }],
      next_high: null, timezone: "Europe/Prague", notes: [], sources: [], rules: { lock_hours: 2, confirm_minutes: 60 },
    },
    tra: {
      as_of: "2026-10-17T10:00:00+00:00",
      xau: { total: -7, max: 25, missing: [], word: "Medvědí", strength: "", arrow: "down", components: [
        { key: "cot", label: "COT bias", score: -1, max: 3, reason: "", inputs: [], usd_score: null, proxy: null }] },
      usd: { total: 9, max: 25, missing: [], word: "Býčí", strength: "silně ", arrow: "up", components: [] },
      momentum: { xau: { current: -7, changes: { "24h": -2, "7d": -2, "30d": -1 }, speed_text: "skóre klesá", idea: null, situations: [] }, usd: null },
    },
    zones: { price: 4157, atr_d1: 71.5, tf: { D1: { demand: [zone({ kind: "demand", lo: 4039, hi: 4064, proximal: 4064, distal: 4039, in_weekly: true })],
      supply: [zone({})] } }, method: "Zóna = základna před prudkým pohybem." },
    setup: {
      action: "wait", primary: "short", bias: "short", timing: [], note: "Není to investiční doporučení.", computed_at: "2026-10-17T10:00:00+00:00",
      headline: "Čekej na SHORT u supply zóny 4 259–4 308 $ (2,5 % od ceny). Potvrzení 4 z 6, setup B.",
      other_text: "Opačný směr: LONG u zóny 4 039–4 064 $ — 3 z 6 potvrzení.",
      setups: {
        short: setup({}),
        long: setup({ side: "long", ok: 3, grade: "C", verdict: "Slabý setup — víc proti než pro.",
          zone: zone({ kind: "demand", lo: 4039, hi: 4064, proximal: 4064, distal: 4039, in_weekly: true }),
          checks: [{ key: "score", label: "Fundament (skóre)", state: "bad", text: "Skóre −7 — fundament jde proti." }],
          plan: { entry: 4064, poc: null, stop: 4021, target: 4259, target_zone: null, rr: 4.5, risk_usd: 43 } }),
      },
    },
    weekly: {
      monday: "2026-10-19", friday: "2026-10-23", next_week: true, title: "Plán na příští týden",
      days: ["19", "20", "21", "22", "23"].map((d) => ({ date: `2026-10-${d}`, events: d === "22"
        ? [{ name: "Žádosti o podporu v nezaměstnanosti (USA, týdně)", time: "14:30", importance: 2 as const, past: false }] : [] })),
      lines: ["Fundament: skóre −7 (medvědí), za týden −2.", "Pátek večer: pozice přes víkend nedrž."],
    },
    season_daily: { gold: { label: "Zlato", next30: { avg: 0.1, win: 40, up: 4, n: 10, by_year: [], from: "", to: "", from_text: "", to_text: "", days: 30 },
      lean: 0, best_up: null, best_down: null, texts: [], path: { offsets: [], dates: [], lines: {}, years_used: {} }, years_from: 2013, source: "", note: "" } },
  } as unknown as Analysis;
}

function mock() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input).split("?")[0];
    if (path === "/api/instruments/XAUUSD/analysis") return Response.json(analysis());
    if (path === "/api/status") return Response.json({ refresh_interval_minutes: 30, cycle_running: false });
    if (path === "/api/tickers") return Response.json({ live: [], daily: [], error: null, fetched_at: "", market: { open: true } });
    if (path === "/api/instruments/XAUUSD/candles") {
      const rows = Array.from({ length: 60 }, (_, i) => [1760000000 + i * 86400, 4100 + i, 4120 + i, 4090 + i, 4110 + i, 4100, 4090]);
      return Response.json({ tf: "D1", source: "Kraken PAXG/USD", candles: rows, trend: {}, fetched_at: "2026-10-17T10:04:00+00:00" });
    }
    return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
  });
}

describe("Pomocník (gold plan)", () => {
  it("answers first: what to do, the checklist and the plan", async () => {
    mock();
    window.location.hash = "#/pomocnik";
    render(<App />);
    expect(await screen.findByRole("heading", { name: /Čekej na SHORT u supply zóny/ })).toBeInTheDocument();
    expect(screen.getByText("ČEKAT")).toBeInTheDocument();
    const check = screen.getByRole("heading", { name: "Checklist setupu" }).closest("div.as-card") as HTMLElement;
    expect(within(check).getByRole("img", { name: /Potvrzení 4 z 6, setup B/ })).toBeInTheDocument();
    expect(within(check).getByText("Týdenní zóna")).toBeInTheDocument();
    fireEvent.click(within(check).getByRole("button", { name: /LONG/ }));
    expect(within(check).getByText(/fundament jde proti/)).toBeInTheDocument();
    expect(screen.getByText("Stop-loss (za zónou)")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Plán na příští týden" })).toBeInTheDocument();
    expect(screen.getByText(/Žádosti o podporu/)).toBeInTheDocument();
    const tiles = screen.getByRole("region", { name: "Rychlý přehled" });
    expect(within(tiles).getByText("−7")).toBeInTheDocument();
  });

  it("keeps the overview of all markets one click away", async () => {
    mock();
    window.location.hash = "#/pomocnik";
    render(<App />);
    await screen.findByRole("heading", { name: /Čekej na SHORT/ });
    expect(screen.getByRole("link", { name: /Přehled všech trhů/ })).toHaveAttribute("href", "#/");
    expect(screen.getAllByRole("link", { name: /Zlato/ })[0]).toHaveClass("is-active");
  });
});
