import { useMemo, useState } from "react";
import { Icon } from "../../components/Icon";
import { Pills } from "../../components/Panel";
import { Unavailable } from "../../components/ui";
import { daysUntil, formatDate, inDays } from "../../lib/format";
import type { CalendarEvent, EconCalendar } from "../../lib/types";
import { NewsLockBanner } from "./Methodology";

const IMP_WORD = { 3: "vysoká", 2: "střední", 1: "nízká" } as const;
type ImpactFilter = "all" | "mid" | "high";
const MIN_IMPORTANCE: Record<ImpactFilter, number> = { all: 1, mid: 2, high: 3 };

function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Economic calendar for the instrument: day navigator like a trading terminal, or the full list. */
export function CalendarTable({ calendar, full = false }: { calendar: EconCalendar | null | undefined; full?: boolean }) {
  const compact = !full;
  const days = useMemo(() => [...new Set((calendar?.events ?? []).map((e) => e.date))].sort(), [calendar]);
  const startIdx = Math.max(0, days.findIndex((d) => d >= todayIso()));
  const [idx, setIdx] = useState<number | null>(null);
  const [mode, setMode] = useState<"day" | "all">(full ? "all" : "day");
  const [open, setOpen] = useState<string | null>(null);
  const [impact, setImpact] = useState<ImpactFilter>("all");

  if (!calendar) return <Unavailable>Kalendář se spočítá při příští aktualizaci dat.</Unavailable>;
  if (!days.length) return <Unavailable>V příštích týdnech žádná ověřená důležitá událost.</Unavailable>;
  const i = Math.min(idx ?? (startIdx === -1 ? days.length - 1 : startIdx), days.length - 1);
  const day = days[i];
  const events = (mode === "day" ? calendar.events.filter((e) => e.date === day) : calendar.events.filter((e) => !e.past)).filter(
    (e) => e.importance >= MIN_IMPORTANCE[impact],
  );

  return (
    <div className="calt">
      {full && <NewsLockBanner calendar={calendar} />}
      {full && (
        <div className="calt-filter">
          <span className="muted small">Dopad:</span>
          <Pills
            label="Filtr podle dopadu"
            options={[
              { value: "all", label: "Vše" },
              { value: "mid", label: "Střední a vysoký" },
              { value: "high", label: <span className="imp-red">Jen červené</span> },
            ]}
            value={impact}
            onChange={setImpact}
          />
          <span className="muted small">Metodika: obchodně rozhodují hlavně červené (vysoký dopad).</span>
        </div>
      )}
      <div className="calt-nav">
        {mode === "day" ? (
          <div className="day-nav">
            <button type="button" className="icon-btn" onClick={() => setIdx(Math.max(0, i - 1))} disabled={i === 0} aria-label="Předchozí den s událostí">
              <Icon name="chevronLeft" />
            </button>
            <span className="day-nav-label">
              {formatDate(day)} <span className="muted small">· {inDays(daysUntil(day))}</span>
            </span>
            <button type="button" className="icon-btn" onClick={() => setIdx(Math.min(days.length - 1, i + 1))} disabled={i === days.length - 1} aria-label="Další den s událostí">
              <Icon name="chevronRight" />
            </button>
          </div>
        ) : (
          <span className="muted small">Všechny nadcházející události</span>
        )}
        <Pills label="Zobrazení kalendáře" options={[{ value: "day", label: "Den" }, { value: "all", label: "Vše" }]} value={mode} onChange={setMode} />
      </div>
      <table className="calt-table">
        <thead>
          <tr>
            <th>Čas</th>
            <th>Měna</th>
            <th>Událost</th>
            {!compact && <th className="num">Poslední hodnota</th>}
            {!compact && <th className="num">Prognóza</th>}
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <Row key={`${e.date}-${e.key ?? e.name}`} e={e} showDate={mode === "all"} compact={compact} open={open === `${e.date}-${e.name}`}
                 next={calendar.events.find((n) => !n.past && n.key === e.key && (n.date > e.date || (e.past && n.date >= e.date))) ?? null}
                 onToggle={() => setOpen(open === `${e.date}-${e.name}` ? null : `${e.date}-${e.name}`)} />
          ))}
          {!events.length && (
            <tr>
              <td colSpan={compact ? 3 : 5} className="muted small">Pro tento filtr tu nic není.</td>
            </tr>
          )}
        </tbody>
      </table>
      <p className="calt-note muted small">
        Časy v našem čase (Praha). Kliknutím na událost uvidíš, jak obvykle pohne zlatem. {calendar.notes[calendar.notes.length - 1]}
      </p>
    </div>
  );
}

