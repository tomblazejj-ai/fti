import { useEffect, useState } from "react";
import { Icon } from "../../components/Icon";
import { Panel } from "../../components/Panel";
import { verdictWord } from "../../components/Tra";
import { Unavailable } from "../../components/ui";
import { formatDate, signed, usd } from "../../lib/format";
import { countdown, newsLock } from "../../lib/newsLock";
import type { Analysis, EconCalendar, HeadlineRisk, Level } from "../../lib/types";

/** Current time, ticking — for the live countdowns. */
export function useNow(ms = 15000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), ms);
    return () => window.clearInterval(id);
  }, [ms]);
  return now;
}

function when(e: { date: string; time: string | null }): string {
  return `${formatDate(e.date)}${e.time ? ` ${e.time}` : ""}`;
}

/** Funded Mind rule "Nikdy nevstupuju 2 h před červenými news" — live banner. `quiet` hides the all-clear state. */
export function NewsLockBanner({ calendar, quiet = false }: { calendar: EconCalendar | null | undefined; quiet?: boolean }) {
  const now = useNow();
  if (!calendar) return null;
  const l = newsLock(calendar.events, now, calendar.rules?.lock_hours, calendar.rules?.confirm_minutes);
  if (l.state === "lock" && l.event) {
    return (
      <div className="lock-banner is-lock" role="alert">
        <span className="lock-ico" aria-hidden="true">⛔</span>
        <div>
          <strong>
            Nevstupuj — za {countdown(l.minutes ?? 0)} vychází {l.event.name} ({l.event.time})
          </strong>
          <span>Pravidlo metodiky: 2 hodiny před červenou zprávou žádné nové obchody. Když se cena blíží k tvému vstupu, příkaz raději zruš.</span>
        </div>
      </div>
    );
  }
  if (l.state === "after" && l.event) {
    return (
      <div className="lock-banner is-after" role="status">
        <span className="lock-ico" aria-hidden="true">⏳</span>
        <div>
          <strong>
            {l.event.name} vyšla před {countdown(l.minutes ?? 0)}
          </strong>
          <span>Strategie se během zpráv rozpadá — počkej, až trh ukáže směr, a vstupuj až po potvrzení.</span>
        </div>
      </div>
    );
  }
  if (quiet) return null;
  return (
    <div className="lock-banner is-clear" role="status">
      <span className="lock-ico" aria-hidden="true">✓</span>
      <div>
        <strong>V příštích {calendar.rules?.lock_hours ?? 2} hodinách žádná červená zpráva</strong>
        <span>
          {l.next && l.minutesToNext !== null
            ? `Další: ${l.next.name} — ${when(l.next)} (za ${countdown(l.minutesToNext)}).`
            : "V kalendáři teď není žádná nadcházející červená zpráva s přesným časem."}
        </span>
      </div>
    </div>
  );
}

const LEVEL_CLASS = ["lvl-0", "lvl-1", "lvl-2"];

