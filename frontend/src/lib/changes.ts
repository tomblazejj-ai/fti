import { IMPACT_LABELS, PILLAR_LABELS, plural, signed } from "./format";
import type { HistoryEntry, PillarDelta, PillarKey } from "./types";

export interface ChangeSummary {
  isFirstReading: boolean;
  delta: number | null;
  biasChanged: boolean;
  pillarChanges: { pillar: PillarKey; label: string; delta: PillarDelta; move: number }[];
  headline: string;
}

/** Plain-language summary of one score-history entry, built only from its stored deltas. */
export function summarizeChange(entry: HistoryEntry): ChangeSummary {
  const isFirstReading = entry.old_score === null;
  const delta = isFirstReading ? null : entry.new_score - (entry.old_score as number);
  const pillarChanges = (Object.entries(entry.pillar_deltas) as [PillarKey, PillarDelta][])
    .map(([pillar, d]) => ({ pillar, label: PILLAR_LABELS[pillar] ?? pillar, delta: d, move: d.new_points - d.old_points }))
    .sort((a, b) => Math.abs(b.move) - Math.abs(a.move));

  let headline: string;
  if (isFirstReading) {
    headline = "První hodnocení pro tento horizont.";
  } else if (pillarChanges.length) {
    const top = pillarChanges[0];
    const more = pillarChanges.length - 1;
    headline =
      `${top.label}: ${signed(top.delta.old_points)} → ${signed(top.delta.new_points)} b.` +
      (top.delta.old_impact !== top.delta.new_impact
        ? ` (${IMPACT_LABELS[top.delta.old_impact]} → ${IMPACT_LABELS[top.delta.new_impact]})`
        : "") +
      (more > 0 ? `, a ${more} ${plural(more, "další pilíř", "další pilíře", "dalších pilířů")}.` : ".");
  } else {
    headline = "Skóre se posunulo, aniž by se jediný pilíř změnil o 1 bod a víc.";
  }

  return { isFirstReading, delta, biasChanged: entry.old_bias !== null && entry.old_bias !== entry.new_bias, pillarChanges, headline };
}
