import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { staticPath } from "./lib/api";
import { countdown, pct, price, relativeTime, shortDate } from "./lib/format";
import type { CalendarAll, IntermarketResult, MarketCard, MarketRegime, MarketsResponse } from "./lib/types";

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
    retail: { long_pct: 20, short_pct: 80, change_4w: -3, as_of: "2026-10-27", head: "Malí obchodníci jsou proti směru skóre.",
              text: "80 % malých obchodníků je short.", tone: "support", source: "CFTC" },
    watch: [{ when: "čt 5. 11. 13:00", datetime: "2026-11-05T12:00:00+00:00", currency: "USD", title: "Rozhodnutí Fedu o sazbách", impact: 3,
              impact_text: "Vysoký dopad na USD", forecast: null, previous: null }],
    change_text: "Rozhodnutí Fedu o sazbách (čt 5. 11.) — tyhle události mohou výhled pro EUR/USD změnit.",
    news: [{ title: "Euro roste po datech", source: "FXStreet", url: "https://x/1", published_at: "2026-10-31T08:00:00+00:00", translated: true }],
    technical: [{ title: "EUR/USD Price Forecast: býci míří na 1,1200", source: "FXEmpire prognózy", url: "https://x/t1",
                  published_at: "2026-10-31T07:00:00+00:00", translated: true }],
    ...o,
  };
}

const MARKETS: MarketsResponse = {
  computed_at: "2026-10-31T10:00:00+00:00", method: "Pevná pravidla.", errors: [],
  markets: [
    card({}),
    card({ code: "USDJPY", name: "USD/JPY", subtitle: "Americký dolar / japonský jen", score10: -5, bias: "SHORT", word: "Mírně negativní fundamentální výhled",
           for: [{ label: "COT", text: "Fondy kupují jen.", score: -1 }], against: [], retail: null, missing: ["Inflace"], technical: [] }),
  ],
  highlights: [
    { title: "Fed nechal sazby beze změny", source: "CNBC", url: "https://x/h1", published_at: "2026-10-31T09:00:00+00:00", translated: true,
      market: "XAUUSD", impact: "bullish" },
    { title: "Jen oslabuje po BoJ", source: "FXStreet", url: "https://x/h2", published_at: "2026-10-31T06:00:00+00:00", translated: false, market: "USDJPY" },
  ],
  next_events: [
    { datetime: "2026-10-31T11:30:00+00:00", when: "dnes 12:30", currency: "USD", title: "Inflace PCE", forecast: "2.8%", previous: "2.9%" },
    { datetime: "2026-11-05T12:00:00+00:00", when: "čt 5. 11. 13:00", currency: "USD", title: "Rozhodnutí Fedu o sazbách", forecast: null, previous: null },
  ],
};

const CAL: CalendarAll = {
  computed_at: "2026-10-31T10:00:00+00:00", timezone: "Europe/Prague", sources: ["ForexFactory"],
  events: [
    { datetime: "2026-11-02T15:00:00+00:00", currency: "USD", title_cs: "ISM PMI průmysl", title_en: "ISM Manufacturing PMI", impact: 3, forecast: "49.8", previous: "49.1", source: "ForexFactory" },
    { datetime: "2026-11-03T09:00:00+00:00", currency: "EUR", title_cs: "Nezaměstnanost", title_en: "Unemployment Rate", impact: 1, forecast: null, previous: "6.6%", source: "ForexFactory" },
    { datetime: "2026-10-30T12:30:00+00:00", currency: "USD", title_cs: "Nová pracovní místa NFP", title_en: "Non-Farm Employment Change", impact: 3,
      forecast: "65K", previous: "29K", source: "ForexFactory", actual: "165K", previous_revised: "60K",
      actual_source: "BLS přes ALFRED/FRED (stav ke dni vydání 2026-10-30, řada PAYEMS) — ověřeno u vydavatele", actual_status: "ověřeno u vydavatele" },
    { datetime: "2026-10-30T12:30:00+00:00", currency: "USD", title_cs: "Žádosti o podporu", title_en: "Unemployment Claims", impact: 2,
      forecast: "197K", previous: "194K", source: "ForexFactory", actual: "189K", actual_status: "neověřeno u vydavatele" },
    { datetime: "2026-10-30T14:00:00+00:00", currency: "USD", title_cs: "ISM služby", title_en: "ISM Services PMI", impact: 2,
      forecast: "54.8", previous: "54.9", source: "ForexFactory", actual_note: "Skutečnost: bez volného oficiálního zdroje — ISM (soukromá organizace)." },
  ],
};

