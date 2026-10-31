import { useState } from "react";
import { Panel, Pills } from "../../components/Panel";
import { TraChip } from "../../components/Tra";
import { shortDate, signed } from "../../lib/format";
import type { SeasonDaily, SeasonalityLong, SeasonalityLongSide } from "../../lib/types";
import { SeasonalityDaily } from "./SeasonalityDaily";

const SHORT = ["Led", "Úno", "Bře", "Dub", "Kvě", "Čvn", "Čvc", "Srp", "Zář", "Říj", "Lis", "Pro"];
const LINES = [
  { key: "5", label: "5 let", color: "var(--yellow)" },
  { key: "10", label: "10 let", color: "var(--bull)" },
  { key: "15", label: "15 let", color: "var(--bear)" },
] as const;

/** Funded Mind seasonality: 5 / 10 / 15-year averages, the average path ahead and a heatmap with the average. */
export function SeasonalityLongSection({ long, daily }: { long: SeasonalityLong; daily?: { gold?: SeasonDaily | null; usd?: SeasonDaily | null } | null }) {
  const sides = (["gold", "usd"] as const).filter((k) => long[k]);
  const [side, setSide] = useState<"gold" | "usd">(sides[0] ?? "gold");
  const s = long[side];
  if (!s) return null;
  const nowMonth = new Date().getMonth() + 1;
  return (
    <>
      <section className="panel season-hero">
        <div className="season-now">
          <span className="muted small">Tento měsíc · {s.label}</span>
          <p>{s.current_text}</p>
        </div>
        <div className="season-now">
          <span className="muted small">Příští měsíc</span>
          <p>{s.next_text}</p>
        </div>
        <div className="season-score">
          <span className="muted small">Skóre sezónnosti</span>
          <TraChip value={s.score} big />
          {sides.length > 1 && (
            <Pills label="Sezónnost pro" options={sides.map((k) => ({ value: k, label: k === "gold" ? "Zlato" : "Dolar" }))} value={side} onChange={setSide} />
          )}
        </div>
      </section>
      {daily?.[side] && <SeasonalityDaily d={daily[side]!} />}
      <div className="grid g-2">
        <Panel title="Sezónní cesta na 12 měsíců" tag={s.label} icon="line" note="průměr za 5, 10 a 15 let">
          <PathChart s={s} />
        </Panel>
        <Panel title="Průměr podle měsíce" tag={s.label} icon="sun" note="5 · 10 · 15 let">
          <MonthBars s={s} nowMonth={nowMonth} />
        </Panel>
      </div>
      <Panel title="Heatmapa posledních 10 let" tag={`${s.label} · změna za měsíc v %`} icon="calendar">
        <Heat s={s} nowMonth={nowMonth} />
        <p className="muted small">
          {s.note} Zdroj: {s.source}
          {s.updated ? `, aktualizace ${/^\d{4}-\d{2}-\d{2}$/.test(s.updated) ? shortDate(s.updated) : s.updated}` : ""}.
        </p>
      </Panel>
    </>
  );
}

const W = 640;
const H = 230;
const PAD = { top: 14, right: 14, bottom: 26, left: 44 };

