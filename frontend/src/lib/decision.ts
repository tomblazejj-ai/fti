// FTI's decision for gold on the dashboard: the engine's rule-based verdict (not AI), with the app's rules above it —
// no LONG / SHORT without a LIVE price (the same rule as the backend's live gate) and nothing while the market is closed.
import type { GoldVerdict, LiveQuote } from "./types";

export type DecisionKind = "LONG" | "SHORT" | "NEUTRAL" | "NO TRADE";

export interface Decision {
  kind: DecisionKind;
  reason: string;
  /** what the engine's verdict alone says (when a rule turned it into NO TRADE) */
  engine?: DecisionKind;
}

export function ftiDecision(verdict: GoldVerdict | null | undefined, gold: LiveQuote | undefined, marketOpen: boolean | undefined): Decision {
  if (!verdict) return { kind: "NO TRADE", reason: "Verdikt FTI pro zlato teď není k dispozici, takže rozhodnutí chybí." };
  const engine: DecisionKind = verdict.action === "long" ? "LONG" : verdict.action === "short" ? "SHORT" : "NEUTRAL";
  if (marketOpen === false) return { kind: "NO TRADE", engine, reason: "Trh se zlatem je teď zavřený — žádný obchod." };
  if (engine === "NEUTRAL") return { kind: "NEUTRAL", reason: `${verdict.action_text} ${verdict.summary}` };
  if (!gold) {
    return { kind: "NO TRADE", engine, reason: "Bez živé ceny zlata FTI nevydává obchodní signál (živý engine teď neběží)." };
  }
  if (gold.status !== "LIVE") {
    return { kind: "NO TRADE", engine, reason: `Cena XAUUSD teď není živá (${gold.status_cs}) — FTI bez živé ceny nevydává obchodní signál.` };
  }
  return { kind: engine, reason: `${verdict.action_text} ${verdict.summary}` };
}
