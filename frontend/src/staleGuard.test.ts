import { describe, expect, it } from "vitest";
import { guardStale } from "./lib/staleGuard";

const NOW = new Date("2026-11-02T12:00:00Z");
const quote = (time: string, status = "LIVE") => ({
  symbol: "BTCUSD", price: 78000, live: true, as_of: time,
  quality: { status, label: "živě", as_of: time, text: "Poslední obchod." },
  last_quote: { price: 78000, time, time_cs: "po 2. 11. 2026 12:00 SEČ", tradable_now: true },
});

describe("phone snapshot from the PC", () => {
  it("keeps a fresh live price as it is", () => {
    const t = guardStale({ live: [quote("2026-11-02T11:55:00Z")] }, NOW);
    expect(t.live[0].quality.status).toBe("LIVE");
    expect(t.live[0].last_quote.tradable_now).toBe(true);
  });

  it("never shows a price from hours ago as live when the PC is off", () => {
    const t = guardStale({ live: [quote("2026-11-02T08:00:00Z")] }, NOW);
    const q = t.live[0];
    expect(q.quality.status).toBe("STALE");
    expect(q.quality.text).toMatch(/novější data z FTI na PC zatím nepřišla/);
    expect(q.last_quote.tradable_now).toBe(false);
    expect(q.live).toBe(false);
  });

  it("leaves daily, reference and proxy values alone and treats an unknown time as old", () => {
    const daily = { quality: { status: "DELAYED", as_of: "2026-10-30" } };
    const noTime = { quality: { status: "LIVE" } };
    const t = guardStale({ a: daily, b: noTime }, NOW);
    expect(t.a.quality.status).toBe("DELAYED");
    expect(t.b.quality.status).toBe("STALE");
  });
});
