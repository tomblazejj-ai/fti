import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { staticPath } from "./lib/api";
import { countdown, pct, price, relativeTime, shortDate } from "./lib/format";
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
  ],
};

function mock() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input).split("?")[0];
    if (path === "/api/markets") return Response.json(MARKETS);
    if (path === "/api/calendar") return Response.json(CAL);
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

  it("has a short menu with the data page", async () => {
    mock();
    render(<App />);
    await screen.findByRole("heading", { name: "Kam míří trhy" });
    const menu = screen.getByRole("navigation", { name: "Hlavní menu" });
    expect(within(menu).getAllByRole("link").map((a) => a.textContent?.trim())).toEqual(["Přehled", "Kalendář", "Zprávy", "Data"]);
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

    const tech = screen.getByRole("region", { name: "Technický výhled z veřejných zdrojů" });
    const link = within(tech).getByRole("link", { name: /býci míří na 1,1200/ });
    expect(link).toHaveAttribute("href", "https://x/t1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(within(tech).getByText(/FXEmpire prognózy/)).toBeInTheDocument();

    expect(screen.getByRole("region", { name: "Drobní obchodníci" })).toHaveTextContent("80 % short");
    fireEvent.click(screen.getByText("Rozpis skóre"));
    expect(screen.getByText("Rozdíl sazeb EUR–USD se zužuje.")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(STRATEGY);
  });

  it("says so when public portals have no new technical outlook", async () => {
    mock();
    window.location.hash = "#/trh/USDJPY";
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
    window.location.hash = "#/trh/EURUSD";
    render(<App />);
    const ai = await screen.findByRole("region", { name: "Výklad AI" });
    expect(await within(ai).findByText("ověřeno proti datům FTI")).toBeInTheDocument();
    expect(within(ai).getByText("Skóre +6 a BIAS LONG táhnou sazby.")).toBeInTheDocument();
    expect(within(ai).getByText(/Fakta z FTI, ze kterých AI vycházela \(2\)/)).toBeInTheDocument();
    expect(within(ai).getByRole("button", { name: "Aktualizovat výklad" })).toBeEnabled();
  });

  it("never presents an answer with invented numbers as verified", async () => {
    mockAi(groq(), [analysis(false)]);
    window.location.hash = "#/trh/EURUSD";
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
    const ai = await screen.findByRole("region", { name: "AI — Groq (zdarma)" });
    expect(await within(ai).findByText("Klíč zatím není uložený.")).toBeInTheDocument();
    expect(within(ai).getByRole("button", { name: "Zapnout AI" })).toBeDisabled();
    expect(within(ai).getByText(/nepřipraveno: Engine FTI zatím zóny nepočítá/)).toBeInTheDocument();
    expect(within(ai).getByText(/0 Kč/)).toBeInTheDocument();
    expect(ai.textContent).not.toMatch(/gsk_[A-Za-z0-9]{8,}/);
  });
});
