// TEST-ONLY fixtures. Never imported by application code — production views
// render exclusively what the backend returns.
import type { Pillar, PillarKey, ScoreSnapshot } from "../lib/types";

export function pillar(overrides: Partial<Pillar> = {}): Pillar {
  return {
    weight: 10,
    raw_signal: 0,
    points: 0,
    impact: "neutral",
    reasons: ["reason"],
    data_quality: "ok",
    source: "TEST SOURCE",
    as_of: "2026-09-26",
    ...overrides,
  };
}

const UNAVAILABLE = (weight: number): Pillar =>
  pillar({ weight, data_quality: "unavailable", reasons: ["chybí data"], as_of: null });

export function snapshot(overrides: Partial<ScoreSnapshot> = {}, pillars: Partial<Record<PillarKey, Pillar>> = {}): ScoreSnapshot {
  return {
    instrument: "XAUUSD",
    horizon: "1-10d",
    computed_at: "2026-09-28T10:00:00+00:00",
    bias: "NEUTRAL",
    direction: "NEUTRAL",
    score: 50,
    pillar_breakdown: {
      fed: UNAVAILABLE(20),
      real_yields: UNAVAILABLE(20),
      inflation: UNAVAILABLE(15),
      usd: UNAVAILABLE(15),
      economy: UNAVAILABLE(10),
      central_banks: pillar({ weight: 8, data_quality: "partial", reasons: ["Žádné zprávy"] }),
      geopolitics: pillar({ weight: 5, data_quality: "partial", reasons: ["Žádné zprávy"] }),
      positioning: UNAVAILABLE(7),
      ...pillars,
    },
    drivers: [],
    contrarian: [],
    risks: ["risk A"],
    scenarios: {
      base: { narrative: "base narrative", supports: ["s1"], would_change: ["w1"], key_risks: ["r1"] },
      bull: { narrative: "bull narrative", supports: ["s2"], would_change: ["w2"], key_risks: ["r2"] },
      bear: { narrative: "bear narrative", supports: ["s3"], would_change: ["w3"], key_risks: ["r3"] },
    },
    invalidation: ["Příští FOMC rozhodnutí o sazbách: 2026-10-28"],
    ...overrides,
  };
}
