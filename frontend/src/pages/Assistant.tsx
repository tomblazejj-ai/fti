import { useCallback, useEffect, useRef, useState } from "react";
import { CandleChart, type ChartZone } from "../components/CandleChart";
import { GoldMark, Icon, type IconName } from "../components/Icon";
import { ErrorState, Loading } from "../components/ui";
import { useAsync, useInterval } from "../hooks/useAsync";
import { useTickers } from "../hooks/useTickers";
import { ApiError, api } from "../lib/api";
import { formatDateTime, isStale, signed, usd } from "../lib/format";
import { countdown, newsLock } from "../lib/newsLock";
import type { Analysis, AssistantView, SetupCheck, TradeSetup, WeeklyPlan, Zone } from "../lib/types";
import { useNow } from "./detail/Methodology";

const ACTION = {
  short: { word: "SHORT", sub: "hledej prodej", tone: "bear", icon: "arrowDown" as IconName },
  long: { word: "LONG", sub: "hledej nákup", tone: "bull", icon: "arrowUp" as IconName },
  wait: { word: "ČEKAT", sub: "teď nic neotevírej", tone: "flat", icon: "clock" as IconName },
};
const DAY = ["Po", "Út", "St", "Čt", "Pá"];

function px(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : usd(v, 0);
}

function zoneRange(z: Zone): string {
  return `${z.lo.toLocaleString("cs-CZ", { maximumFractionDigits: 0 })}–${px(z.hi)}`;
}

function minus(n: number): string {
  return n > 0 ? `+${n}` : n < 0 ? `−${Math.abs(n)}` : "0";
}

/** The home screen: what to do now, why, and the plan — the Funded Mind swing checklist on today's data. */
export function Assistant() {
  const analysis = useAsync(() => api.analysis("XAUUSD"), []);
  const status = useAsync(() => api.status(), []);
  const reload = useCallback(() => {
    analysis.reload();
    status.reload();
  }, [analysis.reload, status.reload]);
  useInterval(reload, 120000);

  if (analysis.error && !analysis.data) {
    const missing = analysis.error instanceof ApiError && analysis.error.status === 404;
    return (
      <main className="page as-page">
        {missing ? (
          <p className="state state-unavailable">Pomocník se sestaví při první aktualizaci dat — chvíli počkej (první výpočet trvá asi 2 minuty).</p>
        ) : (
          <ErrorState message={analysis.error.message} onRetry={reload} />
        )}
      </main>
    );
  }
  if (!analysis.data) {
    return (
      <main className="page as-page">
        <Loading label="Skládám dnešní plán…" />
      </main>
    );
  }
  const a = analysis.data;
  const stale = isStale(a.computed_at, status.data?.refresh_interval_minutes ?? 30);
  return (
    <main className="page as-page">
      <Hero a={a} stale={stale} />
      {a.setup ? <Setups s={a.setup} a={a} /> : <p className="state state-unavailable">Zóny se spočítají, až budou k dispozici denní a týdenní svíčky zlata.</p>}
      <ZoneChart a={a} />
      <div className="as-row">
        {a.weekly && <Week w={a.weekly} a={a} />}
        <Tiles a={a} />
      </div>
      <p className="as-foot muted small">
        {a.setup?.note} Zóny: {a.zones?.method} <a href="#/">Přehled všech trhů</a>
      </p>
    </main>
  );
}

function useCountUp(value: number, ms = 700): number {
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  useEffect(() => {
    const a = from.current;
    if (!a || typeof requestAnimationFrame !== "function") {  // first real value: no count from zero
      from.current = value;
      setShown(value);
      return;
    }
    const start = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / ms);
      setShown(a + (value - a) * (1 - (1 - k) ** 3));
      if (k < 1) raf = requestAnimationFrame(tick);
      else from.current = value;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, ms]);
  return shown;
}

