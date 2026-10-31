import { useState } from "react";
import { shortDate } from "../lib/format";
import { Pills } from "./Panel";

const RANGES = [
  { value: "3m", label: "3M", weeks: 13 },
  { value: "6m", label: "6M", weeks: 26 },
  { value: "1y", label: "1R", weeks: 52 },
  { value: "3y", label: "3R", weeks: 156 },
] as const;
type RangeKey = (typeof RANGES)[number]["value"];

const W = 640;
const H = 200;
const PAD = { top: 12, right: 12, bottom: 24, left: 40 };

function pct(v: number): string {
  return `${v.toFixed(1).replace(".", ",")} %`;
}

/** COT long % vs short % of one trader group over time (Funded Mind "COT – USD" chart). */
export function LongShortChart({ history, subject }: { history: { date: string; long_pct: number }[]; subject: string }) {
  const [range, setRange] = useState<RangeKey>("1y");
  const [hover, setHover] = useState<number | null>(null);
  const rows = history.slice(-RANGES.find((r) => r.value === range)!.weeks);
  if (rows.length < 2) return null;
  const x = (i: number) => PAD.left + (i / (rows.length - 1)) * (W - PAD.left - PAD.right);
  const y = (v: number) => PAD.top + (1 - v / 100) * (H - PAD.top - PAD.bottom);
  const line = (f: (v: number) => number) => rows.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(f(r.long_pct)).toFixed(1)}`).join("");
  const step = Math.max(1, Math.floor(rows.length / 5));
  const h = hover !== null ? rows[hover] : null;
  return (
    <div className="ls-chart">
      <div className="ls-head">
        <span className="small">
          <i className="lg-long" /> Long % <i className="lg-short" /> Short %
        </span>
        <Pills label={`Období COT – ${subject}`} options={RANGES.map((r) => ({ value: r.value, label: r.label }))} value={range} onChange={setRange} />
      </div>
      <div className="chart-box">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`Podíl long a short pozic – ${subject}`}
          onPointerMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const px = ((e.clientX - r.left) / r.width) * W;
            setHover(Math.max(0, Math.min(rows.length - 1, Math.round(((px - PAD.left) / (W - PAD.left - PAD.right)) * (rows.length - 1)))));
          }}
          onPointerLeave={() => setHover(null)}
        >
          {[0, 25, 50, 75, 100].map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className={t === 50 ? "cc-zero" : "cc-grid"} />
              <text x={PAD.left - 6} y={y(t) + 3} textAnchor="end" className="cc-tick">{t} %</text>
            </g>
          ))}
          {rows.map((r, i) =>
            i % step === 0 ? (
              <text key={r.date} x={x(i)} y={H - 6} textAnchor="middle" className="cc-tick">
                {shortDate(r.date).replace(/ \d{4}$/, "")}
              </text>
            ) : null,
          )}
          <path d={line((v) => 100 - v)} fill="none" stroke="var(--bear)" strokeWidth="2" strokeLinejoin="round" />
          <path d={line((v) => v)} fill="none" stroke="var(--bull)" strokeWidth="2.2" strokeLinejoin="round" />
          {h && hover !== null && (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={H - PAD.bottom} className="cc-cross" />
              <circle cx={x(hover)} cy={y(h.long_pct)} r="4" fill="var(--bull)" stroke="var(--surface)" strokeWidth="2" />
              <circle cx={x(hover)} cy={y(100 - h.long_pct)} r="4" fill="var(--bear)" stroke="var(--surface)" strokeWidth="2" />
            </g>
          )}
        </svg>
        {h && hover !== null && (
          <div className="cchart-tip" style={{ left: `${Math.min(78, (x(hover) / W) * 100)}%` }}>
            <strong>{shortDate(h.date)}</strong>
            <span className="tone-bullish">long {pct(h.long_pct)}</span>
            <span className="tone-bearish">short {pct(100 - h.long_pct)}</span>
          </div>
        )}
      </div>
    </div>
  );
}
