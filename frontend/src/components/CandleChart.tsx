import { useCallback, useMemo, useRef, useState } from "react";
import { useAsync, useInterval } from "../hooks/useAsync";
import { STATIC, api } from "../lib/api";
import { relativeTime } from "../lib/format";
import type { CandleRow, Tf } from "../lib/types";
import { MarketChip, QualityBadge } from "./Bits";
import { Pills } from "./ui";

const TFS: Tf[] = ["M15", "H1", "H4", "D1", "W1"];
const W = 960;
const H = 380;
const PAD = { top: 14, right: 78, bottom: 28, left: 8 };
const MONTHS = ["led", "úno", "bře", "dub", "kvě", "čvn", "čvc", "srp", "zář", "říj", "lis", "pro"];

function fmt(v: number, digits: number): string {
  return v.toLocaleString("cs-CZ", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function timeLabel(sec: number, tf: Tf, day?: string): string {
  if ((tf === "D1" || tf === "W1") && day) {
    // the trading day from the backend: a broker's daily candle starts at 17:00 New York the evening before
    const [, m, dd] = day.split("-").map(Number);
    return `${dd}. ${MONTHS[m - 1]}`;
  }
  const d = new Date(sec * 1000);
  if (tf === "D1" || tf === "W1") return `${d.getDate()}. ${MONTHS[d.getMonth()]}`;
  return `${d.getDate()}. ${d.getMonth() + 1}. ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** Price chart (candles or line) from the backend, refreshed every minute. */
export function CandleChart({
  code,
  digits = 2,
  initialTf = "D1",
  lineOnly = false,
}: {
  code: string;
  digits?: number;
  initialTf?: Tf;
  /** daily closing prices only (USD/JPY from ECB, WTI from FRED): a line on D1/W1 */
  lineOnly?: boolean;
}) {
  // the phone version only carries the H4/D1/W1 snapshot
  const tfs: Tf[] = lineOnly ? ["D1", "W1"] : STATIC ? ["H4", "D1", "W1"] : TFS;
  const [tf, setTf] = useState<Tf>(tfs.includes(initialTf) ? initialTf : "D1");
  const [kindState, setKind] = useState<"candles" | "line">("line");
  const kind = lineOnly ? "line" : kindState;
  const [showEma, setShowEma] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const data = useAsync(() => api.candles(code, tf), [code, tf]);
  const reload = useCallback(() => data.reload(), [data.reload]);
  useInterval(reload, 60000);

  const rows: CandleRow[] = useMemo(() => (data.data?.tf === tf ? data.data.candles.slice(-120) : []), [data.data, tf]);
  const days: string[] = useMemo(() => {
    const all = data.data?.tf === tf ? data.data.days : null;
    return all && all.length === data.data?.candles.length ? all.slice(-120) : [];
  }, [data.data, tf]);

  const scale = useMemo(() => {
    if (!rows.length) return null;
    const lo = Math.min(...rows.map((r) => r[3]));
    const hi = Math.max(...rows.map((r) => r[2]));
    const pad = (hi - lo) * 0.06 || 1;
    return { lo: lo - pad, hi: hi + pad };
  }, [rows]);

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
  const first = rows[0];
  const up = last && first ? last[4] >= first[4] : true;
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
    <div className="cchart">
      <div className="cchart-bar">
        <Pills label="Časový rámec" options={tfs.map((t) => ({ value: t, label: t }))} value={tf} onChange={(t) => { setTf(t); setHover(null); }} />
        <div className="cchart-bar-right">
          <button type="button" className={`legend-toggle${showEma ? " is-on" : ""}`} onClick={() => setShowEma((s) => !s)} aria-pressed={showEma}>
            <i className="lg-ema20" /> EMA20 <i className="lg-ema50" /> EMA50
          </button>
          {!lineOnly && (
            <Pills
              label="Typ grafu"
              options={[
                { value: "line", label: "Čára", title: "Čárový graf" },
                { value: "candles", label: "Svíčky", title: "Svíčkový graf" },
              ]}
              value={kind}
              onChange={setKind}
            />
          )}
        </div>
      </div>
      <div className="cchart-box">
        {data.error && !rows.length ? (
          <p className="cchart-msg">Graf se nepodařilo načíst: {data.error.message}</p>
        ) : !rows.length || !scale ? (
          <p className="cchart-msg">Načítám graf…</p>
        ) : (
          <svg
            ref={svgRef}
            viewBox={`0 0 ${W} ${H}`}
            role="img"
            aria-label={`Graf ${code}, časový rámec ${tf}, posledních ${rows.length} svíček`}
            onPointerMove={onMove}
            onPointerLeave={() => setHover(null)}
            className={`cchart-svg ${up ? "is-up" : "is-down"}`}
          >
            <defs>
              <linearGradient id={`area-${code}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="currentColor" stopOpacity="0.22" />
                <stop offset="1" stopColor="currentColor" stopOpacity="0" />
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
                <text key={r[0]} x={x(i)} y={H - 8} className="cc-tick" textAnchor="middle">{timeLabel(r[0], tf, days[i])}</text>
              ) : null,
            )}
            {kind === "line" || data.data?.line_only ? (
              <g key={`${tf}-line`} className="cc-draw">
                <path d={`${linePath(4)}L${x(rows.length - 1)},${PAD.top + plotH}L${x(0)},${PAD.top + plotH}Z`} fill={`url(#area-${code})`} className="cc-area" />
                <path d={linePath(4)} className="cc-line" pathLength={1} />
              </g>
            ) : (
              <g key={`${tf}-candles`} className="cc-candles">
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
                <line x1={PAD.left} x2={W - PAD.right} y1={y(last[4])} y2={y(last[4])} className="cc-last" />
                <rect x={W - PAD.right + 2} y={y(last[4]) - 11} width={PAD.right - 4} height="22" rx="6" className="cc-last-tag" />
                <text x={W - PAD.right + 8} y={y(last[4]) + 4} className="cc-last-text">{fmt(last[4], digits)}</text>
              </g>
            )}
            {h && hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + plotH} className="cc-cross" />}
          </svg>
        )}
        {h && hover !== null && (
          <div className="cchart-tip" style={{ left: `${Math.min(80, (x(hover) / W) * 100)}%` }}>
            <strong>{timeLabel(h[0], tf === "D1" || tf === "W1" ? tf : "H1", hover !== null ? days[hover] : undefined)}</strong>
            <span>O {fmt(h[1], digits)} · H {fmt(h[2], digits)}</span>
            <span>L {fmt(h[3], digits)} · C {fmt(h[4], digits)}</span>
          </div>
        )}
      </div>
      <p className="cchart-foot">
        <MarketChip m={data.data?.market} /> <QualityBadge q={data.data?.quality} source={data.data?.source} /> {data.data?.source}
        {data.data?.last_quote && !data.data.last_quote.tradable_now && ` · poslední kotace ${data.data.last_quote.time_cs}`}
        {data.data?.kind_cs && ` · ${data.data.kind_cs}`}
        {data.data && ` · staženo ${relativeTime(data.data.fetched_at)}`}
      </p>
      {data.data?.notes && data.data.notes.length > 0 && (
        <ul className="cchart-notes">
          {[...new Set(data.data.notes)].map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
