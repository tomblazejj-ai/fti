import { useState } from "react";
import { Donut } from "../../components/Donut";
import { Panel } from "../../components/Panel";
import { Unavailable } from "../../components/ui";
import { formatDate, shortDate } from "../../lib/format";
import type { Cot, CotUsd } from "../../lib/types";
import { CotMethodology } from "./CotExtra";

function contracts(n: number, withSign = true): string {
  const s = Math.abs(Math.round(n)).toLocaleString("cs-CZ");
  return withSign ? `${n > 0 ? "+" : n < 0 ? "−" : ""}${s}` : `${n < 0 ? "−" : ""}${s}`;
}

function pragueTime(iso: string): string {
  return new Date(iso).toLocaleString("cs-CZ", { weekday: "short", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function CotTab({ cot, cotUsd }: { cot: Cot | null; cotUsd?: CotUsd | null }) {
  if (!cot) return <Unavailable>Data COT se nepodařilo stáhnout.</Unavailable>;
  const idx = cot.cot_index_3y;
  const groups = (cot.groups ?? []).filter((g) => g.long !== null && g.short !== null);
  return (
    <div className="ov">
      <section className="panel cot-hero">
        <div>
          <p className="cot-lead">{cot.texts[0]}</p>
          <ul className="sum-list">
            {cot.texts.slice(1).map((t) => <li key={t}>{t}</li>)}
          </ul>
        </div>
        <div className="cot-dates">
          <div><span className="muted small">Data k (úterý)</span><strong>{formatDate(cot.as_of)}</strong></div>
          {cot.schedule && (
            <>
              <div><span className="muted small">Zveřejněno</span><strong>{pragueTime(cot.schedule.published)}</strong></div>
              <div className={cot.schedule.late ? "is-late" : ""}>
                <span className="muted small">Další report (obvykle)</span>
                <strong>{pragueTime(cot.schedule.next_release)}</strong>
                {cot.schedule.late && <span className="small tone-bearish">zpožděný — CFTC ho zatím nevydala</span>}
              </div>
            </>
          )}
        </div>
      </section>

      <Panel title="Kdo drží zlato" tag="COMEX Gold" icon="users" note={<><i className="lg-long" /> Long <i className="lg-short" /> Short</>}>
        {groups.length ? (
          <div className="donuts">
            {groups.map((g) => (
              <div key={g.key} className="donut-card">
                <Donut long={g.long!} short={g.short!} label={g.label} />
                <dl className="donut-kv small">
                  <dt>Čistě</dt><dd>{contracts(g.net, false)}</dd>
                  <dt>Za týden</dt><dd className={g.change_1w > 0 ? "tone-bullish" : g.change_1w < 0 ? "tone-bearish" : ""}>{contracts(g.change_1w)}</dd>
                  <dt>Za 4 týdny</dt><dd className={g.change_4w > 0 ? "tone-bullish" : g.change_4w < 0 ? "tone-bearish" : ""}>{contracts(g.change_4w)}</dd>
                  <dt>Index 3 r.</dt><dd>{g.index_3y === null ? "—" : `${Math.round(g.index_3y)}/100`}</dd>
                </dl>
                <p className="muted small">{g.who}</p>
              </div>
            ))}
          </div>
        ) : (
          <div className="donuts">
            <div className="donut-card">
              <Donut long={cot.spec_long} short={cot.spec_short} label="Velcí spekulanti" />
            </div>
          </div>
        )}
      </Panel>

      <div className="grid g-2">
        <Panel title="Pozice hedgeových fondů" tag="3 roky" icon="chart">
          <CotChart cot={cot} />
        </Panel>
        <Panel title="COT index" tag="3 roky" icon="gauge">
          <div className="cot-index">
            <strong className="cot-index-num">{idx === null ? "—" : Math.round(idx)}</strong>
            <span className="muted">/ 100</span>
          </div>
          {idx !== null && (
            <span className="cot-gauge2" role="img" aria-label={`COT index ${Math.round(idx)} ze 100`}>
              <span className="z-low">málo nakoupeno</span>
              <span className="z-high">přeplněno</span>
              <span className="cot-marker2" style={{ left: `${Math.max(0, Math.min(100, idx))}%` }} />
            </span>
          )}
          <p className="small">
            Kde je dnešní čistá pozice fondů mezi 3letým minimem (0) a maximem (100). Nad 80 = trh přeplněný kupci, hrozí výprodej. Pod 20 = fondy
            mají málo, je z čeho nakupovat.
          </p>
          {cot.long_short_ratio && <p className="small">Poměr long : short u fondů {cot.long_short_ratio.toLocaleString("cs-CZ")} : 1</p>}
          <p className="muted small">{cot.source_label}</p>
        </Panel>
      </div>
      <CotMethodology cot={cot} usd={cotUsd} />
    </div>
  );
}

const W = 640;
const H = 220;
const PAD = { top: 12, right: 12, bottom: 24, left: 60 };

function CotChart({ cot }: { cot: Cot }) {
  const hist = cot.history;
  const [hover, setHover] = useState<number | null>(null);
  if (hist.length < 2) return null;
  const vals = hist.map((h) => h.spec_net);
  const lo = Math.min(0, ...vals);
  const hi = Math.max(...vals);
  const x = (i: number) => PAD.left + (i / (hist.length - 1)) * (W - PAD.left - PAD.right);
  const y = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo || 1)) * (H - PAD.top - PAD.bottom);
  const d = hist.map((h, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(h.spec_net).toFixed(1)}`).join("");
  const step = Math.pow(10, Math.floor(Math.log10((hi - lo) / 3 || 1)));
  const ticks: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step * Math.ceil((hi - lo) / step / 4)) ticks.push(t);
  const years = hist.map((h, i) => ({ i, y: h.date.slice(0, 4) })).filter((p, k, arr) => k > 0 && p.y !== arr[k - 1].y);
  const h = hover !== null ? hist[hover] : null;

  return (
    <div className="chart-box">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Vývoj čisté pozice fondů ve zlatě za poslední 3 roky"
        onPointerMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const px = ((e.clientX - r.left) / r.width) * W;
          setHover(Math.max(0, Math.min(hist.length - 1, Math.round(((px - PAD.left) / (W - PAD.left - PAD.right)) * (hist.length - 1)))));
        }}
        onPointerLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id="cot-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--bull)" stopOpacity="0.35" />
            <stop offset="1" stopColor="var(--bull)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="cc-grid" />
            <text x={PAD.left - 6} y={y(t) + 3} textAnchor="end" className="cc-tick">{Math.round(t / 1000)} tis.</text>
          </g>
        ))}
        {years.map((p) => (
          <text key={p.i} x={x(p.i)} y={H - 6} textAnchor="middle" className="cc-tick">{p.y}</text>
        ))}
        <path d={`${d}L${x(hist.length - 1)},${y(lo)}L${x(0)},${y(lo)}Z`} fill="url(#cot-area)" />
        <path d={d} fill="none" stroke="var(--bull)" strokeWidth="2" strokeLinejoin="round" />
        {h && hover !== null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={H - PAD.bottom} className="cc-cross" />
            <circle cx={x(hover)} cy={y(h.spec_net)} r="4" fill="var(--bull)" stroke="var(--surface)" strokeWidth="2" />
          </g>
        )}
      </svg>
      {h && hover !== null && (
        <div className="cchart-tip" style={{ left: `${Math.min(80, (x(hover) / W) * 100)}%` }}>
          <strong>{shortDate(h.date)}</strong>
          <span>Čistě: {contracts(h.spec_net, false)}</span>
          {h.spec_long !== undefined && <span className="muted">long {contracts(h.spec_long, false)} · short {contracts(h.spec_short ?? 0, false)}</span>}
        </div>
      )}
    </div>
  );
}
