import { useMemo, useState } from "react";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { signed } from "../lib/format";
import type { TraComponent, TraMomentum, TraPack } from "../lib/types";
import { Panel, Pills } from "./Panel";
import { Unavailable } from "./ui";

const ARROW = { up: "↑", down: "↓", flat: "→" } as const;

function minus(n: number): string {
  return n < 0 ? `−${Math.abs(n)}` : `${n}`;
}

/** Trading Analyzer style cell: green ↑n, red ↓n, grey — 0. */
export function TraChip({ value, big = false }: { value: number | null; big?: boolean }) {
  if (value === null) return <span className={`tra-chip is-na${big ? " big" : ""}`} title="data nejsou k dispozici">—</span>;
  const tone = value > 0 ? "pos" : value < 0 ? "neg" : "zero";
  return (
    <span className={`tra-chip is-${tone}${big ? " big" : ""}`}>
      <span aria-hidden="true">{value > 0 ? "↑" : value < 0 ? "↓" : "—"}</span> {Math.abs(value)}
    </span>
  );
}

/** −max…+max as a row of cells, the score fills from the middle. */
function Scale({ value, max }: { value: number | null; max: number }) {
  const v = value ?? 0;
  return (
    <span className="tra-scale" aria-hidden="true">
      {Array.from({ length: max }, (_, i) => max - i).map((k) => (
        <i key={`n${k}`} className={v < 0 && -v >= k ? "on neg" : ""} />
      ))}
      <b />
      {Array.from({ length: max }, (_, i) => i + 1).map((k) => (
        <i key={`p${k}`} className={v > 0 && v >= k ? "on pos" : ""} />
      ))}
    </span>
  );
}

export function verdictWord(p: Pick<TraPack, "strength" | "word">): string {
  return `${p.strength}${p.strength ? p.word.toLowerCase() : p.word}`;
}

/** "Score Overview" — every category of the Funded Mind / TrA model, click a row for the why. */
export function ScoreOverview({ pack, tag, subject, note, className }: { pack: TraPack; tag: string; subject: string; note?: string; className?: string }) {
  const [open, setOpen] = useState<string | null>(null);
  const [help, setHelp] = useState(false);
  return (
    <Panel
      title="Score Overview"
      tag={tag}
      icon="layers"
      className={className}
      actions={
        <button type="button" className={`help-btn${help ? " is-on" : ""}`} aria-expanded={help} aria-label="Jak skóre funguje" onClick={() => setHelp(!help)}>
          ?
        </button>
      }
    >
      {help && (
        <div className="tra-help small">
          <p>
            Skóre podle metodiky Funded Mind / Trading Analyzer: každá kategorie má svůj rozsah podle důležitosti a celkové skóre je jejich{" "}
            <strong>součet</strong> (−{pack.max} až +{pack.max}). Kladné = {subject} spíš poroste, záporné = spíš bude klesat.
          </p>
          <p>
            Makro kategorie (HDP, inflace, trh práce, sazby, PMI, tržby) se počítají pro <strong>americký dolar</strong>. U zlata mají opačné
            znaménko: silnější dolar = horší pro XAU/USD. Klikni na řádek a uvidíš přesná čísla a pravidlo.
          </p>
          {note && <p className="muted">{note}</p>}
        </div>
      )}
      <ul className="tra-list">
        {pack.components.map((c) => (
          <Row key={c.key} c={c} open={open === c.key} onToggle={() => setOpen(open === c.key ? null : c.key)} />
        ))}
      </ul>
      <div className={`tra-final is-${pack.arrow}`}>
        <span className="tra-final-label">Final Score</span>
        <span className="tra-final-word">
          {verdictWord(pack)} <span aria-hidden="true">{ARROW[pack.arrow]}</span>
        </span>
        <span className="tra-final-num">{pack.total > 0 ? `+${pack.total}` : minus(pack.total)}</span>
      </div>
      {pack.missing.length > 0 && <p className="muted small">Bez dat (počítáno jako 0): {pack.missing.join(", ")}.</p>}
    </Panel>
  );
}