function PathChart({ s }: { s: SeasonalityLongSide }) {
  const [hover, setHover] = useState<number | null>(null);
  const n = s.path.labels.length;
  const vals = LINES.flatMap((l) => s.path.lines[l.key]);
  const lo = Math.min(0, ...vals) - 0.5;
  const hi = Math.max(0, ...vals) + 0.5;
  const x = (i: number) => PAD.left + (i / (n - 1)) * (W - PAD.left - PAD.right);
  const y = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo)) * (H - PAD.top - PAD.bottom);
  const step = hi - lo > 12 ? 4 : hi - lo > 6 ? 2 : 1;
  const ticks: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) ticks.push(t);
  return (
    <div className="chart-box">
      <div className="ov-legend small">
        {LINES.map((l) => (
          <span key={l.key}>
            <i style={{ background: l.color }} className="lg-dot" /> {l.label}
          </span>
        ))}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Průměrná sezónní cesta ceny – ${s.label}`}
        onPointerMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const px = ((e.clientX - r.left) / r.width) * W;
          setHover(Math.max(0, Math.min(n - 1, Math.round(((px - PAD.left) / (W - PAD.left - PAD.right)) * (n - 1)))));
        }}
        onPointerLeave={() => setHover(null)}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className={t === 0 ? "cc-zero" : "cc-grid"} />
            <text x={PAD.left - 6} y={y(t) + 3} textAnchor="end" className="cc-tick">{t > 0 ? `+${t}` : t} %</text>
          </g>
        ))}
        {s.path.labels.map((l, i) => (
          <text key={`${l}${i}`} x={x(i)} y={H - 8} textAnchor="middle" className="cc-tick">{l.slice(0, 3)}</text>
        ))}
        {LINES.map((l) => (
          <path key={l.key} d={s.path.lines[l.key].map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("")}
                fill="none" stroke={l.color} strokeWidth={l.key === "10" ? 2.6 : 1.8} strokeLinejoin="round" />
        ))}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={H - PAD.bottom} className="cc-cross" />}
      </svg>
      {hover !== null && (
        <div className="cchart-tip" style={{ left: `${Math.min(78, (x(hover) / W) * 100)}%` }}>
          <strong>začátek: {s.path.labels[hover]}</strong>
          {LINES.map((l) => (
            <span key={l.key}>{l.label}: {signed(s.path.lines[l.key][hover])} %</span>
          ))}
        </div>
      )}
      <p className="muted small">Jak by se cena v průměru vyvíjela od začátku tohoto měsíce, kdyby se opakovala historie. Není to předpověď ceny.</p>
    </div>
  );
}

function MonthBars({ s, nowMonth }: { s: SeasonalityLongSide; nowMonth: number }) {
  const max = Math.max(...s.months.flatMap((m) => [m.avg5, m.avg10, m.avg15].map((v) => Math.abs(v ?? 0))), 0.5);
  return (
    <>
      <div className="mbars" role="img" aria-label="Průměrná změna podle měsíce za 5, 10 a 15 let">
        {s.months.map((m) => (
          <div key={m.month} className={`mbar${m.month === nowMonth ? " is-now" : ""}`}
               title={`${m.name}: 5 let ${m.avg5 ?? "—"} %, 10 let ${m.avg10 ?? "—"} %, 15 let ${m.avg15 ?? "—"} %, růst v ${m.win10 ?? "—"} % let`}>
            <div className="mbar-plot">
              {LINES.map((l) => {
                const v = l.key === "5" ? m.avg5 : l.key === "10" ? m.avg10 : m.avg15;
                const h = ((Math.abs(v ?? 0)) / max) * 50;
                return (
                  <span key={l.key} className="mbar-col">
                    <i style={{ background: l.color, height: `${h}%`, ...(v !== null && v < 0 ? { top: "50%" } : { bottom: "50%" }) }} />
                  </span>
                );
              })}
            </div>
            <span className={`sb-val small ${(m.avg10 ?? 0) > 0 ? "tone-bullish" : (m.avg10 ?? 0) < 0 ? "tone-bearish" : ""}`}>
              {m.avg10 === null ? "—" : signed(m.avg10)}
            </span>
            <span className="sb-name">{SHORT[m.month - 1]}</span>
          </div>
        ))}
      </div>
      <p className="muted small">Tři sloupce u měsíce = průměrná změna za 5, 10 a 15 let; číslo pod nimi je 10letý průměr v %.</p>
    </>
  );
}

function cell(r: number | null | undefined) {
  if (r === null || r === undefined) return undefined;
  const a = Math.min(1, Math.abs(r) / 6);
  return { background: r >= 0 ? `rgba(30, 194, 139, ${0.15 + a * 0.6})` : `rgba(242, 69, 61, ${0.15 + a * 0.6})` };
}

function Heat({ s, nowMonth }: { s: SeasonalityLongSide; nowMonth: number }) {
  return (
    <div className="heat-wrap">
      <table className="heat">
        <thead>
          <tr>
            <th />
            {SHORT.map((m, i) => <th key={m} className={i + 1 === nowMonth ? "is-now" : ""}>{m}</th>)}
          </tr>
        </thead>
        <tbody>
          {s.heatmap.map((row) => (
            <tr key={row.year}>
              <th>{row.year}</th>
              {row.months.map((r, i) => (
                <td key={i} style={cell(r)}>{r === null || r === undefined ? "" : signed(r)}</td>
              ))}
            </tr>
          ))}
          <tr className="heat-avg">
            <th>Ø 10 let</th>
            {s.months.map((m) => (
              <td key={m.month} style={cell(m.avg10)}>{m.avg10 === null ? "" : signed(m.avg10)}</td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