function Hero({ a, stale }: { a: Analysis; stale: boolean }) {
  const t = useTickers();
  const now = useNow(15000);
  const s = a.setup;
  const act = ACTION[s?.action ?? "wait"];
  const live = t?.live.find((q) => q.symbol === "PAXGUSD");
  const open = t?.market?.open ?? true;
  const price = open ? (live?.price ?? a.mtf?.price ?? null) : (t?.weekend?.spot_close ?? a.mtf?.price ?? null);
  const shownPrice = useCountUp(price ?? 0);
  const day = live?.change_pct ?? a.technical?.changes["1d"] ?? null;
  const tra = a.tra?.xau;
  const m = a.tra?.momentum?.xau;
  const lock = a.calendar ? newsLock(a.calendar.events, now, a.calendar.rules?.lock_hours, a.calendar.rules?.confirm_minutes) : null;
  const primary = s?.primary ? s.setups[s.primary] : null;
  return (
    <section className={`as-hero tone-${act.tone}`} aria-labelledby="as-answer">
      <div className="as-hero-glow" aria-hidden="true" />
      <div className="as-hero-main">
        <div className="as-hero-top">
          <span className="as-coin" aria-hidden="true"><GoldMark size={22} /></span>
          <span className="as-sym">XAU/USD</span>
          <span className={`as-action as-${act.tone}`}>
            <Icon name={act.icon} size={16} /> {act.word}
            <small>{act.sub}</small>
          </span>
          {stale && <span className="as-stale">data se obnovují…</span>}
        </div>
        <h1 id="as-answer" className="as-answer">{s?.headline ?? "Pomocník čeká na první výpočet."}</h1>
        {primary && <p className="as-where">{primary.where} {primary.verdict}</p>}
        {m?.idea && (
          <p className={`as-idea is-${m.idea.direction}`}>
            <Icon name="sparkle" size={15} /> <strong>Obchodní nápad:</strong> skóre za 24 h {minus(m.idea.from)} → {minus(m.idea.to)} — sentiment se
            posouvá {m.idea.direction === "up" ? "nahoru" : "dolů"}. Hledej zóny ve směru nového biasu.
          </p>
        )}
        {s?.timing.map((x) => (
          <p key={x.key} className={`as-timing st-${x.state}`}>
            <Icon name={x.key === "weekend" ? "calendar" : "bolt"} size={15} /> {x.text}
          </p>
        ))}
      </div>
      <div className="as-hero-side">
        <div className="as-kpi">
          <span className="as-kpi-label">Cena</span>
          <strong className="as-kpi-big">{price === null ? "—" : usd(shownPrice)}</strong>
          {day !== null && (
            <span className={day > 0 ? "pos" : day < 0 ? "neg" : ""}>
              {day > 0 ? "▲" : day < 0 ? "▼" : "◆"} {signed(day, 2)} % {open ? "dnes" : "· trh zavřen"}
            </span>
          )}
        </div>
        {tra && (
          <a className="as-kpi as-kpi-link" href="#/instrument/XAUUSD">
            <span className="as-kpi-label">Skóre fundamentu</span>
            <strong className={`as-kpi-big ${tra.total > 0 ? "pos" : tra.total < 0 ? "neg" : ""}`}>{minus(tra.total)}</strong>
            <span className="small">
              {tra.strength}{tra.strength ? tra.word.toLowerCase() : tra.word}
              {m?.changes["24h"] !== null && m?.changes["24h"] !== undefined && ` · 24 h ${minus(m.changes["24h"])}`}
            </span>
          </a>
        )}
        <div className={`as-kpi as-news st-${lock?.state ?? "clear"}`}>
          <span className="as-kpi-label">Červené zprávy</span>
          {lock?.state === "lock" && lock.event ? (
            <>
              <strong className="as-kpi-mid neg">za {countdown(lock.minutes ?? 0)}</strong>
              <span className="small">{lock.event.name} — nevstupuj</span>
            </>
          ) : lock?.state === "after" && lock.event ? (
            <>
              <strong className="as-kpi-mid">právě vyšla</strong>
              <span className="small">{lock.event.name} — čekej na potvrzení</span>
            </>
          ) : lock?.next && lock.minutesToNext !== null ? (
            <>
              <strong className="as-kpi-mid">za {countdown(lock.minutesToNext)}</strong>
              <span className="small">{lock.next.name}</span>
            </>
          ) : (
            <strong className="as-kpi-mid">nic v kalendáři</strong>
          )}
        </div>
      </div>
    </section>
  );
}

const STATE_ICON = { ok: "✓", bad: "✕", na: "–" } as const;