function Row({ c, open, onToggle }: { c: TraComponent; open: boolean; onToggle: () => void }) {
  return (
    <li className={open ? "is-open" : ""}>
      <button type="button" className="tra-row" aria-expanded={open} onClick={onToggle}>
        <span className="tra-label">
          {c.label}
          {c.proxy && <span className="tra-proxy" title={c.proxy}>≈</span>}
        </span>
        <Scale value={c.score} max={c.max} />
        <TraChip value={c.score} />
      </button>
      {open && (
        <div className="tra-detail small">
          <p>{c.reason}</p>
          {c.inputs.length > 0 && (
            <dl className="tra-inputs">
              {c.inputs.map((i) => (
                <div key={i.name}>
                  <dt>{i.name}</dt>
                  <dd>
                    {i.value} <span className="muted">· {i.as_of}</span>
                  </dd>
                </div>
              ))}
            </dl>
          )}
          <p className="muted">Rozsah kategorie ±{c.max}.{c.proxy ? ` Náhrada placených dat: ${c.proxy}` : ""}</p>
        </div>
      )}
    </li>
  );
}

const RANGES = [
  { value: "1d", label: "1D", days: 1 },
  { value: "1w", label: "1W", days: 7 },
  { value: "1m", label: "1M", days: 30 },
  { value: "3m", label: "3M", days: 91 },
  { value: "6m", label: "6M", days: 182 },
  { value: "1y", label: "1Y", days: 365 },
] as const;
type RangeKey = (typeof RANGES)[number]["value"];

const W = 640;
const H = 220;
const PAD = { top: 14, right: 14, bottom: 26, left: 34 };

function ChangeChip({ v, label }: { v: number | null | undefined; label: string }) {
  if (v === null || v === undefined) return <span className="tra-delta is-na">— {label}</span>;
  const tone = v > 0 ? "pos" : v < 0 ? "neg" : "zero";
  return (
    <span className={`tra-delta is-${tone}`}>
      {v > 0 ? `+${v}` : minus(v)} <span aria-hidden="true">{v > 0 ? "↗" : v < 0 ? "↘" : "→"}</span> {label}
    </span>
  );
}

