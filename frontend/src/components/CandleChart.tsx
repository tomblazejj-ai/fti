import { useCallback, useMemo, useRef, useState } from "react";
import { useAsync, useInterval } from "../hooks/useAsync";
import { STATIC, api } from "../lib/api";
import { relativeTime } from "../lib/format";
import type { CandleRow, Level, TfTrend } from "../lib/types";
import { Pills } from "./Panel";

export type Tf = TfTrend["tf"];

/** A supply/demand zone drawn as a band (weekly ones dashed). */
export interface ChartZone {
  lo: number;
  hi: number;
  kind: "demand" | "supply";
  tf: "W1" | "D1";
  formed?: string;
}

/** Entry, stop-loss and target of the assistant's plan. */
export interface ChartPlan {
  entry: number;
  stop: number;
  target: number | null;
  side: "long" | "short";
}
const TFS: Tf[] = ["M15", "H1", "H4", "D1", "W1"];
const W = 960;
const H = 380;
const PAD = { top: 14, right: 78, bottom: 28, left: 8 };
const MONTHS = ["led", "úno", "bře", "dub", "kvě", "čvn", "čvc", "srp", "zář", "říj", "lis", "pro"];

function fmt(v: number, digits: number): string {
  return v.toLocaleString("cs-CZ", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function timeLabel(sec: number, tf: Tf): string {
  const d = new Date(sec * 1000);
  if (tf === "D1" || tf === "W1") return `${d.getDate()}. ${MONTHS[d.getMonth()]}`;
  return `${d.getDate()}. ${d.getMonth() + 1}. ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** Live candlestick chart (Kraken via the backend), refreshed every minute. */
export function CandleChart({
  code,
  digits = 2,
  levels = [],
  initialTf = "H4",
  unit = "",
  compact = false,
  zones = [],
  plan = null,
  lineOnly = false,
}: {
  code: string;
  digits?: number;
  levels?: (Level & { kind: "support" | "resistance" })[];
  initialTf?: Tf;
  unit?: string;
  compact?: boolean;
  zones?: ChartZone[];
  plan?: ChartPlan | null;
  /** daily closing prices only (USD/JPY from ECB, WTI from FRED): a line on D1/W1 */
  lineOnly?: boolean;
}) {
  // the phone version only carries the H4/D1/W1 snapshot
  const tfs: Tf[] = lineOnly ? ["D1", "W1"] : STATIC ? ["H4", "D1", "W1"] : TFS;
  const [tf, setTf] = useState<Tf>(tfs.includes(initialTf) ? initialTf : "D1");
  const [kindState, setKind] = useState<"candles" | "line">("candles");
  const kind = lineOnly ? "line" : kindState;
  const [showEma, setShowEma] = useState(true);
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const data = useAsync(() => api.candles(code, tf), [code, tf]);
  const reload = useCallback(() => data.reload(), [data.reload]);
  useInterval(reload, 60000);

  const rows: CandleRow[] = useMemo(() => (data.data?.tf === tf ? data.data.candles.slice(compact ? -80 : -120) : []), [data.data, tf, compact]);
  const levelPrices = [
    ...levels.filter((l) => l.price).map((l) => l.price as number),
    ...zones.flatMap((z) => [z.lo, z.hi]),
    ...(plan ? [plan.entry, plan.stop, ...(plan.target ? [plan.target] : [])] : []),
  ];

  const scale = useMemo(() => {
    if (!rows.length) return null;
    let lo = Math.min(...rows.map((r) => r[3]));
    let hi = Math.max(...rows.map((r) => r[2]));
    // show daily levels only when they are near the visible range
    const span0 = hi - lo;
    for (const p of levelPrices) if (p > lo - span0 * 0.35 && p < hi + span0 * 0.35) { lo = Math.min(lo, p); hi = Math.max(hi, p); }
    const pad = (hi - lo) * 0.06 || 1;
    return { lo: lo - pad, hi: hi + pad };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, levelPrices.join(",")]);

  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const step = rows.length ? plotW / rows.length : 1;
  const x = (i: number) => PAD.left + step * (i + 0.5);
  const y = (v: number) => (scale ? PAD.top + (1 - (v - scale.lo) / (scale.hi - scale.lo)) * plotH : 0);

  const ticks = useMemo(() => {
    if (!scale) return [];
    const raw = (scale.hi - scale.lo) / 6;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const nice = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
    const out = [];
    for (let v = Math.ceil(scale.lo / nice) * nice; v <= scale.hi; v += nice) out.push(v);
    return out;
  }, [scale]);

  const last = rows[rows.length - 1];
  const prevClose = rows.length > 1 ? rows[rows.length - 2][4] : null;
  const up = last && prevClose !== null ? last[4] >= prevClose : true;
  const h = hover !== null ? rows[hover] : null;

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || !rows.length) return;
    const px = ((e.clientX - rect.left) / rect.width) * W;
    setHover(Math.max(0, Math.min(rows.length - 1, Math.floor((px - PAD.left) / step))));
  }

  const linePath = (idx: number) => rows.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(r[idx]).toFixed(1)}`).join("");
  const labelEvery = Math.max(1, Math.round(rows.length / 6));

  return (
    <div className={`cchart${compact ? " compact" : ""}`}>
      <div className="cchart-bar">
        <Pills label="Timeframe" options={tfs.map((t) => ({ value: t, label: t }))} value={tf} onChange={(t) => { setTf(t); setHover(null); }} />
        <div className="cchart-bar-right">
          <button type="button" className={`legend-toggle${showEma ? " is-on" : ""}`} onClick={() => setShowEma((s) => !s)} aria-pressed={showEma}>
            <i className="lg-ema20" /> EMA20 <i className="lg-ema50" /> EMA50
          </button>
          {!lineOnly && <Pills
            label="Typ grafu"
            options={[
              { value: "candles", label: "Svíčky", title: "Svíčkový graf" },
              { value: "line", label: "Čára", title: "Čárový graf" },
            ]}
            value={kind}
            onChange={setKind}
          />}
        </div>
      </div>
      <div className="cchart-box">
        {data.error && !rows.length ? (
          <p className="cchart-msg">Graf se nepodařilo načíst: {data.error.message}</p>
        ) : !rows.length || !scale ? (
          <p className="cchart-msg">Načítám svíčky…</p>
        ) : (
          <svg
            ref={svgRef}
            viewBox={`0 0 ${W} ${H}`}
            role="img"
            aria-label={`Graf ${code}, timeframe ${tf}, posledních ${rows.length} svíček`}
            onPointerMove={onMove}
            onPointerLeave={() => setHover(null)}
            className="cchart-svg"
          >
            <defs>
              <linearGradient id={`area-${code}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="var(--accent)" stopOpacity="0.35" />
                <stop offset="1" stopColor="var(--accent)" stopOpacity="0" />
              </linearGradient>
            </defs>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="cc-grid" />
                <text x={W - PAD.right + 8} y={y(t) + 4} className="cc-tick">{fmt(t, digits > 2 ? 2 : 0)}</text>
              </g>
            ))}
            {rows.map((r, i) =>
              i % labelEvery === 0 ? (
                <text key={r[0]} x={x(i)} y={H - 8} className="cc-tick" textAnchor="middle">{timeLabel(r[0], tf)}</text>
              ) : null,
            )}
            {zones.map((z) => {
              if (!scale || z.hi < scale.lo || z.lo > scale.hi) return null;
              const formedSec = z.formed ? Date.parse(z.formed) / 1000 : 0;
              const first = rows.findIndex((r) => r[0] >= formedSec);
              const x0 = first > 0 ? x(first) - step / 2 : PAD.left;
              const top = y(Math.min(z.hi, scale.hi));
              const bottom = y(Math.max(z.lo, scale.lo));
              return (
                <g key={`${z.tf}-${z.kind}-${z.lo}`} className={`cc-zone cc-zone-${z.kind} cc-zone-${z.tf}`}>
                  <rect x={x0} y={top} width={W - PAD.right - x0} height={Math.max(2, bottom - top)} rx="3" />
                  <text x={W - PAD.right - 6} y={top + 13} textAnchor="end" className="cc-zone-label">
                    {z.tf === "W1" ? "týdenní" : "denní"} {z.kind === "demand" ? "demand" : "supply"}
                  </text>
                </g>
              );
            })}
            {levels.map((l) =>
              l.price && scale && l.price > scale.lo && l.price < scale.hi ? (
                <g key={l.kind}>
                  <line x1={PAD.left} x2={W - PAD.right} y1={y(l.price)} y2={y(l.price)} className={`cc-level cc-${l.kind}`} />
                  <text x={PAD.left + 6} y={y(l.price) - 5} className={`cc-level-label cc-${l.kind}`}>
                    {l.kind === "support" ? "Podpora" : "Odpor"} {fmt(l.price, 0)}
                  </text>
                </g>
              ) : null,
            )}
            {kind === "line" ? (
              <>
                <path d={`${linePath(4)}L${x(rows.length - 1)},${PAD.top + plotH}L${x(0)},${PAD.top + plotH}Z`} fill={`url(#area-${code})`} />
                <path d={linePath(4)} className="cc-line" />
              </>
            ) : (
              <g className="cc-candles">
                {rows.map((r, i) => {
                  const bull = r[4] >= r[1];
                  const bw = Math.max(1.5, step * 0.62);
                  const top = y(Math.max(r[1], r[4]));
                  const bot = y(Math.min(r[1], r[4]));
                  return (
                    <g key={r[0]} className={bull ? "cc-bull" : "cc-bear"}>
                      <line x1={x(i)} x2={x(i)} y1={y(r[2])} y2={y(r[3])} />
                      <rect x={x(i) - bw / 2} y={top} width={bw} height={Math.max(1, bot - top)} rx="1" />
                    </g>
                  );
                })}
              </g>
            )}
            {showEma && (
              <>
                <path d={linePath(5)} className="cc-ema20" />
                <path d={linePath(6)} className="cc-ema50" />
              </>
            )}
            {last && (
              <g>
                <line x1={PAD.left} x2={W - PAD.right} y1={y(last[4])} y2={y(last[4])} className={`cc-last ${up ? "is-up" : "is-down"}`} />
                <rect x={W - PAD.right + 2} y={y(last[4]) - 10} width={PAD.right - 4} height="20" rx="4" className={`cc-last-tag ${up ? "is-up" : "is-down"}`} />
                <text x={W - PAD.right + 8} y={y(last[4]) + 4} className="cc-last-text">{fmt(last[4], digits)}</text>
              </g>
            )}
            {plan && scale &&
              ([
                ["entry", plan.entry, "Vstup"],
                ["stop", plan.stop, "SL"],
                ["target", plan.target, "Cíl"],
              ] as const).map(([key, v, label]) =>
                v && v > scale.lo && v < scale.hi ? (
                  <g key={key} className={`cc-plan cc-plan-${key}`}>
                    <line x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} />
                    <rect x={PAD.left + 4} y={y(v) - 17} width={label.length * 7 + 64} height="15" rx="4" />
                    <text x={PAD.left + 9} y={y(v) - 6}>{label} {fmt(v, 0)}</text>
                  </g>
                ) : null,
              )}
            {h && hover !== null && (
              <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + plotH} className="cc-cross" />
            )}
          </svg>
        )}
        {h && hover !== null && (
          <div className="cchart-tip" style={{ left: `${Math.min(80, (x(hover) / W) * 100)}%` }}>
            <strong>{timeLabel(h[0], tf === "D1" || tf === "W1" ? tf : "H1")}</strong>
            <span>O {fmt(h[1], digits)} · H {fmt(h[2], digits)}</span>
            <span>L {fmt(h[3], digits)} · C {fmt(h[4], digits)}</span>
            <span className="muted">EMA20 {fmt(h[5], digits)} · EMA50 {fmt(h[6], digits)}</span>
          </div>
        )}
      </div>
      <p className="cchart-foot muted small">
        {data.data?.source}
        {unit && ` · ${unit}`} · obnova každou minutu{data.data && ` · staženo ${relativeTime(data.data.fetched_at)}`}
      </p>
    </div>
  );
}
