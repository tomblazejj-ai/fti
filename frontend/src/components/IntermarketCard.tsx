import { useState } from "react";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { formatDateTime } from "../lib/format";
import type { ImRelation } from "../lib/types";
import { Icon } from "./Icon";
import { Card, Empty, ErrorState, Pills, Skeleton } from "./ui";

type Tf = "D1" | "H1";
const UNIT: Record<Tf, string> = { D1: "dní", H1: "hodin" };

function num(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(digits).replace(".", ",")}`;
}

function win(r: ImRelation, w: number | undefined) {
  return r.windows.find((x) => x.window === w);
}

/** Intermarket Intelligence for gold: synchronised correlations, their stability and whether the other markets confirm
 * gold's latest move. Correlation is co-movement, never a cause. */
export function IntermarketCard({ i = 7 }: { i?: number }) {
  const [tf, setTf] = useState<Tf>("D1");
  const data = useAsync(() => api.intermarket(tf), [tf]);
  const res = data.data;
  const main = res?.main_window;
  const long = res?.windows?.[res.windows.length - 1];
  const rows = (res?.relations ?? []).filter((r) => win(r, main)?.r !== null && win(r, main)?.r !== undefined);
  const confirm = rows.filter((r) => r.move?.verdict === "potvrzuje");
  const contra = rows.filter((r) => r.move?.verdict === "odporuje");
  const move = rows.find((r) => r.move)?.move;
  return (
    <Card title="Mezitrh – vztahy se zlatem" icon={<Icon name="layers" size={16} />} i={i} id="mezitrh"
          extra={<Pills label="Časový rámec" value={tf} onChange={setTf}
                        options={[{ value: "D1", label: "D1" }, { value: "H1", label: "H1" }]} />}>
      {data.error && !res ? <ErrorState message={data.error.message} onRetry={data.reload} /> : !res ? <Skeleton rows={4} /> :
        res.error || rows.length === 0 ? <Empty>{res.error ?? "Pro tento rámec zatím nejsou synchronizovaná data."}</Empty> : (
        <>
          {move && (
            <p className="hint" style={{ marginTop: 0 }}>
              Zlato za posledních {move.bars} {UNIT[tf]}: <strong>{num(move.gold_pct)} %</strong>.{" "}
              Potvrzují: <strong>{confirm.map((r) => r.label).join(", ") || "žádný trh"}</strong>. Odporují:{" "}
              <strong>{contra.map((r) => r.label).join(", ") || "žádný trh"}</strong>.
            </p>
          )}
          <div className="twrap">
            <table className="dtable">
              <thead>
                <tr>
                  <th>Trh</th><th>Korelace ({main} {UNIT[tf]})</th><th>Dlouhé okno ({long})</th><th>Stabilita / rozpad</th>
                  <th>Poslední pohyb</th><th>Kvalita dat</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const w = win(r, main);
                  const lw = win(r, long);
                  return (
                    <tr key={r.b}>
                      <td>{r.label}<small>{r.sources[1]}{r.related ? ` · ${r.related}` : ""}</small></td>
                      <td title={w?.ci95 ? `95% interval ${num(w.ci95[0])} až ${num(w.ci95[1])}` : undefined}>
                        <strong>{num(w?.r)}</strong><small>n {w?.n}, efektivně {Math.round(w?.n_eff ?? 0)}, p {w?.p?.toFixed(4).replace(".", ",")}</small>
                      </td>
                      <td>{num(lw?.r)}<small>n {lw?.n}</small></td>
                      <td>{r.stability?.verdict ?? "—"}<small>{r.breakdown?.state ?? ""}{r.change ? ` · předtím ${num(r.change.r_prev)}` : ""}</small></td>
                      <td>{r.move ? r.move.verdict : "—"}{r.move && <small>{num(r.move.other)} {r.move.other_unit}</small>}</td>
                      <td title={r.quality.issues.join("; ") || undefined}>{r.quality.label}{r.quality.issues.length > 0 && <small>{r.quality.issues[0]}</small>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="note">
            {res.causality} Spočteno {formatDateTime(res.computed_at)} ze synchronizovaných výnosů (zlato: {res.target_label}).
          </p>
        </>
      )}
    </Card>
  );
}
