import { DirectionBadge, ScoreMeter } from "../../components/ui";
import { horizonHeadline } from "../../lib/explain";
import { HORIZONS, HORIZON_LABELS, scoreText } from "../../lib/format";
import type { Horizon, ScoreSnapshot } from "../../lib/types";

export function Horizons({
  scores,
  selected,
  onSelect,
}: {
  scores: Partial<Record<Horizon, ScoreSnapshot>>;
  selected: Horizon;
  onSelect: (h: Horizon) => void;
}) {
  return (
    <section className="card section area-horizons" aria-labelledby="horizons-title">
      <header className="section-head">
        <div>
          <h2 id="horizons-title">Časové horizonty</h2>
          <p className="section-sub">
            Každý horizont váží stejná data podle jejich stáří jinak (čerstvé zprávy a statistiky mají největší váhu během dne, denní
            tržní data neztrácejí váhu nikdy). Kliknutím vybereš horizont, podle kterého se řídí sekce níže.
          </p>
        </div>
      </header>
      <div className="horizon-grid" role="tablist" aria-label="Horizont">
        {HORIZONS.map((h) => {
          const s = scores[h];
          return (
            <button
              key={h}
              type="button"
              role="tab"
              aria-selected={selected === h}
              className={`horizon-tile ${selected === h ? "is-selected" : ""}`}
              onClick={() => onSelect(h)}
              disabled={!s}
            >
              <span className="horizon-name">{HORIZON_LABELS[h]}</span>
              {s ? (
                <>
                  <span className="horizon-score">
                    {scoreText(s.score)}
                    <span className="hero-unit">/100</span>
                  </span>
                  <DirectionBadge direction={s.direction} size="sm" />
                  <ScoreMeter score={s.score} compact />
                  <span className="horizon-why">{horizonHeadline(s)}</span>
                </>
              ) : (
                <span className="muted small">Nespočítáno</span>
              )}
            </button>
          );
        })}
      </div>
    </section>
  );
}