function Ring({ s }: { s: TradeSetup }) {
  const r = 46;
  const c = 2 * Math.PI * r;
  const n = s.checks.length;
  const seg = c / n;
  return (
    <svg className="as-ring" viewBox="0 0 120 120" role="img" aria-label={`Potvrzení ${s.ok} z ${n}, setup ${s.grade}`}>
      <circle cx="60" cy="60" r={r} className="as-ring-track" />
      {s.checks.map((ch, i) => (
        <circle
          key={ch.key}
          cx="60"
          cy="60"
          r={r}
          className={`as-ring-seg st-${ch.state}`}
          strokeDasharray={`${(seg - 5).toFixed(2)} ${(c - seg + 5).toFixed(2)}`}
          strokeDashoffset={(-i * seg).toFixed(2)}
          transform="rotate(-90 60 60)"
          style={{ animationDelay: `${i * 0.08}s` }}
        />
      ))}
      <text x="60" y="58" textAnchor="middle" className="as-ring-grade">{s.grade === "skip" ? "✕" : s.grade}</text>
      <text x="60" y="78" textAnchor="middle" className="as-ring-sub">{s.ok} z {n}</text>
    </svg>
  );
}

function Setups({ s, a }: { s: AssistantView; a: Analysis }) {
  const sides = (["short", "long"] as const).filter((k) => s.setups[k]);
  const [side, setSide] = useState<"long" | "short">(s.primary ?? sides[0] ?? "short");
  const cur = s.setups[side] ?? s.setups[sides[0]];
  if (!cur) return null;
  return (
    <section className="as-setup" aria-label="Checklist a plán obchodu">
      <div className="as-card as-check">
        <header className="as-card-head">
          <div>
            <span className="as-eyebrow">Denní kontrola · 10 minut</span>
            <h2>Checklist setupu</h2>
          </div>
          <div className="as-switch" role="group" aria-label="Směr obchodu">
            {sides.map((k) => {
              const su = s.setups[k]!;
              return (
                <button key={k} type="button" className={`as-switch-btn as-${k === "short" ? "bear" : "bull"}${k === cur.side ? " is-on" : ""}`}
                        aria-pressed={k === cur.side} onClick={() => setSide(k)}>
                  {k === "short" ? "SHORT" : "LONG"} <small>{su.ok}/{su.total_checks} · {su.grade === "skip" ? "nech být" : su.grade}</small>
                </button>
              );
            })}
          </div>
        </header>
        <div className="as-check-body">
          <Ring s={cur} />
          <ol className="as-list">
            {cur.checks.map((c, i) => <CheckRow key={c.key} c={c} i={i} />)}
          </ol>
        </div>
        <p className={`as-verdict g-${cur.grade === "A+" || cur.grade === "A" ? "a" : cur.grade === "B" ? "b" : "c"}`}>{cur.verdict}</p>
      </div>
      <Plan s={cur} a={a} />
    </section>
  );
}

function CheckRow({ c, i }: { c: SetupCheck; i: number }) {
  const [open, setOpen] = useState(false);
  const short = c.text.split(/(?<=\.)\s/)[0];
  const more = c.text.length > short.length;
  return (
    <li className={`as-item st-${c.state}`} style={{ animationDelay: `${i * 0.05}s` }}>
      <span className="as-item-ico" aria-label={c.state === "ok" ? "splněno" : c.state === "bad" ? "nesplněno" : "neutrální"}>{STATE_ICON[c.state]}</span>
      <div>
        <strong>{c.label}</strong>
        <p className="small">
          {open ? c.text : short}
          {more && (
            <button type="button" className="as-more" onClick={() => setOpen(!open)} aria-expanded={open}>
              {open ? "méně" : "více"}
            </button>
          )}
        </p>
      </div>
    </li>
  );
}