const IM: IntermarketResult = {
  tf: "D1", target_label: "Zlato (XAU/USD)", computed_at: "2026-10-31T10:00:00+00:00", main_window: 60, windows: [30, 60, 120, 250],
  causality: "Korelace měří souběh pohybů, ne příčinu.",
  relations: [{
    b: "DXY*@mt5", b_code: "DXY*", label: "Dolarový index DXY*", category: "vypočtený index", tf: "D1", observations_total: 380,
    windows: [{ window: 60, n: 60, n_eff: 55, r: -0.47, p: 0.0002, ci95: [-0.65, -0.23], strength: "střední záporná", sufficiency: "dostatečný" },
              { window: 250, n: 250, n_eff: 240, r: -0.45, p: 0, ci95: null, strength: "střední záporná", sufficiency: "dobrý" }],
    last_common: "2026-10-30T22:00:00+00:00", sources: ["Dukascopy", "výpočet FTI z MT5 + ECB"], proxy: false, related: null,
    stability: { verdict: "stabilní", same_sign_share: 1, mean: -0.5 }, breakdown: { state: "drží" },
    change: { r_now: -0.47, r_prev: -0.56, delta: 0.09, p: 0.54, significant: false },
    move: { bars: 5, gold_pct: 5.03, other: 0.33, other_unit: "%", verdict: "odporuje", text: "", until: "2026-10-30T22:00:00+00:00" },
    quality: { label: "použitelná", issues: ["vypočtený index (vzorec ICE z kurzů), ne oficiální kotace"] },
  }],
};

function mock() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input).split("?")[0];
    if (path === "/api/markets") return Response.json(MARKETS);
    if (path === "/api/calendar") return Response.json(CAL);
    if (path === "/api/intermarket/intel") return Response.json(IM);
    if (path === "/api/tickers") return Response.json({ live: [], daily: [], error: null, fetched_at: "", market: { open: true } });
    if (path.endsWith("/candles")) return Response.json({ tf: "D1", source: "Kraken", candles: [], fetched_at: "" });
    return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
  });
}

// anything that would be the user's own trading strategy must never appear in the app
const STRATEGY = /metodik|obchodní plán|nevstupuj|checklist/i;

describe("Home", () => {
  it("puts the fundament of every market first, then what moves and what can move the markets", async () => {
    mock();
    window.location.hash = "#/trhy";
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Kam míří trhy" })).toBeInTheDocument();
    expect(screen.getAllByText("FTI").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Market Intelligence/i)).not.toBeInTheDocument();

    const eur = screen.getByRole("link", { name: /EUR\/USD: skóre 6/ });
    expect(within(eur).getByRole("img", { name: "Skóre +6 z 10" })).toBeInTheDocument();
    expect(within(eur).getByText("Spíš růst")).toBeInTheDocument();
    expect(within(eur).getByText(/Slabší americká inflace/)).toBeInTheDocument();
    expect(eur).toHaveAttribute("href", "#/trh/EURUSD");
    const jpy = screen.getByRole("link", { name: /USD\/JPY: skóre -5/ });
    expect(within(jpy).getByRole("img", { name: "Skóre −5 z 10" })).toBeInTheDocument();
    expect(within(jpy).getByText("Spíš pokles")).toBeInTheDocument();

    const moves = screen.getByRole("region", { name: "Co hýbe trhy" });
    expect(within(moves).getByText("Fed nechal sazby beze změny")).toBeInTheDocument();
    expect(within(moves).getByText("pro zlato ↑")).toBeInTheDocument();
    expect(within(moves).getByText("Zlato")).toBeInTheDocument();

    const next = screen.getByRole("region", { name: "Co může trh ovlivnit" });
    expect(within(next).getByText("Inflace PCE")).toBeInTheDocument();
    expect(within(next).getByText("za 1 h 25 min")).toBeInTheDocument();
    // the next big release also sits at the top, as a countdown
    expect(screen.getByText("Inflace PCE (USD)")).toBeInTheDocument();

    expect(document.body.textContent).not.toMatch(STRATEGY);
  });

  it("shows an error with retry when the data cannot be read", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Data se nepodařilo načíst");
    expect(screen.getByRole("button", { name: "Zkusit znovu" })).toBeInTheDocument();
  });

  it("has a sidebar menu in groups, the data sources page included", async () => {
    mock();
    render(<App />);
    const menu = screen.getByRole("navigation", { name: "Hlavní menu" });
    expect(within(menu).getAllByRole("heading").map((h) => h.textContent)).toEqual(["Přehled", "Analýza", "Rozhodnutí", "Vyhodnocení", "Systém"]);
    expect(within(menu).getAllByRole("link").map((a) => a.textContent?.trim())).toEqual([
      "Dashboard", "Live Markets", "Trhy", "Grafy", "Zlato", "Technika", "Intermarket", "Makro & COT", "Zprávy", "Kalendář",
      "AI Advisor", "Risk", "Backtest", "Historie signálů", "Deník obchodů", "Zdroje dat", "Nastavení",
    ]);
    expect(within(menu).getByRole("link", { name: "Zdroje dat" })).toHaveAttribute("href", "#/data");
  });
});