function Row({ e, showDate, compact, open, next, onToggle }: {
  e: CalendarEvent;
  showDate: boolean;
  compact: boolean;
  open: boolean;
  next: CalendarEvent | null;
  onToggle: () => void;
}) {
  return (
    <>
      <tr className={`calt-row imp-${e.importance}${e.past ? " is-past" : ""}${open ? " is-open" : ""}`} onClick={onToggle}>
        <td className="calt-time">
          {showDate && <span className="calt-date">{formatDate(e.date)}</span>}
          {e.time ?? <span className="muted small">—</span>}
        </td>
        <td><span className="cur">USD</span></td>
        <td>
          <span className="calt-name">
            <span className="imp-bar" aria-label={`důležitost ${IMP_WORD[e.importance]}`} title={`důležitost ${IMP_WORD[e.importance]}`}>
              {[1, 2, 3].map((k) => <span key={k} className={k <= e.importance ? "on" : ""} />)}
            </span>
            <button type="button" className="calt-btn" aria-expanded={open}>{e.name}</button>
          </span>
          {compact && e.previous && <span className="calt-prev muted small">Poslední: {e.previous}</span>}
        </td>
        {!compact && <td className="num small">{e.previous ?? <span className="muted">—</span>}</td>}
        {!compact && <td className="num muted small" title="Konsenzus trhu není zdarma k dispozici">n/a</td>}
      </tr>
      {open && (
        <tr className="calt-detail">
          <td colSpan={compact ? 3 : 5}>
            <p>{e.impact}</p>
            {e.up_if && (
              <p className="calt-sides">
                <span className="tone-bullish">▲ zlato nahoru, když {e.up_if}</span>
                <span className="tone-bearish">▼ zlato dolů, když {e.down_if}</span>
              </p>
            )}
            {e.detail && <EventDetailBox e={e} next={next} />}
            <p className="muted small">Zdroj: {e.source}{e.original && ` · ${e.original}`}</p>
          </td>
        </tr>
      )}
    </>
  );
}

/** Event detail like a trading terminal: how often, why it matters, usual effect, history of values. */
function EventDetailBox({ e, next }: { e: CalendarEvent; next: CalendarEvent | null }) {
  const d = e.detail!;
  const max = Math.max(...d.history.map((h) => Math.abs(h.value)), 0.0001);
  return (
    <div className="evd">
      <dl className="evd-kv small">
        <div>
          <dt>Jak často</dt>
          <dd>{d.freq}</dd>
        </div>
        <div>
          <dt>Proč to trh sleduje</dt>
          <dd>{d.why}</dd>
        </div>
        <div>
          <dt>Obvyklý vliv na dolar</dt>
          <dd>{d.usd}</dd>
        </div>
        {next && (
          <div>
            <dt>Příští zveřejnění</dt>
            <dd>
              {formatDate(next.date)}
              {next.time ? ` v ${next.time}` : ""}
            </dd>
          </div>
        )}
      </dl>
      {d.history.length > 0 && (
        <div className="evd-hist">
          <span className="muted small">
            {d.history_label} — posledních {d.history.length} hodnot
          </span>
          <ul>
            {d.history.map((h) => (
              <li key={h.period}>
                <span className="evd-period">{h.period}</span>
                <span className="evd-bar">
                  <i className={h.value < 0 ? "neg" : "pos"} style={{ width: `${Math.max(4, (Math.abs(h.value) / max) * 100)}%` }} />
                </span>
                <strong>{h.text}</strong>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="small evd-links">
        {d.link && (
          <a href={d.link} target="_blank" rel="noreferrer">
            Oficiální stránka zveřejnění
          </a>
        )}
        {d.series_url && (
          <a href={d.series_url} target="_blank" rel="noreferrer">
            Data na FRED ({d.series})
          </a>
        )}
      </p>
    </div>
  );
}
