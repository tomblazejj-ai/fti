import { useMemo, useState, type CSSProperties } from "react";
import { Icon } from "../components/Icon";
import { Empty, ErrorState, Pills, Skeleton } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { useNow } from "../hooks/useNow";
import { api } from "../lib/api";
import { countdown } from "../lib/format";
import type { CalendarItem } from "../lib/types";

const CURRENCIES = ["USD", "EUR", "GBP", "JPY"] as const;
const DAY = ["Neděle", "Pondělí", "Úterý", "Středa", "Čtvrtek", "Pátek", "Sobota"];
const IMPACT = ["svátek", "nízký dopad", "střední dopad", "vysoký dopad"];
type Impact = "all" | "mid" | "high";
const MIN: Record<Impact, number> = { all: 0, mid: 2, high: 3 };

function dayKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Economic calendar of all four currencies, impact in colour, times in our time zone. */
export function CalendarPage() {
  const data = useAsync(() => api.calendar(), []);
  const [cur, setCur] = useState<string>("all");
  const [impact, setImpact] = useState<Impact>("mid");
  const now = useNow(30000);
  const events = useMemo(() => data.data?.events ?? [], [data.data]);
  if (data.error && !data.data) return <main className="page"><ErrorState message={data.error.message} onRetry={data.reload} /></main>;
  if (!data.data) return <main className="page"><div className="card"><Skeleton rows={6} /></div></main>;

  const shown = events.filter((e) => (cur === "all" || e.currency === cur) && e.impact >= MIN[impact]);
  const byDay = new Map<string, CalendarItem[]>();
  for (const e of shown) {
    const k = dayKey(new Date(e.datetime));
    byDay.set(k, [...(byDay.get(k) ?? []), e]);
  }
  const next = events.find((e) => e.impact === 3 && e.timed !== false && new Date(e.datetime).getTime() > now.getTime());
  const nextMin = next ? (new Date(next.datetime).getTime() - now.getTime()) / 60000 : null;
  const today = dayKey(now);

  return (
    <main className="page">
      <header className="page-head rise">
        <h1>Kalendář</h1>
        <p>Ekonomické zprávy USD, EUR, GBP a JPY · časy v našem čase · červená = vysoký dopad</p>
      </header>
      {next && nextMin !== null && (
        <div className={`nextup rise${nextMin <= 120 ? " is-soon" : ""}`} style={{ "--i": 1 } as CSSProperties}>
          <span className="nextup-ico"><Icon name="clock" size={20} /></span>
          <span className="nextup-body">
            <small>Další zpráva s vysokým dopadem</small>
            <strong>{next.title_cs} ({next.currency})</strong>
          </span>
          <span className="nextup-count">za {countdown(nextMin)}</span>
        </div>
      )}
      <div className="filters rise" style={{ "--i": 2 } as CSSProperties}>
        <Pills label="Měna" options={[{ value: "all", label: "Vše" }, ...CURRENCIES.map((c) => ({ value: c, label: c }))]} value={cur} onChange={setCur} />
        <Pills
          label="Dopad"
          options={[
            { value: "all", label: "Vše" },
            { value: "mid", label: "Střední+" },
            { value: "high", label: "Jen vysoký" },
          ]}
          value={impact}
          onChange={setImpact}
        />
      </div>
      {byDay.size === 0 && <Empty>Pro tento filtr nic.</Empty>}
      {[...byDay.entries()].map(([k, list], di) => {
        const d = new Date(list[0].datetime);
        return (
          <section key={k} className={`card cal-day rise${k === today ? " is-today" : ""}${k < today ? " is-past" : ""}`} style={{ "--i": di + 3 } as CSSProperties}>
            <h2 className="cal-day-name">
              {DAY[d.getDay()]} {d.getDate()}. {d.getMonth() + 1}.{k === today && <span className="cal-today">dnes</span>}
            </h2>
            <ul className="cal-list">
              {list.map((e) => {
                const t = new Date(e.datetime);
                const past = t.getTime() < now.getTime();
                return (
                  <li key={`${e.datetime}-${e.currency}-${e.title_en}`} className={`cal-item imp-${e.impact}${past ? " is-past" : ""}`}>
                    <span className="cal-time">{e.timed === false ? "—" : t.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}</span>
                    <span className={`cal-cur c-${e.currency}`}>{e.currency}</span>
                    <span className="cal-title">
                      {e.title_cs}
                      {(e.forecast || e.previous) && (
                        <small>
                          {e.forecast ? `prognóza ${e.forecast}` : ""}{e.forecast && e.previous ? " · " : ""}{e.previous ? `minule ${e.previous}` : ""}
                        </small>
                      )}
                    </span>
                    <span className="cal-dot" title={IMPACT[e.impact]} aria-label={IMPACT[e.impact]} />
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
      <p className="note">Zdroje: {data.data.sources.join(" · ")}. Na další týdny jsou jen termíny centrálních bank a dat USA; ostatní doplní kalendář v neděli.</p>
    </main>
  );
}
