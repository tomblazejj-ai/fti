import { useState } from "react";
import { ErrorState, ExternalLink, Loading, Section } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { api } from "../../lib/api";
import { summarizeChange } from "../../lib/changes";
import { HORIZON_LABELS, IMPACT_LABELS, formatDateTime, impactOfNumber, num, scoreText, shortDate, signed, sourceLabel } from "../../lib/format";
import type { HistoryEntry, Horizon } from "../../lib/types";

export function Changes({ code, horizon, refreshKey }: { code: string; horizon: Horizon; refreshKey: number }) {
  const history = useAsync(() => api.history(code, horizon), [code, horizon, refreshKey]);
  return (
    <Section
      id="changes"
      className="area-changes"
      title="Co se změnilo?"
      subtitle={`Výrazné změny skóre na horizontu ${HORIZON_LABELS[horizon]} (změna výhledu nebo posun o 5 a více bodů). Rozklikni změnu a uvidíš přesná data, která za ní stojí.`}
    >
      {history.loading && !history.data && <Loading />}
      {history.error && <ErrorState message={history.error.message} onRetry={history.reload} />}
      {history.data && history.data.length === 0 && <p className="muted">Zatím žádné zaznamenané změny.</p>}
      {history.data && history.data.length > 0 && (
        <ul className="change-list">
          {history.data.slice(0, 15).map((e) => (
            <ChangeRow key={e.id} code={code} entry={e} />
          ))}
        </ul>
      )}
    </Section>
  );
}

function ChangeRow({ code, entry }: { code: string; entry: HistoryEntry }) {
  const [open, setOpen] = useState(false);
  const s = summarizeChange(entry);
  return (
    <li className="change">
      <button type="button" className="change-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="change-time muted">{formatDateTime(entry.changed_at)}</span>
        <span className="change-score">
          Skóre {entry.old_score === null ? "—" : scoreText(entry.old_score)} → <strong>{scoreText(entry.new_score)}</strong>
          {s.delta !== null && (
            <span className={`delta tone-${impactOfNumber(s.delta, 0.05)}`}>
              {" "}
              {s.delta > 0 ? "▲" : s.delta < 0 ? "▼" : "●"} {signed(s.delta)}
            </span>
          )}
        </span>
        <span className="change-bias">
          {entry.old_bias ?? "—"} → <strong>{entry.new_bias}</strong>
          {s.biasChanged && <span className="tag tag-warn">změna výhledu</span>}
        </span>
        <span className="change-headline">{s.headline}</span>
        <span className="change-toggle" aria-hidden="true">{open ? "−" : "+"}</span>
      </button>
      {open && <ChangeDetail code={code} entry={entry} />}
    </li>
  );
}

function ChangeDetail({ code, entry }: { code: string; entry: HistoryEntry }) {
  const detail = useAsync(() => api.historyEntry(code, entry.id), [code, entry.id]);
  const s = summarizeChange(entry);
  return (
    <div className="change-detail">
      {s.pillarChanges.length > 0 && (
        <>
          <h4>Pilíře, které se pohnuly</h4>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Pilíř</th>
                  <th className="num">Předtím</th>
                  <th className="num">Potom</th>
                  <th className="num">Změna</th>
                  <th>Dopad</th>
                </tr>
              </thead>
              <tbody>
                {s.pillarChanges.map((c) => (
                  <tr key={c.pillar}>
                    <td>{c.label}</td>
                    <td className="num">{signed(c.delta.old_points)}</td>
                    <td className="num">{signed(c.delta.new_points)}</td>
                    <td className={`num tone-${impactOfNumber(c.move, 0.05)}`}>{signed(c.move)}</td>
                    <td>
                      {IMPACT_LABELS[c.delta.old_impact]} → {IMPACT_LABELS[c.delta.new_impact]}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {detail.loading && <Loading label="Načítám data, která za touto změnou stojí…" />}
      {detail.error && <ErrorState message={detail.error.message} onRetry={detail.reload} />}
      {detail.data && (
        <>
          <h4>Data za tímto hodnocením ({detail.data.observations.length})</h4>
          {detail.data.observations.length === 0 ? (
            <p className="muted small">Pro toto hodnocení nebyla k dispozici žádná číselná data.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Řada</th>
                    <th>Období</th>
                    <th className="num">Předchozí</th>
                    <th className="num">Poslední</th>
                    <th>Jednotka</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.data.observations.map((o) => (
                    <tr key={o.id}>
                      <td>
                        <ExternalLink href={o.source_url}>
                          {o.source.toUpperCase()} {o.series}
                        </ExternalLink>
                      </td>
                      <td>{shortDate(o.period)}</td>
                      <td className="num">{o.previous === null ? "—" : num(o.previous)}</td>
                      <td className="num">{o.actual === null ? "—" : num(o.actual)}</td>
                      <td>{o.unit || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <h4>Zprávy za tímto hodnocením ({detail.data.news.length})</h4>
          {detail.data.news.length === 0 ? (
            <p className="muted small">Do tohoto hodnocení nepřispěla žádná zpráva.</p>
          ) : (
            <ul className="bullet-list">
              {detail.data.news.map((n) => (
                <li key={n.id}>
                  <ExternalLink href={n.url}>{n.title}</ExternalLink>{" "}
                  <span className="muted small">
                    {sourceLabel(n.source)} · {formatDateTime(n.published_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="muted small engine-note">Záznam výpočtu: {detail.data.reason}</p>
        </>
      )}
    </div>
  );
}
