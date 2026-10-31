import { buildWhy, type WhyItem } from "../../lib/explain";
import { QUALITY_LABELS, signed } from "../../lib/format";
import type { ScoreSnapshot } from "../../lib/types";

export function Why({ snapshot, assetName }: { snapshot: ScoreSnapshot; assetName: string }) {
  const why = buildWhy(snapshot, assetName);
  const tone = snapshot.direction.toLowerCase();
  return (
    <section className={`card section why area-why tone-border-${tone}`} aria-labelledby="why-title">
      <header className="section-head">
        <h2 id="why-title" className="why-title">{why.question.toUpperCase()}</h2>
      </header>
      <p className="why-summary">{why.summary}</p>
      {why.evidenceIsLimited && (
        <p className="why-warning" role="note">
          <span aria-hidden="true">◐</span> Omezená data: daty je teď podložena méně než polovina pilířů.
        </p>
      )}
      <div className="why-cols">
        <WhyList title="Pro růst zlata" items={why.supporting} empty="Růst teď nepodporuje žádný pilíř s daty." tone="bullish" />
        <WhyList title="Proti zlatu" items={why.opposing} empty="Proti zlatu teď nemluví žádný pilíř s daty." tone="bearish" />
      </div>
      {why.flat.length > 0 && (
        <p className="muted small">
          Hodnoceno, téměř neutrální: {why.flat.map((f) => `${f.label} (${signed(f.points)} b.)`).join(", ")}.
        </p>
      )}
      {why.notAssessed.length > 0 && (
        <details className="why-na">
          <summary>
            Nehodnoceno ({why.notAssessed.length}) — chybí použitelná data, tyto pilíře přispívají nulou a nepočítají se jako důvody
          </summary>
          <ul>
            {why.notAssessed.map((n) => (
              <li key={n.pillar}>
                <strong>{n.label}</strong> <span className="muted">({QUALITY_LABELS[n.quality]})</span> — {n.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function WhyList({ title, items, empty, tone }: { title: string; items: WhyItem[]; empty: string; tone: "bullish" | "bearish" }) {
  return (
    <div className="why-list">
      <h3 className={`tone-${tone}`}>
        <span aria-hidden="true">{tone === "bullish" ? "▲" : "▼"}</span> {title}
      </h3>
      {items.length === 0 ? (
        <p className="muted small">{empty}</p>
      ) : (
        <ol>
          {items.map((i) => (
            <li key={i.pillar}>
              <strong>{i.label}</strong> <span className={`tone-${tone}`}>{signed(i.points)} b.</span>
              <span className="muted"> z ±{i.weight}</span>
              {i.quality === "partial" && <span className="tag quality-partial why-partial">◐ částečná data</span>}
              <div className="why-reason">{i.reason}</div>
              <div className="muted small">Zdroj: {i.source}</div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
