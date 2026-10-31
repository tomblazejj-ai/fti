import { ContributionBar, ImpactTag, QualityTag, Section } from "../../components/ui";
import { PILLAR_LABELS, PILLAR_ORDER, shortDate, signed } from "../../lib/format";
import type { ScoreSnapshot } from "../../lib/types";

export function Pillars({ snapshot }: { snapshot: ScoreSnapshot }) {
  return (
    <Section
      id="pillars"
      className="area-pillars"
      title="Fundamentální pilíře"
      subtitle="Příspěvek každého pilíře v rámci jeho vlastní váhy ±. Váhy dávají dohromady 100. Pilíř bez použitelných dat přispívá nulou a je tak označen — nikdy se nevykresluje jako nulové hodnocení."
    >
      <ul className="pillar-list">
        {PILLAR_ORDER.map((key) => {
          const p = snapshot.pillar_breakdown[key];
          if (!p) return null;
          const unavailable = p.data_quality === "unavailable";
          return (
            <li key={key} className={`pillar ${unavailable ? "pillar-na" : ""}`}>
              <div className="pillar-head">
                <span className="pillar-name">{PILLAR_LABELS[key]}</span>
                <span className="pillar-points">
                  {unavailable ? <span className="muted">nehodnoceno</span> : <span className={`tone-${p.impact}`}>{signed(p.points)}</span>}
                  <span className="muted"> / ±{p.weight}</span>
                </span>
              </div>
              <ContributionBar points={p.points} weight={p.weight} unavailable={unavailable} />
              <div className="pillar-tags">
                {!unavailable && <ImpactTag impact={p.impact} />}
                <QualityTag quality={p.data_quality} />
                <span className="muted small">data k {shortDate(p.as_of)}</span>
              </div>
              <div className="muted small pillar-source">Zdroj: {p.source}</div>
              <details className="pillar-reasons" open={!unavailable}>
                <summary>Vysvětlení ({p.reasons.length})</summary>
                <ul>
                  {p.reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </details>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}
