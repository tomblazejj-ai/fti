import { useCallback } from "react";
import { useAsync, useInterval } from "../hooks/useAsync";
import { api } from "../lib/api";

const W = 600;
const H = 90;

/** Small live price line (last ~60 H4 closes) for the dashboard cards. */
export function Sparkline({ code, tf = "H4" }: { code: string; tf?: string }) {
  const data = useAsync(() => api.candles(code, tf), [code, tf]);
  const reload = useCallback(() => data.reload(), [data.reload]);
  useInterval(reload, 60000);
  const closes = (data.data?.candles ?? []).slice(-60).map((r) => r[4]);
  if (closes.length < 2) return <div className="spark spark-empty" aria-hidden="true" />;
  const lo = Math.min(...closes);
  const hi = Math.max(...closes);
  const x = (i: number) => (i / (closes.length - 1)) * W;
  const y = (v: number) => 6 + (1 - (v - lo) / (hi - lo || 1)) * (H - 12);
  const d = closes.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const up = closes[closes.length - 1] >= closes[0];
  const color = up ? "var(--bull)" : "var(--bear)";
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
         aria-label={`Cena ${code} za posledních ${closes.length} svíček ${tf}: ${up ? "roste" : "klesá"}`}>
      <defs>
        <linearGradient id={`spark-${code}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.35" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${d}L${W},${H}L0,${H}Z`} fill={`url(#spark-${code})`} />
      <path d={d} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" className="spark-line" />
    </svg>
  );
}
