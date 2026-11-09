// Small charts for the KPI cards. They draw FTI's numbers as they are; colours come from CSS classes (theme tokens).

/** A line of values (e.g. daily closes); `compare` = a second line (e.g. the 50-day average). */
export function Sparkline({ values, compare, label }: { values: number[]; compare?: (number | null)[]; label: string }) {
  if (values.length < 2) return null;
  const all = [...values, ...(compare ?? []).filter((v): v is number => v !== null)];
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const span = hi - lo || 1;
  const W = 120;
  const H = 36;
  const x = (i: number, n: number) => (i / (n - 1)) * W;
  const y = (v: number) => H - 2 - ((v - lo) / span) * (H - 4);
  const path = values.map((v, i) => `${i ? "L" : "M"}${x(i, values.length).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const cmp = compare
    ? compare.map((v, i) => (v === null ? "" : `${i && compare[i - 1] !== null ? "L" : "M"}${x(i, compare.length).toFixed(1)},${y(v).toFixed(1)}`)).join("")
    : "";
  const up = values[values.length - 1] >= values[0];
  return (
    <svg className={`spark ${up ? "is-up" : "is-down"}`} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={label}>
      <path d={`${path}L${W},${H}L0,${H}Z`} className="spark-area" />
      {cmp && <path d={cmp} className="spark-cmp" />}
      <path d={path} className="spark-line" />
    </svg>
  );
}

/** A value on a scale with zero in the middle (e.g. score −10 … +10). */
export function CenterBar({ value, max, label }: { value: number; max: number; label: string }) {
  const w = Math.min(1, Math.abs(value) / max) * 50;
  const t = value > 0 ? "pos" : value < 0 ? "neg" : "zero";
  return (
    <span className="cbar" role="img" aria-label={label}>
      <i className={`cbar-fill ${t}`} style={{ width: `${w}%`, [value < 0 ? "right" : "left"]: "50%" }} />
      <i className="cbar-mid" />
    </span>
  );
}

/** A value 0 … 100 (e.g. the ATR percentile) with a marker. */
export function Meter({ value, label }: { value: number; label: string }) {
  const v = Math.max(0, Math.min(100, value));
  return (
    <span className="meter" role="img" aria-label={label}>
      <i className="meter-fill" style={{ width: `${v}%` }} />
      <i className="meter-mark" style={{ left: `${v}%` }} />
    </span>
  );
}

/** Counts side by side (e.g. how many quotes are LIVE, DELAYED, CLOSED, N/A). */
export function Segments({ parts, label }: { parts: { n: number; cls: string; title: string }[]; label: string }) {
  const total = parts.reduce((s, p) => s + p.n, 0) || 1;
  return (
    <span className="segs" role="img" aria-label={label}>
      {parts.filter((p) => p.n > 0).map((p) => (
        <i key={p.cls} className={`seg seg-${p.cls}`} style={{ flexGrow: p.n / total }} title={`${p.title}: ${p.n}`} />
      ))}
    </span>
  );
}
