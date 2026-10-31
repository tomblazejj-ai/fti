import { ErrorState, ExternalLink, ImpactTag, Loading, Section } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { api } from "../../lib/api";
import { PILLAR_LABELS, formatDateTime, relativeTime, sourceLabel } from "../../lib/format";
import type { NewsEvent } from "../../lib/types";

export function News({ code, refreshKey, gdeltFailures }: { code: string; refreshKey: number; gdeltFailures: number }) {
  const news = useAsync(() => api.news(code), [code, refreshKey]);
  return (
    <Section
      id="news"
      className="area-news"
      title="Nejnovější relevantní zprávy"
      subtitle="Seskupeno podle událostí: více článků o téže události se zobrazí jako JEDNA událost a do skóre se započítá jen jednou — nejde o nezávislá potvrzení."
    >
      {gdeltFailures > 0 && (
        <p className="why-warning" role="note">
          <span aria-hidden="true">◐</span> Při poslední aktualizaci {gdeltFailures === 1 ? "selhal 1 dotaz" : `selhaly ${gdeltFailures} dotazy`} na GDELT
          (omezení počtu požadavků) — zprávy nemusí být úplné. Zprávy centrálních bank (RSS) to neovlivnilo.
        </p>
      )}
      {news.loading && !news.data && <Loading label="Načítám zprávy…" />}
      {news.error && <ErrorState message={news.error.message} onRetry={news.reload} />}
      {news.data && news.data.events.length === 0 && (
        <p className="muted">Za posledních 60 dní nebyla nalezena žádná zpráva relevantní pro {code}.</p>
      )}
      {news.data && news.data.events.length > 0 && (
        <ul className="news-list">
          {news.data.events.map((e) => (
            <NewsRow key={e.event_id} event={e} />
          ))}
        </ul>
      )}
    </Section>
  );
}

function NewsRow({ event }: { event: NewsEvent }) {
  return (
    <li className="news">
      <div className="news-head">
        {event.factors.length > 0 && <ImpactTag impact={event.impact} />}
        <span className="muted small" title={formatDateTime(event.published_at)}>
          {sourceLabel(event.source)} · {relativeTime(event.published_at)}
        </span>
      </div>
      <p className="news-title">
        <ExternalLink href={event.url}>{event.headline}</ExternalLink>
      </p>
      <div className="news-tags">
        {event.factors.length === 0 && (
          <span className="tag quality-unavailable" title="Zmiňuje instrument, ale neodpovídá žádnému fundamentálnímu faktoru, takže nevstupuje do žádného pilíře.">
            jen pro kontext — nezapočítáno
          </span>
        )}
        {event.factors.map((f) => (
          <span key={f.factor} className="tag">
            pilíř {PILLAR_LABELS[f.pillar]}
          </span>
        ))}
        {event.instrument_tags.map((t) => (
          <span key={t} className="tag tag-inst">
            {t}
          </span>
        ))}
      </div>
      {event.report_count > 1 && (
        <details className="news-reports">
          <summary>
            Jedna událost · {event.report_count} {event.report_count < 5 ? "články" : "článků"} — do skóre započítáno jednou
          </summary>
          <ul>
            {event.reports.map((r) => (
              <li key={r.id}>
                <ExternalLink href={r.url}>{r.title}</ExternalLink>{" "}
                <span className="muted small">
                  {sourceLabel(r.source)} · {formatDateTime(r.published_at)}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}