function Plan({ s, a }: { s: TradeSetup; a: Analysis }) {
  const p = s.plan;
  const price = a.zones?.price ?? null;
  const pts = [p.stop, p.entry, s.zone.lo, s.zone.hi, ...(p.target ? [p.target] : []), ...(price ? [price] : [])];
  const lo = Math.min(...pts);
  const hi = Math.max(...pts);
  const pad = (hi - lo) * 0.08 || 1;
  const H = 260;
  const y = (v: number) => 10 + (1 - (v - (lo - pad)) / (hi - lo + 2 * pad)) * (H - 20);
  const long = s.side === "long";
  const zoneTone = long ? "bull" : "bear";
  return (
    <div className="as-card as-plan">
      <header className="as-card-head">
        <div>
          <span className="as-eyebrow">Obchodní plán podle pravidel</span>
          <h2>{long ? "Long" : "Short"} z {long ? "demand" : "supply"} zóny</h2>
        </div>
        {p.rr !== null && <span className={`as-rr ${p.rr >= 2 ? "is-good" : p.rr >= 1.5 ? "is-ok" : "is-bad"}`}>R:R {String(p.rr).replace(".", ",")}</span>}
      </header>
      <div className="as-plan-body">
        <svg className="as-ladder" viewBox={`0 0 220 ${H}`} role="img" aria-label="Cenový žebřík: cíl, vstup, zóna, stop-loss a aktuální cena">
          <rect x="60" y={y(s.zone.hi)} width="150" height={Math.max(4, y(s.zone.lo) - y(s.zone.hi))} rx="6" className={`ld-zone ld-${zoneTone}`} />
          {p.target && <Rung y={y(p.target)} label="Cíl" value={p.target} cls="ld-target" />}
          <Rung y={y(p.entry)} label="Vstup" value={p.entry} cls="ld-entry" />
          <Rung y={y(p.stop)} label="SL" value={p.stop} cls="ld-stop" />
          {price && (
            <g className="ld-now">
              <line x1="60" x2="210" y1={y(price)} y2={y(price)} />
              <circle cx="60" cy={y(price)} r="5" />
              <text x="54" y={y(price) + 4} textAnchor="end">teď</text>
            </g>
          )}
        </svg>
        <dl className="as-plan-kv">
          <div><dt>Vstup (hrana zóny)</dt><dd>{px(p.entry)}</dd></div>
          {p.poc !== null && p.poc !== p.entry && <div><dt>Přesnější vstup (POC)</dt><dd>{px(p.poc)}</dd></div>}
          <div><dt>Stop-loss (za zónou)</dt><dd className="neg">{px(p.stop)}</dd></div>
          <div><dt>Cíl (protější zóna)</dt><dd className="pos">{px(p.target)}</dd></div>
          <div><dt>Riziko na 1 unci</dt><dd>{px(p.risk_usd)}</dd></div>
          <div><dt>Zóna</dt><dd>{zoneRange(s.zone)} <span className="muted small">{s.zone.tf === "W1" ? "týdenní" : "denní"}{s.zone.fresh ? " · čerstvá" : ` · testovaná ${s.zone.touches}×`}</span></dd></div>
        </dl>
      </div>
      <p className="muted small">{s.where}</p>
    </div>
  );
}

function Rung({ y, label, value, cls }: { y: number; label: string; value: number; cls: string }) {
  return (
    <g className={cls}>
      <line x1="60" x2="210" y1={y} y2={y} />
      <text x="54" y={y + 4} textAnchor="end">{label}</text>
      <text x="206" y={y - 5} textAnchor="end" className="ld-val">{px(value)}</text>
    </g>
  );
}

function ZoneChart({ a }: { a: Analysis }) {
  const z = a.zones;
  const s = a.setup;
  const cur = s?.primary ? s.setups[s.primary] : null;
  const list: ChartZone[] = [];
  for (const tf of ["W1", "D1"] as const) {
    for (const kind of ["demand", "supply"] as const) {
      for (const zone of (z?.tf[tf]?.[kind] ?? []).slice(0, 2)) {
        if (zone.distance_pct <= 8) list.push({ lo: zone.lo, hi: zone.hi, kind, tf, formed: zone.formed });
      }
    }
  }
  return (
    <section className="as-card as-chart" aria-label="Graf se zónami">
      <header className="as-card-head">
        <div>
          <span className="as-eyebrow">Týdenní a denní zóny</span>
          <h2>Graf se zónami a plánem</h2>
        </div>
        <span className="as-legend small">
          <i className="lg-zone-d" /> demand <i className="lg-zone-s" /> supply <i className="lg-zone-w" /> týdenní
        </span>
      </header>
      <CandleChart code="XAUUSD" initialTf="D1" zones={list} unit="ceny v USD"
                   plan={cur ? { entry: cur.plan.entry, stop: cur.plan.stop, target: cur.plan.target, side: cur.side } : null} />
    </section>
  );
}

