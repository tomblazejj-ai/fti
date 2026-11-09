import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { mergeBars } from "./lib/chartFeed";
import { ftiDecision } from "./lib/decision";
import type { GoldVerdict, LiveQuote, MarketsResponse } from "./lib/types";
import { calls } from "./test/lwcMock";
import { initTheme } from "./theme";

const MARKETS: MarketsResponse = {
  computed_at: "2026-11-09T10:00:00+00:00", method: "Pevná pravidla.", errors: [], markets: [], highlights: [],
  next_events: [{ datetime: "2026-11-10T13:30:00+00:00", when: "út 10. 11. 14:30", currency: "USD", title: "Inflace CPI", forecast: null, previous: null }],
};

const VERDICT = (action: GoldVerdict["action"]): GoldVerdict => ({
  action, direction_text: "ZLATO", action_text: action === "wait" ? "Vyčkat — žádná strana nemá výhodu." : "Swing: hledat nákup (long).",
  headline: "", summary: "2 z 4 faktorů ukazuje dolů.", confidence: "nízká", combined: 0, factors: [],
});

const quote = (o: Partial<LiveQuote>): LiveQuote => ({
  code: "XAUUSD", label: "XAUUSD", name: "Zlato", kind: "spot_metal", digits: 2, status: "LIVE", status_cs: "živě",
  failover: false, notes: [], providers: [], provider: "deriv", product: "Deriv Gold/USD", price_type: "bid",
  bid: 4096, ask: 4096.5, spread: 0.5, mid: 4096.25, market_status: "OPEN", market_status_cs: "trh otevřen", ...o,
});

function bars(n: number, last = 100) {
  return Array.from({ length: n }, (_, i) => [1794200000 + i * 60, 100, 101, 99, i === n - 1 ? last : 100]);
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-09T10:05:00Z"));
  calls.reset();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function mockFetch(extra: (path: string, url: string) => Response | null = () => null) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const path = url.split("?")[0];
    const r = extra(path, url);
    if (r) return r;
    if (path === "/api/markets") return Response.json(MARKETS);
    if (path === "/api/tickers") return Response.json({ live: [], daily: [], error: null, fetched_at: "", market: { open: true } });
    if (path.endsWith("/candles")) return Response.json({ tf: "D1", source: "Dukascopy Bank", candles: [], fetched_at: "" });
    return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
  });
}

