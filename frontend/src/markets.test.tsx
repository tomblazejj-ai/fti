import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { staticPath } from "./lib/api";
import type { CalendarAll, MarketCard, MarketsResponse } from "./lib/types";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-31T10:05:00Z"));
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function card(o: Partial<MarketCard>): MarketCard {
  return {
    code: "EURUSD", name: "EUR/USD", subtitle: "Euro / americký dolar", kind: "fx", digits: 5, score10: 6, word: "Silně pozitivní fundamentální výhled",
    bias: "LONG", raw: 6, possible: 10, missing: [],
    components: [{ key: "rates", label: "Úrokové sazby", score: 2, max: 3, text: "Rozdíl sazeb EUR–USD se zužuje.", details: [] }],
    for: [{ label: "Úrokové sazby", text: "Slabší americká inflace zvyšuje očekávání snížení sazeb Fedu.", score: 2 }],
    against: [{ label: "Ekonomika (HDP)", text: "USA rostou rychleji než eurozóna.", score: -1 }],
    price: { value: 1.11532, change_pct: 0.12, as_of: "2026-10-30T00:00:00+00:00", live: true, source: "Kraken" },
    trend: "Nahoru",
    retail: { long_pct: 20, short_pct: 80, change_4w: -3, as_of: "2026-10-27", head: "Sentiment podporuje LONG bias.",
              text: "Zatímco 80 % malých obchodníků je short, fundamentální skóre ukazuje na růst.", tone: "support", source: "CFTC" },
    watch: [{ when: "čt 5. 11. 13:00", datetime: "2026-11-05T12:00:00+00:00", currency: "USD", title: "Rozhodnutí Fedu o sazbách", impact: 3,
              impact_text: "Vysoký dopad na USD", forecast: null, previous: null }],
    change_text: "Rozhodnutí Fedu o sazbách (čt 5. 11.) — tyhle události mohou výhled pro EUR/USD změnit.",
    news: [{ title: "Euro roste po datech", source: "FXStreet", url: "https://x/1", published_at: "2026-10-31T08:00:00+00:00", translated: true }],
    ...o,
  };
}

const MARKETS: MarketsResponse = {
  computed_at: "2026-10-31T10:00:00+00:00", method: "Pevná pravidla.", errors: [],
  markets: [
    card({}),
    card({ code: "USDJPY", name: "USD/JPY", subtitle: "Americký dolar / japonský jen", score10: -5, bias: "SHORT", word: "Mírně negativní fundamentální výhled",
           for: [{ label: "COT", text: "Fondy kupují jen.", score: -1 }], against: [], retail: null, missing: ["Inflace"] }),
  ],
};

const CAL: CalendarAll = {
  computed_at: "2026-10-31T10:00:00+00:00", timezone: "Europe/Prague", sources: ["ForexFactory"],
  events: [
    { datetime: "2026-11-02T15:00:00+00:00", currency: "USD", title_cs: "ISM PMI průmysl", title_en: "ISM Manufacturing PMI", impact: 3, forecast: "49.8", previous: "49.1", source: "ForexFactory" },
    { datetime: "2026-11-03T09:00:00+00:00", currency: "EUR", title_cs: "Nezaměstnanost", title_en: "Unemployment Rate", impact: 1, forecast: null, previous: "6.6%", source: "ForexFactory" },
  ],
};

function mock() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input).split("?")[0];
    if (path === "/api/markets") return Response.json(MARKETS);
    if (path === "/api/calendar") return Response.json(CAL);
    if (path === "/api/tickers") return Response.json({ live: [], daily: [], error: null, fetched_at: "", market: { open: true } });
    if (path.endsWith("/candles")) return Response.json({ tf: "D1", source: "Kraken", candles: [], trend: {}, fetched_at: "" });
    return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
  });
}

describe("Market overview", () => {
  it("lists every market with its score and explains the selected one", async () => {
    mock();
    window.location.hash = "#/";
    render(<App />);
    expect(await screen.findByRole("heading", { name: /MARKET INTELLIGENCE/ })).toBeInTheDocument();
    const detail = screen.getByRole("complementary", { name: /Detail EUR\/USD/ });
    expect(within(detail).getByText("+6 / 10")).toBeInTheDocument();
    expect(within(detail).getByText("LONG")).toBeInTheDocument();
    expect(within(detail).getByText(/Slabší americká inflace/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /USDJPY/ })[0]);
    expect(screen.getByRole("complementary", { name: /Detail USD\/JPY/ })).toHaveTextContent("−5 / 10");
  });

  it("opens a market: arguments, risks, what to watch and retail sentiment", async () => {
    mock();
    window.location.hash = "#/trh/EURUSD";
    render(<App />);
    expect(await screen.findByRole("heading", { name: "EURUSD" })).toBeInTheDocument();
    expect(screen.getByText("ARGUMENTY PODPORUJÍCÍ RŮST")).toBeInTheDocument();
    expect(screen.getByText("PROTIARGUMENTY A RIZIKA")).toBeInTheDocument();
    expect(screen.getByText("Vysoký dopad na USD")).toBeInTheDocument();
    const retail = screen.getByRole("region", { name: "Retail sentiment" });
    expect(within(retail).getByText("20 % LONG")).toBeInTheDocument();
    expect(within(retail).getByText(/Sentiment podporuje LONG bias/)).toBeInTheDocument();
  });

  it("shows the calendar of all currencies and filters by impact", async () => {
    mock();
    window.location.hash = "#/kalendar";
    render(<App />);
    expect(await screen.findByText("ISM PMI průmysl")).toBeInTheDocument();
    expect(screen.queryByText("Nezaměstnanost")).not.toBeInTheDocument(); // low impact hidden by default
    fireEvent.click(within(screen.getByRole("group", { name: "Dopad" })).getByRole("button", { name: "Vše" }));
    expect(screen.getByText("Nezaměstnanost")).toBeInTheDocument();
    expect(screen.getByText(/prognóza 49.8/)).toBeInTheDocument();
  });
});

describe("phone version (static snapshot)", () => {
  it("maps every API call to a snapshot file", () => {
    expect(staticPath("/api/markets")).toBe("data/markets.json");
    expect(staticPath("/api/instruments/EURUSD/candles?tf=D1")).toBe("data/candles-EURUSD-D1.json");
    expect(staticPath("/api/instruments/XAUUSD/tra-history?days=91")).toBe("data/tra-XAUUSD.json");
    expect(staticPath("/api/instruments/XAUUSD/analysis")).toBe("data/analysis-XAUUSD.json");
    expect(staticPath("/api/instruments/XAUUSD/refresh")).toBeNull();
  });
});
