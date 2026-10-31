import { Section } from "../../components/ui";
import { DIRECTION_LABELS } from "../../lib/format";
import type { ScoreSnapshot } from "../../lib/types";

export function Invalidation({ snapshot }: { snapshot: ScoreSnapshot }) {
  return (
    <Section
      id="invalidation"
      className="area-invalidation"
      title="Co by mohlo výhled zvrátit?"
      subtitle={`Konkrétní změny, které by posunuly současný ${DIRECTION_LABELS[snapshot.direction].toLowerCase()} výhled (${snapshot.bias}) — odvozeno z hodnot pilířů a ověřeného kalendáře událostí.`}
    >
      <ul className="bullet-list">
        {snapshot.invalidation.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
      <h3 className="subhead">Rizika tohoto hodnocení</h3>
      <p className="muted small">Mezery v datech a problémy s kvalitou, kterým je skóre teď vystavené.</p>
      <ul className="bullet-list risk-list">
        {snapshot.risks.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>
    </Section>
  );
}
