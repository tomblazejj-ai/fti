import { useMemo, useState } from "react";
import { Pills } from "../components/Panel";
import { ErrorState, Loading } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { countdown, newsLock } from "../lib/newsLock";
import type { CalendarEvent, CalendarItem } from "../lib/types";
import { useNow } from "./detail/Methodology";

const CURRENCIES = ["USD", "EUR", "GBP", "JPY"] as const;
const DAY = ["Neděle", "Pondělí", "Úterý", "Středa", "Čtvrtek", "Pátek", "Sobota"];
type Impact = "all" | "mid" | "high";
const MIN: Record<Impact, number> = { all: 0, mid: 2, high: 3 };

function local(iso: string): Date {
  return new Date(iso);
}

function dayKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Economic calendar of all four currencies — impact colours like the trading terminals. */
export function CalendarPage() {
  const data = useAsync(() => api.calendar(), []);
  const [cur, setCur] = useState<string>("all");
  const [impact, setImpact] = useState<Impact>("mid");
  const now = useNow(30000);
  const events = useMemo(() => data.data?.events ?? [], [data.data]);
  if (data.error && !data.data) return <main className="page mi-page"><ErrorState message={data.error.message} onRetry={data.reload} /></main>;
  if (!data.data) return <main className="page mi-page"><Loading label="Načítám kalendář…" /></main>;

  const shown = events.filter((e) => (cur === "all" || e.currency === cur) && e.impact >= MIN[impact]);
  const byDay = new Map<string, CalendarItem[]>();
  for (const e of shown) {
    const k = dayKey(local(e.datetime));
    byDay.set(k, [...(byDay.get(k) ?? []), e]);
  }
  // the 2-hour rule over every red release of the four currencies
  const asEvents: CalendarEvent[] = events
    .filter((e) => e.impact === 3 && e.timed !== false)
    .map((e) => ({ date: e.datetime.slice(0, 10), time: null, datetime: e.datetime, name: `${e.title_cs} (${e.currency})`, original: e.title_en,
                   importance: 3, impact: "", previous: e.previous, forecast: e.forecast, source: e.source, past: false }));
  const lock = newsLock(asEvents, now);
  const today = dayKey(now);

  return (
    <main className="page mi-page">
      <header className="cal-head">
        <div>
          <h1 className="mi-title">KALENDÁŘ <span>/ ekonomické události</span></h1>
          <p className="mi-sub">USD, EUR, GBP a JPY · časy v našem čase · červená = vysoký dopad</p>
        </div>
      </header>
      {lock.state !== "clear" && lock.event ? (
        <div className={`lock-banner ${lock.state === "lock" ? "is-lock" : "is-after"}`} role="alert">
          <span className="lock-ico" aria-hidden="true">{lock.state === "lock" ? "⛔" : "⏳"}</span>
          <div>
            <strong>
              {lock.state === "lock" ? `Nevstupuj — za ${countdown(lock.minutes ?? 0)} vychází ${lock.event.name}` : `${lock.event.name} právě vyšla`}
            </strong>
            <span>{lock.state === "lock" ? "2 hodiny před červenou zprávou žádné nové obchody." : "Počkej na potvrzení směru."}</span>
          </div>
        </div>
      ) : (
        lock.next &&
        lock.minutesToNext !== null && (
          <div className="lock-banner is-clear">
            <span className="lock-ico" aria-hidden="true">✓</span>
            <div>
              <strong>Další červená zpráva za {countdown(lock.minutesToNext)}</strong>
              <span>{lock.next.name}</span>
            </div>
          </div>
        )
      )}
      <div className="cal-filters">
        <Pills label="Měna" options={[{ value: "all", label: "Vše" }, ...CURRENCIES.map((c) => ({ value: c, label: c }))]} value={cur} onChange={setCur} />
        <Pills
          label="Dopad"
          options={[
            { value: "all", label: "Vše" },
            { value: "mid", label: "Střední+" },
            { value: "high", label: <span className="imp-red">Vysoký</span> },
          ]}
          value={impact}
          onChange={setImpact}
        />
      </div>
      {byDay.size === 0 && <p className="state state-unavailable">Pro tento filtr nic.</p>}
      {[...byDay.entries()].map(([k, list]) => {
        const d = local(list[0].datetime);
        return (
          <section key={k} className={`cal-day${k === today ? " is-today" : ""}${k < today ? " is-past" : ""}`}>
            <h2 className="cal-day-name">
              {DAY[d.getDay()]} {d.getDate()}. {d.getMonth() + 1}.{k === today && <span className="cal-today">dnes</span>}
            </h2>
            <ul className="cal-list">
              {list.map((e) => {
                const t = local(e.datetime);
                const past = t.getTime() < now.getTime();
                return (
                  <li key={`${e.datetime}-${e.currency}-${e.title_en}`} className={`cal-item imp-${e.impact}${past ? " is-past" : ""}`}>
                    <span className="cal-time">{e.timed === false ? "—" : t.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}</span>
                    <span className={`cal-cur c-${e.currency}`}>{e.currency}</span>
                    <span className="cal-title">
                      {e.title_cs}
                      {(e.forecast || e.previous) && (
                        <small className="muted">
                          {e.forecast ? `prognóza ${e.forecast}` : ""}{e.forecast && e.previous ? " · " : ""}{e.previous ? `minule ${e.previous}` : ""}
                        </small>
                      )}
                    </span>
                    <span className="cal-dot" title={["svátek", "nízký dopad", "střední dopad", "vysoký dopad"][e.impact]} aria-label={["svátek", "nízký dopad", "střední dopad", "vysoký dopad"][e.impact]} />
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
      <p className="mi-note muted small">Zdroje: {data.data.sources.join(" · ")}. Na další týdny jsou jen termíny centrálních bank a dat USA; ostatní doplní kalendář v neděli.</p>
    </main>
  );
}