describe("Market detail", () => {
  it("explains the score, lists what can move the market and the public technical outlooks", async () => {
    mock();
    window.location.hash = "#/trh/EURUSD";
    render(<App />);
    expect(await screen.findByRole("heading", { name: "EUR/USD", level: 1 })).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: "Skóre +6 z 10" }).length).toBeGreaterThan(0);

    const why = screen.getByRole("region", { name: "Proč" });
    expect(within(why).getByText(/Slabší americká inflace/)).toBeInTheDocument();
    expect(within(why).getByText("Co jde proti")).toBeInTheDocument();
    expect(within(why).getByText(/USA rostou rychleji/)).toBeInTheDocument();

    const influence = screen.getByRole("region", { name: "Co může trh ovlivnit" });
    expect(within(influence).getByText("Rozhodnutí Fedu o sazbách")).toBeInTheDocument();

    expect(screen.getByText("Rozdíl sazeb EUR–USD se zužuje.")).toBeInTheDocument();  // score overview under the chart
    expect(screen.getByRole("navigation", { name: "Části detailu" })).toHaveTextContent(
      "PřehledTechnikaZóny & likviditaIntermarketMakro & COTSezónnostZprávyKalendář");

    window.location.hash = "#/trh/EURUSD/technika";
    const tech = await screen.findByRole("region", { name: "Technický výhled z veřejných zdrojů" });
    const link = within(tech).getByRole("link", { name: /býci míří na 1,1200/ });
    expect(link).toHaveAttribute("href", "https://x/t1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(within(tech).getByText(/FXEmpire prognózy/)).toBeInTheDocument();

    window.location.hash = "#/trh/EURUSD/makro";
    expect(await screen.findByRole("region", { name: "Drobní obchodníci" })).toHaveTextContent("80 % short");
    expect(document.body.textContent).not.toMatch(STRATEGY);
  });

  it("says so when public portals have no new technical outlook", async () => {
    mock();
    window.location.hash = "#/trh/USDJPY/technika";
    render(<App />);
    const tech = await screen.findByRole("region", { name: "Technický výhled z veřejných zdrojů" });
    expect(tech).toHaveTextContent("nový technický rozbor nevydaly");
    expect(screen.getByText(/Bez dat: Inflace/)).toBeInTheDocument();
  });
});

