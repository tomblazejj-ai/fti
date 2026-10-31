import { Panel } from "../../components/Panel";
import { Unavailable } from "../../components/ui";
import { useTickers } from "../../hooks/useTickers";
import { formatDateTime, shortDate, signed, usd } from "../../lib/format";
import type { SourceStatus } from "../../lib/types";

const STATUS = {
  ok: { word: "aktuální", cls: "ok" },
  closed: { word: "trh zavřen", cls: "closed" },
  late: { word: "zpožděné", cls: "late" },
  missing: { word: "chybí", cls: "missing" },
} as const;

function asOf(v: string | null): string {
  if (!v) return "—";
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return shortDate(v);
  if (/^\d{4}–\d{4}$/.test(v)) return v;
  return formatDateTime(v);
}

export function sourceProblems(rows: SourceStatus[] | undefined): number {
  return (rows ?? []).filter((r) => r.status === "late" || r.status === "missing").length;
}

/** Where every number comes from, what date it is for, and whether it is as fresh as it can be. */
export function SourcesTab({ rows }: { rows: SourceStatus[] | undefined }) {
  const t = useTickers();
  const check = t?.price_check;
  return (
    <div className="ov">
      <Panel title="Kontrola ceny zlata" tag="3 nezávislé zdroje" icon="target" note={t ? `obnova každou minutu` : undefined}>
        {!check ? (
          <Unavailable>Kontrola ceny se načítá…</Unavailable>
        ) : (
          <>
            <ul className="pcheck">
              {Object.entries(check.quotes).map(([k, v]) => (
                <li key={k}>
                  <span>{k}</span>
                  <strong>{usd(v)}</strong>
                  <span className="muted small">{check.gaps_pct && k in check.gaps_pct ? `${signed(check.gaps_pct[k], 2)} %` : ""}</span>
                </li>
              ))}
            </ul>
            <p className={check.ok === false ? "tone-bearish" : check.ok ? "tone-bullish" : "muted"}>
              <strong>{check.ok === false ? "⚠ " : check.ok ? "✓ " : ""}{check.text}</strong>
            </p>
            <p className="muted small">
              Grafy a technika počítají s PAXG/USD (token krytý 1:1 uncí fyzického zlata, Kraken). BullionVault je burza fyzického zlata
              (prostřední cena z londýnského trezoru), XAUT je druhý zlatý token. Spot XAUUSD u brokera (např. OANDA) se od PAXG obvykle liší o
              několik dolarů — úrovně ber jako zóny, ne jako přesné ceny.
            </p>
          </>
        )}
      </Panel>

      <Panel title="Zdroje a čerstvost dat" tag="vše zdarma, bez registrace" icon="layers">
        {!rows?.length ? (
          <Unavailable>Přehled zdrojů se spočítá při příštím přepočtu.</Unavailable>
        ) : (
          <div className="table-wrap">
            <table className="src-table">
              <thead>
                <tr>
                  <th>Stav</th>
                  <th>Co</th>
                  <th>Zdroj</th>
                  <th>Data k</th>
                  <th>Jak často</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.key}>
                    <td><span className={`src-dot s-${STATUS[r.status].cls}`} /> {STATUS[r.status].word}</td>
                    <td>
                      <strong>{r.label}</strong>
                      {r.note && <span className="muted small src-note">{r.note}</span>}
                    </td>
                    <td className="small">{r.provider}</td>
                    <td className="small">{asOf(r.as_of)}</td>
                    <td className="small muted">{r.rhythm}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted small">
          „Data k“ = k jakému okamžiku nebo období hodnota patří (u měsíčních čísel měsíc, za který jsou). Měsíční a týdenní data nejdou mít
          novější, než je zdroj vydá — proto „aktuální“ znamená „nejnovější, co existuje“.
        </p>
      </Panel>
    </div>
  );
}
