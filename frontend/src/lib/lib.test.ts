import { describe, expect, it } from "vitest";
import { snapshot, pillar } from "../test/fixtures";
import { summarizeChange } from "./changes";
import { buildWhy, horizonHeadline } from "./explain";
import { daysUntil, inDays, isStale, netFromScore, num, relativeTime, scoreText, signed, sourceLabel } from "./format";

describe("buildWhy", () => {
  it("never lists a pillar without usable data as a reason", () => {
    const s = snapshot({ score: 49, direction: "NEUTRAL" }, {
      positioning: pillar({ weight: 7, points: -1.0, raw_signal: -0.14, impact: "bearish", reasons: ["CFTC kleslo"] }),
    });
    const why = buildWhy(s);
    expect(why.supporting).toEqual([]);
    expect(why.opposing.map((o) => o.pillar)).toEqual(["positioning"]);
    expect(why.notAssessed.map((n) => n.pillar)).toEqual(
      expect.arrayContaining(["fed", "real_yields", "inflation", "usd", "economy", "central_banks", "geopolitics"]),
    );
    expect(why.summary).toContain("Daty je podloženo 1 z 8 pilířů");
    expect(why.evidenceIsLimited).toBe(true);
  });

  it("builds the question from the backend's direction and orders reasons by size", () => {
    const s = snapshot({ score: 74, bias: "LONG", direction: "BULLISH" }, {
      fed: pillar({ weight: 20, points: 8, impact: "bullish", reasons: ["Fed holubičí"] }),
      real_yields: pillar({ weight: 20, points: 14, impact: "bullish", reasons: ["výnosy klesají"] }),
      usd: pillar({ weight: 15, points: -3, impact: "bearish", reasons: ["USD roste"] }),
      inflation: pillar({ weight: 15, points: 2, impact: "bullish" }),
      economy: pillar({ weight: 10, points: 0.3, impact: "neutral" }),
    });
    const why = buildWhy(s);
    expect(why.question).toBe("Proč je výhled pro zlato býčí?");
    expect(why.supporting.map((i) => i.pillar)).toEqual(["real_yields", "fed", "inflation"]);
    expect(why.summary).toContain("Pro růst mluví: Reálné výnosy, Fed a Inflace (celkem +24,0 b.)");
    expect(why.summary).toContain("Proti mluví: USD");
    expect(why.flat.map((i) => i.pillar)).toEqual(["economy"]); // small move, labelled neutral by the backend
    expect(why.evidenceIsLimited).toBe(false);
  });

  it("cites a partial pillar whose available data moved the score, and says it is partial", () => {
    const s = snapshot({ score: 32, bias: "SHORT", direction: "BEARISH" }, {
      fed: pillar({ weight: 20, points: -6, impact: "bearish", data_quality: "partial",
        reasons: ["Sazba Fedu 3,75 → 4,00", "Fed tón: žádná zpráva"], gaps: ["Fed tón: žádná zpráva"] }),
    });
    const why = buildWhy(s);
    expect(why.question).toBe("Proč je výhled pro zlato medvědí?");
    expect(why.opposing.map((o) => o.pillar)).toEqual(["fed"]);
    expect(why.opposing[0].quality).toBe("partial");
    expect(why.opposing[0].reason).toBe("Sazba Fedu 3,75 → 4,00");
    expect(why.notAssessed.map((n) => n.pillar)).not.toContain("fed");
    expect(why.summary).toContain("(1 jen částečně)");
  });

  it("explains a not-assessed pillar by what is missing", () => {
    const why = buildWhy(snapshot({}, {
      geopolitics: pillar({ weight: 5, data_quality: "partial", reasons: ["žádné zprávy"], gaps: ["žádné geopolitické zprávy v okně"] }),
    }));
    expect(why.notAssessed.find((n) => n.pillar === "geopolitics")?.reason).toBe("žádné geopolitické zprávy v okně");
  });

  it("says plainly when nothing moves the score", () => {
    const why = buildWhy(snapshot());
    expect(why.summary).toContain("Žádný pilíř s použitelnými daty teď skóre neposouvá");
  });
});

describe("horizonHeadline", () => {
  it("names the biggest mover or admits there is none", () => {
    expect(horizonHeadline(snapshot())).toBe("Skóre neposouvá žádný pilíř s daty.");
    const s = snapshot({}, { positioning: pillar({ weight: 7, points: -1.03, impact: "bearish" }) });
    expect(horizonHeadline(s)).toBe("Hlavní faktor: Pozicování −1,0 b.");
  });
});

describe("summarizeChange", () => {
  const base = {
    id: 1, changed_at: "2026-09-28T10:00:00+00:00", horizon: "1-10d" as const, reason: "",
    related_news_ids: [], related_observation_ids: [],
  };
  it("flags a first reading", () => {
    const s = summarizeChange({ ...base, old_score: null, new_score: 49, old_bias: null, new_bias: "NEUTRAL", pillar_deltas: {} });
    expect(s.isFirstReading).toBe(true);
    expect(s.delta).toBeNull();
    expect(s.headline).toBe("První hodnocení pro tento horizont.");
  });
  it("leads with the largest pillar move and detects a bias flip", () => {
    const s = summarizeChange({
      ...base, old_score: 72, new_score: 64, old_bias: "LONG", new_bias: "NEUTRAL",
      pillar_deltas: {
        usd: { old_points: 1, new_points: -1, old_impact: "bullish", new_impact: "bearish" },
        real_yields: { old_points: 10, new_points: 4, old_impact: "bullish", new_impact: "bullish" },
      },
    });
    expect(s.delta).toBe(-8);
    expect(s.biasChanged).toBe(true);
    expect(s.headline).toBe("Reálné výnosy: +10,0 → +4,0 b., a 1 další pilíř.");
  });
});

describe("format", () => {
  it("uses Czech decimal comma, a real minus sign and no negative zero", () => {
    expect(signed(3.14)).toBe("+3,1");
    expect(signed(-3.14)).toBe("−3,1");
    expect(signed(-0.01)).toBe("0,0");
    expect(scoreText(49.49)).toBe("49,5");
    expect(num(-2.85)).toBe("−2,850");
  });
  it("maps the 0–100 score back to the net pillar sum", () => {
    expect(netFromScore(50)).toBe(0);
    expect(netFromScore(86)).toBe(72);
  });
  it("computes Czech relative times and calendar-day distance", () => {
    const now = new Date("2026-09-28T12:00:00Z");
    expect(relativeTime("2026-09-28T11:30:00Z", now)).toBe("před 30 min");
    expect(relativeTime("2026-09-28T12:30:00Z", now)).toBe("za 30 min");
    expect(relativeTime("2026-09-25T12:00:00Z", now)).toBe("před 3 dny");
    expect(daysUntil("2026-10-28", now)).toBe(30);
    expect(inDays(30)).toBe("za 30 dní");
    expect(inDays(2)).toBe("za 2 dny");
    expect(inDays(1)).toBe("zítra");
  });
  it("calls data stale only after two missed refreshes", () => {
    const now = new Date("2026-09-28T12:00:00Z");
    expect(isStale("2026-09-28T11:10:00Z", 30, now)).toBe(false);
    expect(isStale("2026-09-28T10:50:00Z", 30, now)).toBe(true);
    expect(isStale(null, 30, now)).toBe(false);
  });
  it("labels GDELT sources by their outlet", () => {
    expect(sourceLabel("gdelt:reuters.com")).toBe("reuters.com (přes GDELT)");
    expect(sourceLabel("Fed")).toBe("Fed");
  });
});
