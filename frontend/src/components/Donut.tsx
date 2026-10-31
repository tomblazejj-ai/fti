// Long vs. short ring (COT). Green = long, red = short; the ring animates in.
export function Donut({ long, short, label, sub, size = 150 }: { long: number; short: number; label: string; sub?: string; size?: number }) {
  const total = long + short;
  const r = 52;
  const c = 2 * Math.PI * r;
  const longShare = total > 0 ? long / total : 0;
  const pct = Math.round(longShare * 100);
  return (
    <figure className="donut" style={{ width: size }} aria-label={`${label}: long ${pct} %, short ${100 - pct} %`}>
      <svg viewBox="0 0 140 140" width={size} height={size} role="img">
        <circle cx="70" cy="70" r={r + 10} className="donut-halo" />
        <circle cx="70" cy="70" r={r} fill="none" stroke="var(--bear)" strokeWidth="18" />
        <circle
          cx="70"
          cy="70"
          r={r}
          fill="none"
          stroke="var(--bull)"
          strokeWidth="18"
          strokeDasharray={`${(longShare * c).toFixed(1)} ${c.toFixed(1)}`}
          transform="rotate(-90 70 70)"
          className="donut-long"
        />
        <circle cx="70" cy="70" r={r - 16} className="donut-hole" />
        <text x="70" y="68" textAnchor="middle" className="donut-pct">{pct} %</text>
        <text x="70" y="86" textAnchor="middle" className="donut-sub">long</text>
      </svg>
      <figcaption>
        <strong>{label}</strong>
        {sub && <span className="muted small">{sub}</span>}
      </figcaption>
    </figure>
  );
}