/** "Score History": how the score moved — the methodology trades its CHANGE, not its level. */
export function ScoreHistory({ code, pack, momentum, refreshKey = 0, className }: {
  code: "XAUUSD" | "DXY";
  pack: TraPack;
  momentum: TraMomentum | null | undefined;
  refreshKey?: number;
  className?: string;
}) {
  const [range, setRange] = useState<RangeKey>("3m");
  const days = RANGES.find((r) => r.value === range)!.days;
  const hist = useAsync(() => api.traHistory(code, days), [code, days, refreshKey]);
  const [hover, setHover] = useState<number | null>(null);
  const pts = useMemo(() => (hist.data?.points ?? []).map((p) => ({ ...p, ms: new Date(p.t).getTime() })), [hist.data]);

  const head = (
    <div className="tra-hist-head">
      <strong className={`tra-hist-total is-${pack.arrow}`}>
        {pack.total > 0 ? `+${pack.total}` : minus(pack.total)} {pack.word} <span aria-hidden="true">{ARROW[pack.arrow]}</span>
      </strong>
      <ChangeChip v={momentum?.changes["24h"]} label="24h" />
      <ChangeChip v={momentum?.changes["7d"]} label="7 dní" />
      <ChangeChip v={momentum?.changes["30d"]} label="30 dní" />
    </div>
  );

  let body;
  if (pts.length < 2) {
    body = hist.loading ? <p className="muted small">Načítám historii…</p> : <Unavailable>Historie skóre se teprve sbírá.</Unavailable>;
  } else {
    const t0 = pts[0].ms;
    const t1 = Math.max(pts[pts.length - 1].ms, t0 + 1);
    const vals = pts.map((p) => p.total);
    const lo = Math.min(-3, ...vals) - 1;
    const hi = Math.max(3, ...vals) + 1;
    const x = (ms: number) => PAD.left + ((ms - t0) / (t1 - t0)) * (W - PAD.left - PAD.right);
    const y = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo)) * (H - PAD.top - PAD.bottom);
    // step line: the score holds its value until the next point
    const d = pts.map((p, i) => (i ? `H${x(p.ms).toFixed(1)}V${y(p.total).toFixed(1)}` : `M${x(p.ms).toFixed(1)},${y(p.total).toFixed(1)}`)).join("");
    const step = hi - lo > 16 ? 5 : hi - lo > 8 ? 2 : 1;
    const ticks: number[] = [];
    for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) ticks.push(t);
    const labels = axisLabels(t0, t1, days);
    const hp = hover !== null ? pts[hover] : null;
    body = (
      <div className="chart-box">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`Historie skóre za ${RANGES.find((r) => r.value === range)!.label}`}
          onPointerMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const ms = t0 + ((((e.clientX - r.left) / r.width) * W - PAD.left) / (W - PAD.left - PAD.right)) * (t1 - t0);
            let best = 0;
            pts.forEach((p, i) => {
              if (Math.abs(p.ms - ms) < Math.abs(pts[best].ms - ms)) best = i;
            });
            setHover(best);
          }}
          onPointerLeave={() => setHover(null)}
        >
          <defs>
            <linearGradient id="tra-area" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="var(--gold)" stopOpacity="0.28" />
              <stop offset="1" stopColor="var(--gold)" stopOpacity="0" />
            </linearGradient>
          </defs>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className={t === 0 ? "cc-zero" : "cc-grid"} />
              <text x={PAD.left - 6} y={y(t) + 3} textAnchor="end" className="cc-tick">{minus(t)}</text>
            </g>
          ))}
          {labels.map((l) => (
            <text key={l.ms} x={x(l.ms)} y={H - 8} textAnchor="middle" className="cc-tick">{l.text}</text>
          ))}
          <path d={`${d}V${y(lo)}H${x(pts[0].ms)}Z`} fill="url(#tra-area)" />
          <path d={d} fill="none" stroke="var(--gold)" strokeWidth="2.2" strokeLinejoin="round" className="tra-line" />
          {pts.length <= 90 && pts.map((p) => <circle key={p.t} cx={x(p.ms)} cy={y(p.total)} r="2.6" className="tra-dot" />)}
          {hp && (
            <g>
              <line x1={x(hp.ms)} x2={x(hp.ms)} y1={PAD.top} y2={H - PAD.bottom} className="cc-cross" />
              <circle cx={x(hp.ms)} cy={y(hp.total)} r="5" fill="var(--gold)" stroke="var(--surface)" strokeWidth="2" />
            </g>
          )}
        </svg>
        {hp && (
          <div className="cchart-tip" style={{ left: `${Math.min(78, (x(hp.ms) / W) * 100)}%` }}>
            <strong>{hp.total > 0 ? `+${hp.total}` : minus(hp.total)}</strong>
            <span>{new Date(hp.t).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" })}</span>
            <span className="muted">{hp.source === "live" ? "živě" : "rekonstrukce z historických dat"}</span>
          </div>
        )}
      </div>
    );
  }

  return (
    <Panel
      title="Score History"
      tag={code === "XAUUSD" ? "XAU/USD" : "USD"}
      icon="line"
      className={className}
      actions={<Pills label="Období historie skóre" options={RANGES.map((r) => ({ value: r.value, label: r.label }))} value={range} onChange={setRange} />}
    >
      {head}
      {body}
      {momentum && <MomentumNotes m={momentum} />}
      {hist.data && <p className="muted small">{hist.data.backfill_note}</p>}
    </Panel>
  );
}

function axisLabels(t0: number, t1: number, days: number): { ms: number; text: string }[] {
  const out: { ms: number; text: string }[] = [];
  const n = 5;
  for (let i = 0; i <= n; i++) {
    const ms = t0 + ((t1 - t0) * i) / n;
    const d = new Date(ms);
    out.push({
      ms,
      text: days <= 2 ? d.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" }) : `${d.getDate()}. ${d.getMonth() + 1}.${days > 200 ? ` ${String(d.getFullYear()).slice(2)}` : ""}`,
    });
  }
  return out;
}

/** Trade idea (score moved ≥ 2 points in 24 h) and the two model situations from "TrA Score Momentum". */
export function MomentumNotes({ m }: { m: TraMomentum }) {
  return (
    <div className="tra-mom">
      {m.idea ? (
        <div className={`tra-idea is-${m.idea.direction}`} role="status">
          <span className="tra-idea-tag">Obchodní nápad</span>
          <p>{m.idea.text}</p>
        </div>
      ) : (
        <p className="small muted">
          Momentum: {m.speed_text}. Obchodní nápad vzniká, když se skóre za 24 h změní aspoň o 2 body
          {m.changes["24h"] !== null ? ` (teď ${signed(m.changes["24h"], 0)})` : ""}.
        </p>
      )}
      {m.situations.map((s) => (
        <div key={s.key} className="tra-sit">
          <strong>{s.title}</strong>
          <p className="small">{s.text}</p>
        </div>
      ))}
    </div>
  );
}
