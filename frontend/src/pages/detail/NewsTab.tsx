import { ErrorState, ExternalLink, Loading } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { api } from "../../lib/api";
import { IMPACT_LABELS, PILLAR_LABELS, formatDateTime, relativeTime, sourceLabel } from "../../lib/format";
import type { NewsEvent, NewsMood } from "../../lib/types";

const IMPACT_ICON = { bullish: "▲", bearish: "▼", neutral: "●" } as const;

export function NewsTab({ code, refreshKey, mood }: { code: string; refreshKey: number; mood: NewsMood | null }) {
  const news = useAsync(() => api.news(code), [code, refreshKey]);
  const scored = news.data?.events.filter((e) => e.factors.length > 0) ?? [];
  const context = news.data?.events.filter((e) => e.factors.length === 0) ?? [];

  return (
    <div className="tab-body">
      {mood && (
        <p className="cot-lead">
          <strong>
            Za posledních {mood.hours / 24} dny: {mood.bullish} zpráv pro růst zlata, {mood.bearish} pro pokles
          </strong>{" "}
          <span className="muted small">(celkem {mood.count} zpráv s vlivem na zlato)</span>
        </p>
      )}
      <p className="muted small">
        Zdroje: fxstreet.cz (česky), FXStreet, Investing.com, CNBC, MarketWatch, tiskové zprávy Fedu, ECB a BoE a GDELT. Anglické titulky jsou
        strojově přeložené v tvém počítači — originál zobrazíš najetím myši. Stejná událost z více zdrojů se počítá jen jednou.
      </p>
      {news.loading && !news.data && <Loading label="Načítám zprávy…" />}
      {news.error && <ErrorState message={news.error.message} onRetry={news.reload} />}
      {news.data && (
        <>
          <h3>Zprávy, které hýbou zlatem</h3>
          {scored.length === 0 ? <p className="muted">Za posledních 60 dní žádné.</p> : <NewsList events={scored.slice(0, 30)} />}
          {context.length > 0 && (
            <details className="tech-why">
              <summary>Další zprávy o zlatě ({context.length}) — jen pro kontext, do hodnocení nevstupují</summary>
              <NewsList events={context.slice(0, 30)} />
            </details>
          )}
        </>
      )}
    </div>
  );
}

function NewsList({ events }: { events: NewsEvent[] }) {
  return (
    <ul className="news-list">
      {events.map((e) => (
        <li key={e.event_id} className="news">
          <div className="news-row">
            {e.factors.length > 0 ? (
              <span className={`news-impact tone-${e.impact}`} title={IMPACT_LABELS[e.impact]}>
                {IMPACT_ICON[e.impact]}
              </span>
            ) : (
              <span className="news-impact muted">·</span>
            )}
            <div>
              <p className="news-title" title={e.translated ? `Originál: ${e.headline_original}` : undefined}>
                <ExternalLink href={e.url}>{e.headline}</ExternalLink>
              </p>
              <div className="muted small">
                {sourceLabel(e.source)} · <span title={formatDateTime(e.published_at)}>{relativeTime(e.published_at)}</span>
                {e.translated && <> · strojový překlad</>}
                {e.factors.length > 0 && <> · {e.factors.map((f) => PILLAR_LABELS[f.pillar]).join(", ")}</>}
                {e.report_count > 1 && <> · {e.report_count} zdroje o téže události</>}
              </div>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}
