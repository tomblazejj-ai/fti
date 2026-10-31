import { useState } from "react";
import { Panel } from "../../components/Panel";
import { signed } from "../../lib/format";
import type { SeasonDaily, SeasonWindow } from "../../lib/types";

const LINES = [
  { key: "5", color: "var(--yellow)" },
  { key: "10", color: "var(--bull)" },
  { key: "15", color: "var(--bear)" },
] as const;

/** Funded Mind seasonal windows: the same calendar days in each of the last 10 years. */
export function SeasonalityDaily({ d }: { d: SeasonDaily }) {
  return (
    <div className="grid g-2">
      <Panel title="Sezónní okna" tag={d.label} icon="calendar" note="denní data, 10 let">
        <div className="sw">
          {d.next30 && <WindowCard w={d.next30} title="Příštích 30 dní" label={d.label} />}
          {d.best_up && <WindowCard w={d.best_up} title="Nejsilnější růstové okno" label={d.label} />}
          {d.best_down && <WindowCard w={d.best_down} title="Nejsilnější poklesové okno" label={d.label} />}
          {!d.best_up && !d.best_down && <p className="muted small">V příštích třech týdnech nezačíná žádné výrazné okno (aspoň 7 z 10 let stejným směrem).</p>}
        </div>
        <p className="muted small">{d.note} Zdroj: {d.source}.</p>
      </Panel>
      <Panel title="Sezónní cesta kolem dneška" tag={d.label} icon="line" note="průměr let, 0 = dnešní datum">
        <DailyPath d={d} />
      </Panel>
    </div>
  );
}

function WindowCard({ w, title, label }: { w: SeasonWindow; title: string; label: string }) {
  const up = w.avg >= 0;
  const max = Math.max(...w.by_year.map((y) => Math.abs(y.ret)), 0.5);
  return (
    <div className={`sw-card ${up ? "is-up" : "is-down"}`}>
      <div className="sw-head">
        <span className="as-eyebrow">{title}</span>
        <strong>{w.from_text} – {w.to_text}</strong>
      </div>
      <p className="sw-stat">
        <span className={up ? "tone-bullish" : "tone-bearish"}>{signed(w.avg, 1)} %</span> průměr ·{" "}
        {up ? `růst v ${w.up} z ${w.n} let` : `pokles v ${w.n - w.up} z ${w.n} let`}
      </p>
      <div className="sw-years" role="img" aria-label={`${label}: změna v jednotlivých letech`}>
        {[...w.by_year].reverse().map((y) => (
          <span key={y.year} className="sw-year" title={`${y.year}: ${signed(y.ret, 1)} %`}>
            <span className="sw-bar-wrap">
              <i className={y.ret >= 0 ? "pos" : "neg"} style={{ height: `${Math.max(6, (Math.abs(y.ret) / max) * 100)}%` }} />
            </span>
            <small>{String(y.year).slice(2)}</small>
          </span>
        ))}
      </div>
    </div>
  );
}

const W = 640;
const H = 230;
const PAD = { top: 14, right: 14, bottom: 26, left: 44 };

function DailyPath({ d }: { d: SeasonDaily }) {
  const [hover, setHover] = useState<number | null>(null);
  const keys = LINES.filter((l) => d.path.lines[l.key]);
  const off = d.path.offsets;
  if (!keys.length || off.length < 2) return <p className="muted small">Málo historie.</p>;
  const vals = keys.flatMap((l) => d.path.lines[l.key]);
  const lo = Math.min(0, ...vals) - 0.3;
  const hi = Math.max(0, ...vals) + 0.3;
  const x = (i: number) => PAD.left + (i / (off.length - 1)) * (W - PAD.left - PAD.right);
  const y = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo)) * (H - PAD.top - PAD.bottom);
  const zero = off.indexOf(0);
  const step = hi - lo > 10 ? 2 : 1;
  const ticks: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) ticks.push(t);
  const labelAt = off.map((o, i) => (o % 14 === 0 ? i : -1)).filter((i) => i >= 0);
  return (
    <div className="chart-box">
      <div className="ov-legend small">
        {keys.map((l) => (
          <span key={l.key}>
            <i className="lg-dot" style={{ background: l.color }} /> {d.path.years_used[l.key] ?? l.key} let
          </span>
        ))}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Průměrný sezónní vývoj ${d.label} od dvou týdnů zpět do tří měsíců dopředu`}
        onPointerMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const px = ((e.clientX - r.left) / r.width) * W;
          setHover(Math.max(0, Math.min(off.length - 1, Math.round(((px - PAD.left) / (W - PAD.left - PAD.right)) * (off.length - 1)))));
        }}
        onPointerLeave={() => setHover(null)}
      >
        <rect x={x(zero)} y={PAD.top} width={x(Math.min(off.length - 1, zero + 30)) - x(zero)} height={H - PAD.top - PAD.bottom} className="sw-next" />
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className={t === 0 ? "cc-zero" : "cc-grid"} />
            <text x={PAD.left - 6} y={y(t) + 3} textAnchor="end" className="cc-tick">{t > 0 ? `+${t}` : t} %</text>
          </g>
        ))}
        {labelAt.map((i) => {
          const dt = new Date(d.path.dates[i]);
          return <text key={i} x={x(i)} y={H - 8} textAnchor="middle" className="cc-tick">{off[i] === 0 ? "dnes" : `${dt.getDate()}. ${dt.getMonth() + 1}.`}</text>;
        })}
        <line x1={x(zero)} x2={x(zero)} y1={PAD.top} y2={H - PAD.bottom} className="sw-today" />
        {keys.map((l) => (
          <path key={l.key} d={d.path.lines[l.key].map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("")}
                fill="none" stroke={l.color} strokeWidth={l.key === "10" ? 2.4 : 1.6} strokeLinejoin="round" />
        ))}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={H - PAD.bottom} className="cc-cross" />}
      </svg>
      {hover !== null && (
        <div className="cchart-tip" style={{ left: `${Math.min(78, (x(hover) / W) * 100)}%` }}>
          <strong>{new Date(d.path.dates[hover]).toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" })}</strong>
          {keys.map((l) => (
            <span key={l.key}>{d.path.years_used[l.key] ?? l.key} let: {signed(d.path.lines[l.key][hover], 1)} %</span>
          ))}
        </div>
      )}
      <p className="muted small">Zvýrazněných je příštích 30 dní. Čára = průměrný vývoj ceny od dnešního data v minulých letech, ne předpověď.</p>
    </div>
  );
}