function Week({ w, a }: { w: WeeklyPlan; a: Analysis }) {
  const today = new Date();
  const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  return (
    <section className="as-card as-week" aria-label={w.title}>
      <header className="as-card-head">
        <div>
          <span className="as-eyebrow">Víkendová příprava</span>
          <h2>{w.title}</h2>
        </div>
        <a className="link-more" href="#/instrument/XAUUSD/calendar">Kalendář <Icon name="chevronRight" size={14} /></a>
      </header>
      <div className="as-days">
        {w.days.map((d, i) => (
          <div key={d.date} className={`as-day${d.date === todayIso ? " is-today" : ""}`}>
            <span className="as-day-name">{DAY[i]} <small>{Number(d.date.slice(8))}. {Number(d.date.slice(5, 7))}.</small></span>
            {d.events.length ? (
              d.events.map((e) => (
                <span key={e.name} className={`as-ev imp-${e.importance}${e.past ? " is-past" : ""}`} title={e.name}>
                  {e.time ?? ""} {e.name.replace(" (USA)", "")}
                </span>
              ))
            ) : (
              <span className="as-ev-none">klid</span>
            )}
          </div>
        ))}
      </div>
      <ul className="as-lines">
        {w.lines.map((l) => <li key={l}>{l}</li>)}
      </ul>
      {a.setup?.other_text && <p className="muted small">{a.setup.other_text}</p>}
    </section>
  );
}

function Tiles({ a }: { a: Analysis }) {
  const tra = a.tra?.xau;
  const cot = a.cot;
  const sd = a.season_daily?.gold;
  const d = a.dxy;
  const h = a.headline_risk;
  const cotScore = tra?.components.find((c) => c.key === "cot")?.score ?? null;
  const tiles: { href: string; icon: IconName; label: string; value: string; sub: string; tone: string }[] = [
    {
      href: "#/instrument/XAUUSD", icon: "layers", label: "Fundament", value: tra ? minus(tra.total) : "—",
      sub: tra ? `${tra.word} · 11 kategorií` : "spočítá se", tone: tra ? (tra.total > 0 ? "pos" : tra.total < 0 ? "neg" : "") : "",
    },
    {
      href: "#/instrument/XAUUSD/cot", icon: "users", label: "COT", value: cotScore === null ? "—" : minus(cotScore),
      sub: cot?.long_short ? `fondy ${Math.round(cot.long_short.long_pct)} % long` : "pozice fondů", tone: cotScore ? (cotScore > 0 ? "pos" : "neg") : "",
    },
    {
      href: "#/instrument/XAUUSD/season", icon: "sun", label: "Sezónnost",
      value: sd?.next30 ? `${sd.next30.up}/${sd.next30.n}` : "—",
      sub: sd?.next30 ? `let růst v příštích 30 dnech` : "", tone: sd?.lean ? (sd.lean > 0 ? "pos" : "neg") : "",
    },
    {
      href: "#/instrument/XAUUSD/dxy", icon: "chart", label: "Dolar (DXY)",
      value: d?.price ? d.price.toLocaleString("cs-CZ", { maximumFractionDigits: 2 }) : "—",
      sub: d?.trends.swing ? `swing ${d.trends.swing.word.toLowerCase()}` : "", tone: d?.trends.swing?.lean === "up" ? "neg" : d?.trends.swing?.lean === "down" ? "pos" : "",
    },
    {
      href: "#/instrument/XAUUSD", icon: "bolt", label: "Headline risk", value: h ? h.word : "—",
      sub: h?.weekend ? "blíží se víkend" : `zprávy za ${h?.hours ?? 12} h`, tone: h ? (h.level === 2 ? "neg" : h.level === 1 ? "warn" : "pos") : "",
    },
    {
      href: "#/instrument/XAUUSD/news", icon: "news", label: "Zprávy",
      value: a.news?.count !== undefined ? String(a.news.count) : "—", sub: "o zlatě za 3 dny", tone: "",
    },
  ];
  return (
    <section className="as-tiles" aria-label="Rychlý přehled">
      {tiles.map((t) => (
        <a key={t.label} href={t.href} className="as-tile">
          <span className="as-tile-ico"><Icon name={t.icon} size={17} /></span>
          <span className="as-tile-label">{t.label}</span>
          <strong className={`as-tile-val ${t.tone}`}>{t.value}</strong>
          <span className="as-tile-sub small">{t.sub}</span>
          <Icon name="chevronRight" size={14} className="as-tile-go" />
        </a>
      ))}
      <p className="as-updated muted small">Přepočteno {formatDateTime(a.computed_at)} · obnova každých 5 minut</p>
    </section>
  );
}