describe("theme", () => {
  it("is dark by default, switches to light and back, remembers it and recolours the chart without reload", async () => {
    mockFetch();
    window.location.hash = "#/grafy";
    initTheme(); // what main.tsx does before the first render
    render(<App />);
    expect(document.documentElement.dataset.theme).toBe("dark");
    await screen.findAllByRole("img", { name: /Graf XAUUSD/ });
    const before = calls.chartOptions.length;
    fireEvent.click(screen.getByRole("button", { name: "Přepnout na světlý režim" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("fti-theme")).toBe("light");
    expect(calls.chartOptions.length).toBeGreaterThan(before); // chart.applyOptions with the new colours
    expect(calls.chartOptions.at(-1)).toHaveProperty("layout");
    fireEvent.click(screen.getByRole("button", { name: "Přepnout na tmavý režim" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});

describe("charts", () => {
  it("has every timeframe M1–MN1 for gold and says which source the candles are from", async () => {
    mockFetch((path) =>
      path === "/api/instruments/XAUUSD/candles"
        ? Response.json({ tf: "MN1", source: "Dukascopy Bank (zpožděné kotace) · XAUUSD", candles: bars(12), days: null, fetched_at: "2026-11-09T10:00:00Z",
                          quality: { status: "DELAYED", freshness: "DELAYED", label: "se zpožděním", as_of: null, text: "" } })
        : null);
    window.location.hash = "#/grafy";
    render(<App />);
    const panel = (await screen.findAllByRole("region", { name: /Graf 1/ }))[0];
    const chips = within(within(panel).getByRole("group", { name: "Časový rámec" })).getAllByRole("button").map((b) => b.textContent);
    expect(chips).toEqual(["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]);
    fireEvent.click(within(panel).getByRole("button", { name: "MN1" }));
    expect(await within(panel).findByText(/Zdroj: Dukascopy Bank/)).toBeInTheDocument();
    expect(within(panel).getByText("DELAYED")).toBeInTheDocument();
  });

  it("shows two or four charts side by side", async () => {
    mockFetch();
    window.location.hash = "#/grafy";
    render(<App />);
    expect(await screen.findAllByRole("region", { name: /^Graf \d$/ })).toHaveLength(2);
    fireEvent.click(within(screen.getByRole("group", { name: "Počet grafů" })).getByText("4"));
    expect(screen.getAllByRole("region", { name: /^Graf \d$/ })).toHaveLength(4);
    expect(JSON.parse(localStorage.getItem("fti-charts") ?? "{}").n).toBe(4);
  });

  it("draws a live candle through series.update(), never by redrawing the whole chart", async () => {
    let last = 100;
    mockFetch((path, url) => {
      if (path === "/api/live/candles") {
        const limit = Number(new URLSearchParams(url.split("?")[1]).get("limit"));
        const all = bars(80, last);
        return Response.json({ code: "XAUUSD", tf: "M1", provider: "deriv", product: "Deriv Gold/USD", price_type: "bid",
                               candles: all.slice(-limit), quote: quote({}) });
      }
      return null;
    });
    let es: { onopen: (() => void) | null; onmessage: ((e: { data: string }) => void) | null } | null = null;
    class FakeES {
      onopen: (() => void) | null = null;
      onmessage: ((e: { data: string }) => void) | null = null;
      onerror: (() => void) | null = null;
      constructor() {
        es = this;
        setTimeout(() => {
          this.onopen?.();
          this.onmessage?.({ data: JSON.stringify({ version: 1, at: "", running: true, instruments: [quote({})] }) });
        }, 0);
      }
      close() {}
    }
    vi.stubGlobal("EventSource", FakeES);
    window.location.hash = "#/zive";
    render(<App />);
    const main = await screen.findByRole("main");
    expect(await within(main).findByText(/Zdroj: Deriv Gold\/USD/)).toBeInTheDocument();
    expect(calls.setData).toBeGreaterThan(0);
    const setDataBefore = calls.setData;
    last = 101.5; // the forming candle moved
    vi.setSystemTime(new Date("2026-11-09T10:05:05Z"));
    await act(async () => {
      es!.onmessage!({ data: JSON.stringify({ version: 2, at: "", running: true, instruments: [quote({ bid: 4097 })] }) });
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(calls.update).toBeGreaterThan(0);
    expect(calls.setData).toBe(setDataBefore);
    // bid / ask of the same source as the candles: two price lines, and the spread below the chart
    expect(calls.priceLines.map((p) => p.title)).toEqual(expect.arrayContaining(["Bid", "Ask"]));
    expect(within(main).getByTitle(/^Živá kotace/)).toHaveTextContent("Spread 0,50");
  });

  it("merges newer bars so only the tail changes", () => {
    const a = [{ t: 1, o: 1, h: 1, l: 1, c: 1 }, { t: 2, o: 1, h: 2, l: 1, c: 2 }];
    const same = mergeBars(a, [{ t: 2, o: 1, h: 2, l: 1, c: 2 }]);
    expect(same).toBe(a); // nothing new → nothing redrawn
    const next = mergeBars(a, [{ t: 2, o: 1, h: 3, l: 1, c: 3 }, { t: 3, o: 3, h: 3, l: 3, c: 3 }]);
    expect(next.map((b) => b.t)).toEqual([1, 2, 3]);
    expect(next[0]).toBe(a[0]);
  });
});

describe("FTI decision for gold", () => {
  it("is NO TRADE with a reason when the price is not live, NEUTRAL when the engine says wait", () => {
    expect(ftiDecision(VERDICT("long"), quote({ status: "DELAYED", status_cs: "se zpožděním" }), true)).toMatchObject({
      kind: "NO TRADE", engine: "LONG", reason: expect.stringContaining("není živá"),
    });
    expect(ftiDecision(VERDICT("long"), undefined, true).kind).toBe("NO TRADE");
    expect(ftiDecision(VERDICT("long"), quote({}), true).kind).toBe("LONG");
    expect(ftiDecision(VERDICT("wait"), undefined, true)).toMatchObject({ kind: "NEUTRAL", reason: expect.stringContaining("Vyčkat") });
    expect(ftiDecision(VERDICT("short"), quote({}), false)).toMatchObject({ kind: "NO TRADE", reason: expect.stringContaining("zavřený") });
    expect(ftiDecision(null, quote({}), true).kind).toBe("NO TRADE");
  });

  it("the dashboard shows NO TRADE as a full state and never claims the market is open when it does not know", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input).split("?")[0];
      if (path === "/api/markets") return Response.json(MARKETS);
      return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    });
    render(<App />);
    const hero = await screen.findByRole("region", { name: "Rozhodnutí FTI pro zlato" });
    expect(within(hero).getByText("NO TRADE")).toBeInTheDocument();
    expect(hero).toHaveTextContent("Verdikt FTI pro zlato teď není k dispozici");
    expect(screen.queryByText(/TRH OTEVŘEN – DATA NEAKTUÁLNÍ/)).not.toBeInTheDocument();
    expect(screen.getByText(/^Verze/)).toHaveTextContent(/Verze \S+ · build/);
  });
});
