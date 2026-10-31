import { Section, Unavailable } from "../../components/ui";
import type { Scenario, ScoreSnapshot } from "../../lib/types";

const ORDER = [
  { key: "base", title: "Základní scénář", tone: "neutral" },
  { key: "bull", title: "Býčí scénář", tone: "bullish" },
  { key: "bear", title: "Medvědí scénář", tone: "bearish" },
] as const;

export function Scenarios({ snapshot }: { snapshot: ScoreSnapshot }) {
  return (
    <Section
      id="scenarios"
      className="area-scenarios"
      title="Scénáře"
      subtitle="Sestavené z aktuálních hodnot pilířů — na čem každý scénář stojí, co by k němu vedlo a co se může pokazit."
    >
      <div className="scenario-grid">
        {ORDER.map(({ key, title, tone }) => {
          const s = snapshot.scenarios[key];
          return (
            <article key={key} className={`scenario tone-border-${tone}`}>
              <h3 className={`tone-${tone}`}>
                <span aria-hidden="true">{tone === "bullish" ? "▲" : tone === "bearish" ? "▼" : "●"}</span> {title.toUpperCase()}
              </h3>
              {s ? <ScenarioBody s={s} /> : <Unavailable>Tento scénář backend neposkytl.</Unavailable>}
            </article>
          );
        })}
      </div>
    </Section>
  );
}

function ScenarioBody({ s }: { s: Scenario }) {
  return (
    <>
      <p>{s.narrative}</p>
      <h4>Co ho podporuje</h4>
      <List items={s.supports} />
      <h4>Co by ho mohlo změnit</h4>
      <List items={s.would_change} />
      <h4>Hlavní rizika</h4>
      <List items={s.key_risks} />
    </>
  );
}

function List({ items }: { items: string[] }) {
  if (!items.length) return <p className="muted small">Z aktuálních dat nic nevyplývá.</p>;
  return (
    <ul>
      {items.map((i, idx) => (
        <li key={idx}>{i}</li>
      ))}
    </ul>
  );
}
