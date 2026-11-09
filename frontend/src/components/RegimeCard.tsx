import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { formatDateTime } from "../lib/format";
import type { RegimeDimension } from "../lib/types";
import { Icon } from "./Icon";
import { Card, Empty, ErrorState, Skeleton } from "./ui";

/** Tone of a dimension for the colour of its state (nothing here is a trading signal). */
function tone(d: RegimeDimension): string {
  if (!d.available) return "muted";
  if (["trend_up", "usd_down", "real_down", "risk_on", "stable"].includes(d.state)) return "pos";
  if (["trend_down", "usd_up", "real_up", "risk_off", "breaking", "extreme", "high"].includes(d.state)) return "neg";
  return "neutral";
}

/** Market regime of gold (Ú2): what kind of market it is now — trend or range, volatility, risk mood, dollar, real
 * yields and the intermarket relationships. Deterministic, every input with its source; context, not a trade signal. */
export function RegimeCard({ i = 7 }: { i?: number }) {
  const data = useAsync(() => api.regime(), []);
  const r = data.data;
  return (
    <Card title="Režim trhu" icon={<Icon name="layers" size={16} />} i={i} id="rezim">
      {data.error && !r ? (
        <Empty>{data.error.message}</Empty>
      ) : !r ? (
        <Skeleton rows={4} />
      ) : (
        <>
          <p className="hint" style={{ marginTop: 0 }}>
            <strong>{r.label}</strong>
          </p>
          <div className="twrap">
            <table className="dtable regime">
              <thead>
                <tr>
                  <th>Oblast</th>
                  <th>Stav</th>
                  <th>Z čeho (data)</th>
                  <th>Co to znamená</th>
                </tr>
              </thead>
              <tbody>
                {r.dimensions.map((d) => (
                  <tr key={d.key}>
                    <td>{d.label}</td>
                    <td className={`rg-${tone(d)}`}>
                      <strong>{d.word}</strong>
                    </td>
                    <td>
                      {d.detail}
                      {d.inputs.length > 0 && (
                        <small>
                          {[...new Set(d.inputs.map((x) => x.source).filter(Boolean))].join(" · ")}
                        </small>
                      )}
                    </td>
                    <td>{d.implication ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="note">
            {r.note} Spočteno {formatDateTime(r.computed_at)}.
          </p>
        </>
      )}
      {data.error && r && <ErrorState message={data.error.message} onRetry={data.reload} />}
    </Card>
  );
}
