import type { Horizon, ScoreSnapshot } from "../../lib/types";
import { Changes } from "./Changes";
import { Events } from "./Events";
import { FundCard } from "./FundCard";
import { Horizons } from "./Horizons";
import { Invalidation } from "./Invalidation";
import { Pillars } from "./Pillars";
import { Scenarios } from "./Scenarios";
import { Why } from "./Why";

export function FundTab({
  code,
  assetName,
  scores,
  horizon,
  onHorizon,
  refreshKey,
}: {
  code: string;
  assetName: string;
  scores: Partial<Record<Horizon, ScoreSnapshot>>;
  horizon: Horizon;
  onHorizon: (h: Horizon) => void;
  refreshKey: number;
}) {
  const primary = scores["1-10d"];
  const snapshot = scores[horizon];
  return (
    <div className="tab-body fund-tab">
      <div className="fund-tab-top">
        {primary && <FundCard snapshot={primary} />}
        <Events />
      </div>
      <details className="more">
        <summary>
          <span className="more-name">Podrobný rozbor fundamentu</span>
          <span className="muted small">časové horizonty, všech 8 pilířů, scénáře, historie změn</span>
        </summary>
        <div className="more-body">
          <Horizons scores={scores} selected={horizon} onSelect={onHorizon} />
          {snapshot && (
            <>
              <Why snapshot={snapshot} assetName={assetName} />
              <Pillars snapshot={snapshot} />
              <Scenarios snapshot={snapshot} />
              <Invalidation snapshot={snapshot} />
            </>
          )}
          <Changes code={code} horizon={horizon} refreshKey={refreshKey} />
        </div>
      </details>
    </div>
  );
}
