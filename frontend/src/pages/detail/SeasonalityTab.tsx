import { Panel } from "../../components/Panel";
import { Unavailable } from "../../components/ui";
import { signed } from "../../lib/format";
import type { SeasonDaily, Seasonality, SeasonalityLong } from "../../lib/types";
import { SeasonalityLongSection } from "./SeasonalityLong";

const SHORT = ["Led", "Úno", "Bře", "Dub", "Kvě", "Čvn", "Čvc", "Srp", "Zář", "Říj", "Lis", "Pro"];

/** How gold did in each calendar month: average bars, win rate, year-by-year heatmap. */
export function SeasonalityTab({ s, long, daily }: {
  s: Seasonality | null | undefined;
  long?: SeasonalityLong | null;
  daily?: { gold?: SeasonDaily | null; usd?: SeasonDaily | null } | null;
}) {
  if (!s && !long) return <Unavailable>Sezónnost se spočítá, až budou k dispozici ceny zlata.</Unavailable>;
  if (!s) {
    return (
      <div className="ov">
        <SeasonalityLongSection long={long!} daily={daily} />
      </div>
    );
  }
  const years = [...new Set(s.months.flatMap((m) => m.by_year.map((y) => y.year)))].sort();
  const max = Math.max(...s.months.map((m) => Math.abs(m.avg ?? 0)), 1);
  return (
    <div className="ov">
      {long && <SeasonalityLongSection long={long} daily={daily} />}
      {long && (
        <div>
          <h2 className="section-h">Krátká historie z ceny PAXG (týdenní svíčky)</h2>
          <p className="muted small">
            Počítá změnu od konce do konce měsíce za posledních pár let; dlouhá historie výše porovnává měsíční průměry za 5–15 let. Čísla se
            proto mohou lišit — pro skóre metodiky platí dlouhá historie.
          </p>
        </div>
      )}
      <section className="panel season-hero">
        <div className="season-now">
          <span className="muted small">Tento měsíc</span>
          <p>{s.current_text}</p>
        </div>
        <div className="season-now">
          <span className="muted small">Příští měsíc</span>
          <p>{s.next_text}</p>
        </div>
      </section>
      <Panel title="Průměrná změna podle měsíce" tag={`zlato ${s.years_from}–${s.years_to}`} icon="sun">
        <div className="season-bars" role="img" aria-label="Průměrná měsíční změna ceny zlata">
          {s.months.map((m) => {
            const v = m.avg ?? 0;
            const hPct = (Math.abs(v) / max) * 100;
            return (
              <div key={m.month} className={`sb${m.month === s.current_month ? " is-now" : ""}`} title={`${m.name}: průměr ${m.avg === null ? "—" : signed(m.avg) + " %"}, růst v ${m.win_rate ?? "—"} % let (${m.years} let)`}>
                <div className="sb-plot">
                  <div className="sb-half sb-up">{v > 0 && <span className="sb-bar pos" style={{ height: `${hPct}%` }} />}</div>
                  <div className="sb-half sb-down">{v < 0 && <span className="sb-bar neg" style={{ height: `${hPct}%` }} />}</div>
                </div>
                <span className={`sb-val ${v > 0 ? "tone-bullish" : v < 0 ? "tone-bearish" : ""}`}>{m.avg === null ? "—" : signed(m.avg)}</span>
                <span className="sb-win small muted">{m.win_rate === null ? "" : `${m.win_rate} %`}</span>
                <span className="sb-name">{SHORT[m.month - 1]}</span>
              </div>
            );
          })}
        </div>
        <p className="muted small">Sloupec = průměrná změna za měsíc v %, pod ním podíl let, kdy zlato v daném měsíci rostlo. Zvýrazněn je aktuální měsíc.</p>
      </Panel>
      <Panel title="Rok po roku" tag="změna za měsíc v %" icon="calendar">
        <div className="heat-wrap">
          <table className="heat">
            <thead>
              <tr>
                <th />
                {SHORT.map((m, i) => <th key={m} className={i + 1 === s.current_month ? "is-now" : ""}>{m}</th>)}
              </tr>
            </thead>
            <tbody>
              {years.map((y) => (
                <tr key={y}>
                  <th>{y}</th>
                  {s.months.map((m) => {
                    const r = m.by_year.find((b) => b.year === y)?.ret;
                    const a = r === undefined ? 0 : Math.min(1, Math.abs(r) / 6);
                    return (
                      <td key={m.month}
                          style={r === undefined ? undefined : { background: r >= 0 ? `rgba(30, 194, 139, ${0.15 + a * 0.6})` : `rgba(242, 69, 61, ${0.15 + a * 0.6})` }}>
                        {r === undefined ? "" : signed(r)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small">{s.note}</p>
      </Panel>
    </div>
  );
}