/** Headline risk: unexpected news outside the calendar + the weekend rule. */
export function HeadlineRiskPanel({ h }: { h: HeadlineRisk | null | undefined }) {
  return (
    <Panel title="Headline risk" tag="mimo kalendář" icon="bolt" note={h ? `posledních ${h.hours} h` : undefined}>
      {!h ? (
        <Unavailable>Headline risk se spočítá při příští aktualizaci.</Unavailable>
      ) : (
        <div className="hr">
          <div className={`hr-level ${LEVEL_CLASS[h.level]}`}>
            <span className="hr-dot" aria-hidden="true" />
            Riziko nečekaných zpráv: <strong>{h.word}</strong>
          </div>
          {h.spike && (
            <p className="hr-alert">
              Neobvykle velká svíčka M15 ({new Date(h.spike.time).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}): rozpětí{" "}
              {usd(h.spike.range)} je {String(h.spike.factor).replace(".", ",")}× víc než obvykle, směr {h.spike.direction === "up" ? "nahoru" : "dolů"}. Trh
              na něco reaguje — nepanikař a počkej na uklidnění.
            </p>
          )}
          {h.weekend && (
            <p className="hr-alert is-weekend">
              <Icon name="clock" size={15} /> {h.weekend.text} Uzavření za {countdown(h.weekend.hours * 60)}.
            </p>
          )}
          {h.items.length ? (
            <ul className="hr-list">
              {h.items.map((i) => (
                <li key={i.url}>
                  <span className="hr-topic">{i.topic}</span>
                  <a href={i.url} target="_blank" rel="noreferrer">{i.title}</a>
                  <span className="muted small">
                    {i.source} · {new Date(i.published_at).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}
                    {i.translated ? " · strojový překlad" : ""}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted small">Ve zprávách za posledních {h.hours} hodin nic, co by vypadalo jako nečekaný šok.</p>
          )}
          <ul className="hr-advice small">
            {h.advice.map((a) => <li key={a}>{a}</li>)}
          </ul>
          {h.note && <p className="muted small">{h.note}</p>}
        </div>
      )}
    </Panel>
  );
}

type StepState = "done" | "go" | "wait" | "stop";
const STEP_ICON: Record<StepState, string> = { done: "✓", go: "➜", wait: "…", stop: "!" };

function price(l: Level | null | undefined): string {
  return l?.price ? usd(l.price, 0) : l ? `${signed(l.pct, 1)} %` : "—";
}

/** The trader's daily routine from "Score overview" with today's numbers filled in. */
export function DailyRoutine({ a }: { a: Analysis }) {
  const now = useNow(30000);
  const tra = a.tra;
  const m = tra?.momentum?.xau ?? null;
  const total = tra?.xau.total ?? null;
  const bias = total === null ? null : total > 0 ? "long" : total < 0 ? "short" : "flat";
  const lock = a.calendar ? newsLock(a.calendar.events, now, a.calendar.rules?.lock_hours, a.calendar.rules?.confirm_minutes) : null;
  const sup = a.verdict.support;
  const res = a.verdict.resistance;
  const weekend = a.headline_risk?.weekend ?? null;
  const d24 = m?.changes["24h"];

  const steps: { title: string; text: string; state: StepState }[] = [
    {
      title: "Ranní kontrola skóre",
      text: tra
        ? `XAU/USD ${signed(tra.xau.total, 0)} (${verdictWord(tra.xau)})${d24 !== null && d24 !== undefined ? `, za 24 h ${signed(d24, 0)}` : ""}.`
        : "Skóre zatím není spočítané.",
      state: tra ? "done" : "wait",
    },
    {
      title: "Změnilo se skóre o 2 a víc bodů?",
      text: m?.idea ? m.idea.text : "Ne — nový obchodní nápad zatím není. Během dne sleduj, jestli se skóre pohne.",
      state: m?.idea ? "go" : "wait",
    },
    {
      title: "Zóny ve směru biasu",
      text:
        bias === "long"
          ? `Bias je býčí → v TradingView hledej demand zóny pro nákup. Nejbližší support ${price(sup)}.`
          : bias === "short"
            ? `Bias je medvědí → v TradingView hledej supply zóny pro prodej. Nejbližší rezistence ${price(res)}.`
            : "Skóre je neutrální — bez jasného biasu nové zóny nehledej.",
      state: bias === "long" || bias === "short" ? "go" : "wait",
    },
    {
      title: "Cíl",
      text:
        bias === "long"
          ? `Další zóna nad cenou${res ? ` — rezistence ${price(res)}` : ""}.`
          : bias === "short"
            ? `Další zóna pod cenou${sup ? ` — support ${price(sup)}` : ""}.`
            : "Až bude bias, cílem je nejbližší zóna ve směru obchodu.",
      state: bias === "long" || bias === "short" ? "go" : "wait",
    },
    {
      title: "Vstup a stop-loss",
      text:
        lock?.state === "lock" && lock.event
          ? `Teď ne: za ${countdown(lock.minutes ?? 0)} vychází ${lock.event.name}. Pravidlo 2 hodin před červenou zprávou.`
          : lock?.state === "after" && lock.event
            ? `${lock.event.name} právě vyšla — vstupuj až po potvrzení směru. Pak pullback do zóny, SL za zónu.`
            : "Počkej na menší pullback do zóny, stop-loss dej za zónu. Vstup podle své technické strategie.",
      state: lock?.state === "lock" ? "stop" : lock?.state === "after" ? "wait" : "go",
    },
    {
      title: "Nech obchod běžet",
      text: weekend ? `${weekend.text}` : "Důvěřuj procesu. Pozice přes víkend a přes velké události nedrž.",
      state: weekend ? "stop" : "done",
    },
  ];

  return (
    <Panel title="Denní rutina" tag="podle metodiky" icon="target">
      <ol className="routine">
        {steps.map((s, i) => (
          <li key={s.title} className={`st-${s.state}`}>
            <span className="routine-num" aria-hidden="true">{STEP_ICON[s.state] === "✓" ? "✓" : i + 1}</span>
            <div>
              <strong>{s.title}</strong>
              <p className="small">{s.text}</p>
            </div>
          </li>
        ))}
      </ol>
    </Panel>
  );
}