describe("Calendar and news", () => {
  it("shows the calendar of all currencies and filters by impact", async () => {
    mock();
    window.location.hash = "#/kalendar";
    render(<App />);
    expect(await screen.findByText("ISM PMI průmysl")).toBeInTheDocument();
    expect(screen.queryByText("Nezaměstnanost")).not.toBeInTheDocument(); // low impact hidden by default
    fireEvent.click(within(screen.getByRole("group", { name: "Dopad" })).getByText("Vše"));
    expect(screen.getByText("Nezaměstnanost")).toBeInTheDocument();
    expect(screen.getByText("Další zpráva s vysokým dopadem")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(STRATEGY);
  });

  it("shows gold's intermarket relationships with n, stability, the latest move and data quality", async () => {
    const gold = card({ code: "XAUUSD", name: "Zlato", subtitle: "Zlato / americký dolar" });
    const base = mock();
    base.mockImplementation(async (input) => {
      const path = String(input).split("?")[0];
      if (path === "/api/markets") return Response.json({ ...MARKETS, markets: [...MARKETS.markets, gold] });
      if (path === "/api/intermarket/intel") return Response.json(IM);
      if (path === "/api/tickers") return Response.json({ live: [], daily: [], error: null, fetched_at: "", market: { open: true } });
      if (path.endsWith("/candles")) return Response.json({ tf: "D1", source: "Dukascopy", candles: [], fetched_at: "" });
      return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    });
    window.location.hash = "#/trh/XAUUSD/intermarket";
    render(<App />);
    expect(await screen.findByText("Mezitrh – vztahy se zlatem")).toBeInTheDocument();
    const row = (await screen.findAllByText("Dolarový index DXY*")).map((e) => e.closest("tr")).find(Boolean)!;
    expect(row).toHaveTextContent("−0,47");
    expect(row).toHaveTextContent("n 60, efektivně 55");
    expect(row).toHaveTextContent("odporuje");
    expect(row).toHaveTextContent("vypočtený index");
    expect(screen.getByText(/Odporují:/).closest("p")).toHaveTextContent("Odporují: Dolarový index DXY*");
    expect(document.body.textContent).toContain("ne příčinu");
  });

  it("shows gold's market regime with each dimension, its data and what it means — or says it is not computed yet", async () => {
    const gold = card({ code: "XAUUSD", name: "Zlato", subtitle: "Zlato / americký dolar" });
    const regime: MarketRegime = {
      as_of: "2026-11-09T08:28:00+00:00", computed_at: "2026-11-09T08:28:00+00:00",
      label: "Klesající trend · volatilita běžná · riziková averze", summary: "Trend: klesající trend.", missing: [],
      method: "Deterministicky.", note: "Režim trhu je kontext, ne hlas ve verdiktu.",
      atr: { d1: 79.9, pct_of_price: 1.97, percentile: 71, window: 250, as_of: "2026-11-06" },
      dimensions: [
        { key: "trend", label: "Trend", state: "trend_down", word: "Klesající trend", available: true,
          detail: "D1: dolů, ADX 26,3 (trend od 25, slabý od 20).", implication: "Obchody ve směru trendu.",
          inputs: [{ name: "ADX D1", value: 26.3, source: "Dukascopy", as_of: "2026-11-08T22:00:00+00:00" }] },
        { key: "korelace", label: "Vztahy se zlatem", state: "unknown", word: "nelze určit", available: false,
          detail: "Výsledek Intermarket Intelligence D1 FTI teď nemá.", implication: null, inputs: [] },
      ],
    };
    let ready = false;
    const base = mock();
    base.mockImplementation(async (input) => {
      const path = String(input).split("?")[0];
      if (path === "/api/markets") return Response.json({ ...MARKETS, markets: [...MARKETS.markets, gold] });
      if (path === "/api/regime") return ready ? Response.json(regime)
        : new Response(JSON.stringify({ detail: "Režim trhu se ještě počítá — přijde s nejbližším výpočtem FTI." }), { status: 404 });
      if (path === "/api/tickers") return Response.json({ live: [], daily: [], error: null, fetched_at: "", market: { open: true } });
      if (path.endsWith("/candles")) return Response.json({ tf: "D1", source: "Dukascopy", candles: [], fetched_at: "" });
      return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    });
    window.location.hash = "#/trh/XAUUSD/technika";
    const first = render(<App />);
    expect(await screen.findByText(/Režim trhu se ještě počítá/)).toBeInTheDocument();  // said, never invented
    first.unmount();
    ready = true;
    render(<App />);
    expect(await screen.findByText("Klesající trend · volatilita běžná · riziková averze")).toBeInTheDocument();
    const trend = screen.getByText("Klesající trend").closest("tr")!;
    expect(trend).toHaveTextContent("ADX 26,3");
    expect(trend).toHaveTextContent("Dukascopy");
    expect(trend).toHaveTextContent("Obchody ve směru trendu.");
    expect(screen.getByText("nelze určit").closest("tr")).toHaveTextContent("Intermarket Intelligence D1 FTI teď nemá");
    expect(document.body.textContent).toContain("kontext, ne hlas ve verdiktu");
  });

  it("live terminal: says it is off, never invents a price", async () => {
    const base = mock();
    base.mockImplementation(async (input) => {
      const path = String(input).split("?")[0];
      if (path === "/api/live/snapshot")
        return new Response(JSON.stringify({ detail: "Živá data jsou vypnutá (Nastavení → LIVE)." }), { status: 503 });
      if (path === "/api/tickers") return Response.json({ live: [], daily: [], error: null, fetched_at: "", market: { open: true } });
      return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    });
    class FakeES {
      onopen: (() => void) | null = null;
      onmessage: ((e: { data: string }) => void) | null = null;
      onerror: (() => void) | null = null;
      constructor() {
        setTimeout(() => this.onerror?.(), 0);
      }
      close() {}
    }
    vi.stubGlobal("EventSource", FakeES);
    window.location.hash = "#/zive";
    render(<App />);
    expect(await screen.findByText(/Živá data jsou vypnutá/)).toBeInTheDocument();
    expect(document.body.textContent).toContain("stream nepřipojen");
    vi.unstubAllGlobals();
  });

  it("live terminal: streamed prices with state, bid/ask, change and source", async () => {
    mock();
    const snap = {
      version: 3, at: "2026-11-09T09:20:00+00:00", running: true,
      instruments: [
        { code: "XAUUSD", label: "XAUUSD", name: "Zlato", kind: "spot_metal", digits: 2, status: "LIVE", status_cs: "živě",
          failover: false, notes: [], provider: "deriv", product: "Deriv Gold/USD — kotace brokera Deriv", price_type: "mid",
          bid: 4096.0, ask: 4096.58, spread: 0.58, mid: 4096.29, time_basis: "quote", quote_time: "2026-11-09T09:19:59+00:00",
          age_s: 0.3, prev_close: 4055.42, prev_close_day: "2026-11-06", change: 40.87, change_pct: 1.008,
          providers: [{ provider: "deriv", symbol: "frxXAUUSD", role: "primary", product: "Deriv Gold/USD", age_s: 0.3, fresh: true,
                        in_session: true, compat: null }] },
        { code: "US500.CFD", label: "US500", name: "S&P 500 — CFD", kind: "cfd_index", digits: 1, status: "HISTORICAL",
          status_cs: "historická cena", failover: false, market_status: "OPEN", market_status_cs: "trh otevřen",
          banner: "TRH OTEVŘEN – DATA NEAKTUÁLNÍ", notes: ["Deriv kotuje US500 jen 6–21 h UTC."], provider: "deriv",
          product: "Deriv US 500 — OTC index (CFD, ne index sám)", bid: 7409.6, ask: 7410, spread: 0.4, mid: 7409.8,
          quote_time: "2026-11-08T20:59:59+00:00", age_s: 44400, change: null, change_pct: null, providers: [] },
      ],
    };
    class FakeES {
      onopen: (() => void) | null = null;
      onmessage: ((e: { data: string }) => void) | null = null;
      onerror: (() => void) | null = null;
      constructor() {
        setTimeout(() => {
          this.onopen?.();
          this.onmessage?.({ data: JSON.stringify(snap) });
        }, 0);
      }
      close() {}
    }
    vi.stubGlobal("EventSource", FakeES);
    window.location.hash = "#/zive";
    render(<App />);
    const main = await screen.findByRole("main");
    const gold = (await within(main).findByText("4 096,29")).closest("button")!;
    expect(gold).toHaveTextContent("LIVE");
    expect(gold).toHaveTextContent("Bid 4 096,00");
    expect(gold).toHaveTextContent("Ask 4 096,58");
    expect(gold).toHaveTextContent("+40,87 (+1,01 %)");
    expect(gold).toHaveTextContent("proti závěru 2026-11-06");
    expect(gold).toHaveTextContent("Deriv Gold/USD");
    const spx = within(main).getByText("US500").closest("button")!;
    expect(spx).toHaveTextContent("HISTORICAL");
    expect(spx).toHaveTextContent("ne index sám");
    expect(spx).toHaveTextContent("jen 6–21 h UTC");
    expect(spx).toHaveTextContent("TRH OTEVŘEN – DATA NEAKTUÁLNÍ");  // market open, data not live: said loudly
    expect(screen.getByRole("alert")).toHaveTextContent("US500: TRH OTEVŘEN – DATA NEAKTUÁLNÍ");
    expect(document.body.textContent).toContain("stream připojen");
    vi.unstubAllGlobals();
  });

  it("shows the official actual of a released event next to forecast and previous", async () => {
    mock();
    window.location.hash = "#/kalendar";
    render(<App />);
    const actual = await screen.findByText("skutečnost 165K");
    expect(actual.closest("small")).toHaveTextContent("skutečnost 165K · prognóza 65K · minule 29K (revize 60K)");
    expect(actual.closest("small")).toHaveAttribute("title", expect.stringContaining("PAYEMS"));
    expect(screen.getByText(/bez volného oficiálního zdroje — ISM/)).toBeInTheDocument();
    expect(screen.getByText("skutečnost 189K").closest("small")).toHaveTextContent("skutečnost 189K (neověřeno u vydavatele)");
  });

  it("switches between news and technical outlooks", async () => {
    mock();
    window.location.hash = "#/zpravy";
    render(<App />);
    expect((await screen.findAllByText("Euro roste po datech")).length).toBe(2);
    fireEvent.click(screen.getByRole("button", { name: "Technický výhled" }));
    expect(screen.getByText(/býci míří na 1,1200/)).toBeInTheDocument();
    expect(screen.queryByText("Euro roste po datech")).not.toBeInTheDocument();
    expect(screen.getByText("Teď žádný nový technický rozbor z veřejných webů.")).toBeInTheDocument();
  });
});

describe("helpers", () => {
  it("maps the phone version's requests to the snapshot files", () => {
    expect(staticPath("/api/markets")).toBe("data/markets.json");
    expect(staticPath("/api/instruments/XAUUSD/candles?tf=D1")).toBe("data/candles-XAUUSD-D1.json");
    expect(staticPath("/api/metodika")).toBeNull();
  });

  it("formats Czech numbers, dates and countdowns", () => {
    expect(price(4012.345, 2)).toBe("4 012,35".replace(" ", " "));
    expect(price(1.115321, 5)).toBe("1,1153");
    expect(pct(-1.1)).toBe("−1,10 %");
    expect(pct(0.42)).toBe("+0,42 %");
    expect(shortDate("2026-09-25")).toBe("25. 9. 2026");
    expect(countdown(85)).toBe("1 h 25 min");
    expect(countdown(3 * 1440)).toBe("3 dny");
    expect(countdown(6 * 1440)).toBe("6 dní");
    const now = new Date("2026-10-31T10:00:00Z");
    expect(relativeTime("2026-10-31T09:30:00Z", now)).toBe("před 30 min");
    expect(relativeTime("2026-10-28T10:00:00Z", now)).toBe("před 3 dny");
  });
});

describe("AI (Groq Free)", () => {
  const groq = (o: Record<string, unknown> = {}) => ({
    provider: "groq", key_set: true, state: "ready", text: "AI je připravená (Groq Free).", until: null, auto_analyses: false,
    usage: { requests: 3, tokens: 4200, failed: 0, cap: 80, token_cap: 100000, per_minute_cap: 6, reserve_from: 64 },
    models: { "openai/gpt-oss-120b": { paused_until: null, reason: null, limits: { requests_per_day: 1000, tokens_per_minute: 8000 } } },
    limits_changed: null, terms_checked: "2026-11-01", cost: "0 Kč — jen bezplatný tarif Groq Free, bez platební metody", ...o,
  });
  const tasks = [
    { id: "market", name: "Tržní podmínky, BIAS, fundamentální skóre a konfluence", ready: true, why_not: null, cooldown_min: 60 },
    { id: "zones", name: "Supply/demand zóny, order blocks a FVG", ready: false, why_not: "Engine FTI zatím zóny nepočítá.", cooldown_min: 0 },
  ];
  const analysis = (ok: boolean) => ({
    id: 1, task: "market", code: "EURUSD", created_at: "2026-10-31T09:50:00+00:00", model: "openai/gpt-oss-120b",
    reason: "na požádání", engine_computed_at: "2026-10-31T09:30:00+00:00", confidence: "střední", tokens: { in: 900, out: 300 },
    output: { shrnuti: ok ? "Skóre +6 a BIAS LONG táhnou sazby." : "Cíl je 1,1500.", bias: "LONG vychází ze sazeb.",
              pro: [{ text: "Sazby +2.", fakta: ["F2"] }], proti: [], sledovat: [], chybi: [], jistota: "střední" },
    facts: [{ id: "F1", co: "Fundamentální skóre", hodnota: 6, zdroj: "výpočet FTI" },
            { id: "F2", co: "Složka skóre: Úrokové sazby", hodnota: 2, zdroj: "výpočet FTI" }],
    validation: { ok, schema: [], unknown_facts: [], unknown_numbers: ok ? [] : ["1,1500"] },
  });

  function mockAi(status: object, analyses: object[]) {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input).split("?")[0];
      if (path === "/api/markets") return Response.json(MARKETS);
      if (path === "/api/tickers") return Response.json({ live: [], daily: [], error: null, fetched_at: "", market: { open: true } });
      if (path.endsWith("/candles")) return Response.json({ tf: "D1", source: "Kraken", candles: [], fetched_at: "" });
      if (path === "/api/ai/status") return Response.json({ provider: "groq", groq: status, tasks });
      if (path === "/api/ai/analyses") return Response.json({ analyses });
      return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    });
  }

  it("shows a verified AI interpretation with the facts it used", async () => {
    mockAi(groq(), [analysis(true)]);
    window.location.hash = "#/ai/EURUSD";
    render(<App />);
    const ai = await screen.findByRole("region", { name: "Výklad AI" });
    expect(await within(ai).findByText("ověřeno proti datům FTI")).toBeInTheDocument();
    expect(within(ai).getByText("Skóre +6 a BIAS LONG táhnou sazby.")).toBeInTheDocument();
    expect(within(ai).getByText(/Fakta z FTI, ze kterých AI vycházela \(2\)/)).toBeInTheDocument();
    expect(within(ai).getByRole("button", { name: "Aktualizovat výklad" })).toBeEnabled();
  });

  it("never presents an answer with invented numbers as verified", async () => {
    mockAi(groq(), [analysis(false)]);
    window.location.hash = "#/ai/EURUSD";
    render(<App />);
    const ai = await screen.findByRole("region", { name: "Výklad AI" });
    expect(await within(ai).findByText("neověřeno")).toBeInTheDocument();
    expect(within(ai).getByText(/čísla, která ve výpočtech FTI nejsou: 1,1500/)).toBeInTheDocument();
    expect(within(ai).getByText("Cíl je 1,1500.")).not.toBeVisible();
  });

  it("without a key AI cannot be switched on and the key is never shown", async () => {
    mockAi(groq({ provider: "none", key_set: false, state: "off", text: "AI je vypnutá v nastavení — FTI ukazuje rozbor z pravidel." }), []);
    window.location.hash = "#/data";
    render(<App />);
    const ai = await screen.findByRole("region", { name: "AI — Gemini Free, záloha Groq Free (zdarma)" });
    expect(await within(ai).findByText("Klíč zatím není uložený.")).toBeInTheDocument();
    expect(within(ai).getByText(/NO TRADE „AI nedostupná“/)).toBeInTheDocument();  // limits gone: never a paid provider
    expect(within(ai).getByText(/nezapínej billing/)).toBeInTheDocument();
    expect(within(ai).getByRole("button", { name: "Zapnout AI" })).toBeDisabled();
    expect(within(ai).getByText(/nepřipraveno: Engine FTI zatím zóny nepočítá/)).toBeInTheDocument();
    expect(within(ai).getByText(/0 Kč/)).toBeInTheDocument();
    expect(ai.textContent).not.toMatch(/gsk_[A-Za-z0-9]{8,}/);
    expect(ai.textContent).not.toMatch(/AIza[A-Za-z0-9_-]{8,}/);
  });

  it("shows today's AI calls against the daily cap, Gemini first", async () => {
    mockAi(groq({ provider: "gemini", keys: { gemini: true, groq: true }, order: ["gemini", "groq"], calls_today: 12, calls_cap: 80,
                  text: "AI je připravená (Gemini Free → Groq Free)." }), []);
    window.location.hash = "#/data";
    render(<App />);
    const ai = await screen.findByRole("region", { name: "AI — Gemini Free, záloha Groq Free (zdarma)" });
    expect(await within(ai).findByText("12 / 80")).toBeInTheDocument();
    expect(within(ai).getByText("AI je připravená (Gemini Free → Groq Free).")).toBeInTheDocument();
    expect(within(ai).getByRole("button", { name: "Otestovat Gemini" })).toBeEnabled();
  });
});
