import { ContributionBar, DirectionBadge, ScoreMeter, Section } from "../../components/ui";
import { PILLAR_LABELS, PILLAR_ORDER, scoreText, signed } from "../../lib/format";
import type { ScoreSnapshot } from "../../lib/types";

/** Compact fundamental view: score + the pillars that actually move it. */
export function FundCard({ snapshot }: { snapshot: ScoreSnapshot }) {
  const movers = PILLAR_ORDER.flatMap((k) => {
    const p = snapshot.pillar_breakdown[k];
    return p && p.data_quality !== "unavailable" && Math.abs(p.points) >= 0.5 ? [{ key: k, p }] : [];
  }).sort((a, b) => Math.abs(b.p.points) - Math.abs(a.p.points));

  return (
    <Section
      id="fundament"
      className="area-fund"
      title="Fundament"
      subtitle="Makrodata (Fed, výnosy, inflace, dolar, ekonomika), pozice spekulantů a zprávy."
    >
      <div className="fund-head">
        <div className="hero-number">
          {scoreText(snapshot.score)}
          <span className="hero-unit">/100</span>
        </div>
        <DirectionBadge direction={snapshot.direction} />
      </div>
      <ScoreMeter score={snapshot.score} compact />
      <h3 className="subhead">Co skóre hýbe</h3>
      {movers.length === 0 ? (
        <p className="muted small">Žádný pilíř teď skóre výrazně neposouvá.</p>
      ) : (
        <ul className="fund-movers">
          {movers.slice(0, 5).map(({ key, p }) => (
            <li key={key}>
              <span>{PILLAR_LABELS[key]}</span>
              <ContributionBar points={p.points} weight={p.weight} />
              <span className={`num tone-${p.impact}`}>{signed(p.points)}</span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
