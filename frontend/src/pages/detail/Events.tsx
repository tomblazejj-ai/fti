import { ErrorState, ExternalLink, Loading, Section } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { api } from "../../lib/api";
import { PILLAR_LABELS, daysUntil, formatDate, inDays } from "../../lib/format";
import type { PillarKey } from "../../lib/types";

export function Events() {
  const events = useAsync(() => api.upcomingEvents(), []);
  return (
    <Section id="events" className="area-events" title="Nadcházející události" subtitle="Zobrazují se jen termíny ověřené z oficiálního zdroje.">
      {events.loading && !events.data && <Loading />}
      {events.error && <ErrorState message={events.error.message} onRetry={events.reload} />}
      {events.data && (
        <>
          {events.data.events.length === 0 ? (
            <p className="muted">V kalendáři nejsou žádné ověřené nadcházející události.</p>
          ) : (
            <ul className="event-list">
              {events.data.events.map((e) => {
                const days = daysUntil(e.date);
                return (
                  <li key={`${e.event}-${e.date}`} className="event">
                    <div className="event-date">
                      <strong>{formatDate(e.date)}</strong>
                      <span className="muted small">{inDays(days)}</span>
                    </div>
                    <div className="event-body">
                      <div>
                        <strong>{e.event}</strong> <span className="tag tag-warn">{e.importance} význam</span>
                      </div>
                      <div className="muted small">
                        Čas: {e.time ?? "zdrojový kalendář ho neuvádí"} · {e.instruments.join(", ")} · pilíř{" "}
                        {PILLAR_LABELS[e.factor as PillarKey] ?? e.factor}
                      </div>
                      <div className="muted small">{e.importance_basis}</div>
                      <div className="small">
                        <ExternalLink href={e.source_url}>Oficiální zdroj</ExternalLink>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          <p className="muted small">{events.data.coverage_note}</p>
        </>
      )}
    </Section>
  );
}
