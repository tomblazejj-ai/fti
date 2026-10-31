// Builds the human-readable "PROČ?" explanation strictly from what the
// backend returned. A pillar is only cited as a reason if real data moved
// it; if the evidence is thin, the text says so instead of filling the gap.

import { DIRECTION_LABELS, HORIZON_LABELS, PILLAR_LABELS, PILLAR_ORDER, scoreText, signed } from "./format";
import type { DataQuality, Pillar, PillarKey, ScoreSnapshot } from "./types";

export interface WhyItem {
  pillar: PillarKey;
  label: string;
  points: number;
  weight: number;
  reason: string;
  source: string;
  quality: DataQuality;
}

export interface WhyExplanation {
  question: string;
  summary: string;
  supporting: WhyItem[];
  opposing: WhyItem[];
  flat: WhyItem[];
  notAssessed: { pillar: PillarKey; label: string; quality: DataQuality; reason: string }[];
  evidenceIsLimited: boolean;
}

const LIMITED_EVIDENCE_BELOW = 4; // fewer than 4 of 8 pillars backed by data
const MOVE_EPSILON = 0.05; // pts — below this a partial pillar did not move the score

/** Same rule as the backend's PillarResult.has_evidence. */
export function hasEvidence(p: Pillar): boolean {
  return p.data_quality === "ok" || (p.data_quality === "partial" && Math.abs(p.points) >= MOVE_EPSILON);
}

function item(key: PillarKey, p: Pillar): WhyItem {
  return {
    pillar: key,
    label: PILLAR_LABELS[key],
    points: p.points,
    weight: p.weight,
    reason: p.reasons[0] ?? "",
    source: p.source,
    quality: p.data_quality,
  };
}

export function buildWhy(snapshot: ScoreSnapshot, assetName = "Zlato"): WhyExplanation {
  const entries = PILLAR_ORDER.flatMap((key) => {
    const p = snapshot.pillar_breakdown[key];
    return p ? [[key, p] as const] : [];
  });

  const evidenced = entries.filter(([, p]) => hasEvidence(p));
  const byMagnitude = (a: WhyItem, b: WhyItem) => Math.abs(b.points) - Math.abs(a.points);

  // Classified by the backend's own impact label, so the text never calls a
  // pillar "supporting" while its card says "neutral".
  const supporting = evidenced.filter(([, p]) => p.impact === "bullish").map(([k, p]) => item(k, p)).sort(byMagnitude);
  const opposing = evidenced.filter(([, p]) => p.impact === "bearish").map(([k, p]) => item(k, p)).sort(byMagnitude);
  const flat = evidenced.filter(([, p]) => p.impact === "neutral").map(([k, p]) => item(k, p));
  const notAssessed = entries
    .filter(([, p]) => !hasEvidence(p))
    .map(([k, p]) => ({ pillar: k, label: PILLAR_LABELS[k], quality: p.data_quality, reason: p.gaps?.[0] ?? p.reasons[0] ?? "" }));
  const partialCount = evidenced.filter(([, p]) => p.data_quality === "partial").length;

  const asset = assetName.toLowerCase();
  const directionWord = DIRECTION_LABELS[snapshot.direction].toLowerCase();
  const question = `Proč je výhled pro ${asset} ${directionWord}?`;
  const evidenceIsLimited = evidenced.length < LIMITED_EVIDENCE_BELOW;

  const parts: string[] = [
    `Na horizontu ${HORIZON_LABELS[snapshot.horizon]} má ${asset} skóre ${scoreText(snapshot.score)}/100 (${DIRECTION_LABELS[snapshot.direction]}).`,
  ];
  if (supporting.length) parts.push(`Pro růst mluví: ${joinLabels(supporting)} (celkem ${signed(sum(supporting))} b.).`);
  if (opposing.length) parts.push(`Proti mluví: ${joinLabels(opposing)} (celkem ${signed(sum(opposing))} b.).`);
  if (!supporting.length && !opposing.length) {
    parts.push("Žádný pilíř s použitelnými daty teď skóre neposouvá ani nahoru, ani dolů.");
  }
  parts.push(
    `Daty je podloženo ${evidenced.length} z ${entries.length} pilířů` +
      (partialCount ? ` (${partialCount} jen částečně)` : "") +
      (notAssessed.length ? `; nehodnoceno: ${joinLabels(notAssessed)}.` : "."),
  );
  if (evidenceIsLimited) parts.push("Hodnocení stojí na omezených datech — ber ho jako předběžné.");

  return { question, summary: parts.join(" "), supporting, opposing, flat, notAssessed, evidenceIsLimited };
}

/** One-line explanation for a horizon tile: the single biggest mover backed by data. */
export function horizonHeadline(snapshot: ScoreSnapshot): string {
  const movers = PILLAR_ORDER.flatMap((key) => {
    const p = snapshot.pillar_breakdown[key];
    return p && hasEvidence(p) && Math.abs(p.points) >= MOVE_EPSILON ? [item(key, p)] : [];
  }).sort((a, b) => Math.abs(b.points) - Math.abs(a.points));
  if (!movers.length) return "Skóre neposouvá žádný pilíř s daty.";
  return `Hlavní faktor: ${movers[0].label} ${signed(movers[0].points)} b.`;
}

function sum(items: WhyItem[]): number {
  return items.reduce((acc, i) => acc + i.points, 0);
}

function joinLabels(items: { label: string }[]): string {
  const labels = items.map((i) => i.label);
  if (labels.length <= 1) return labels.join("");
  return `${labels.slice(0, -1).join(", ")} a ${labels[labels.length - 1]}`;
}
