import { useEffect, useState } from "react";

// Half-circle speedometer, −10 … +10. Five coloured zones like a car gauge;
// the needle sweeps in on mount (disabled with prefers-reduced-motion in CSS).
const ZONES = [
  { from: -10, to: -6, color: "var(--bear)", label: "Silně medvědí" },
  { from: -6, to: -2, color: "var(--orange)", label: "Medvědí" },
  { from: -2, to: 2, color: "var(--yellow)", label: "Neutrální" },
  { from: 2, to: 6, color: "var(--teal)", label: "Býčí" },
  { from: 6, to: 10, color: "var(--bull)", label: "Silně býčí" },
];

const CX = 160;
const CY = 160;
const R = 120;

function angle(v: number): number {
  return Math.PI * (1 - (v + 10) / 20); // −10 → 180°, +10 → 0°
}

function point(v: number, r: number): [number, number] {
  const a = angle(v);
  return [CX + r * Math.cos(a), CY - r * Math.sin(a)];
}

function arc(from: number, to: number, r: number): string {
  const [x1, y1] = point(from, r);
  const [x2, y2] = point(to, r);
  return `M${x1.toFixed(1)},${y1.toFixed(1)} A${r},${r} 0 0 1 ${x2.toFixed(1)},${y2.toFixed(1)}`;
}

export function zoneOf(v: number) {
  return ZONES.find((z) => v >= z.from && v < z.to) ?? (v >= 10 ? ZONES[4] : ZONES[0]);
}

export function Gauge({ value, caption }: { value: number; caption?: string }) {
  const v = Math.max(-10, Math.min(10, value));
  const [shown, setShown] = useState(-10);
  useEffect(() => {
    const id = window.setTimeout(() => setShown(v), 60);
    return () => window.clearTimeout(id);
  }, [v]);
  const zone = zoneOf(v);
  const rot = 90 - (angle(shown) * 180) / Math.PI; // needle drawn pointing up (0)
  return (
    <figure className="gauge" aria-label={`${caption ?? "Skóre"}: ${v < 0 ? `−${Math.abs(v)}` : v > 0 ? `+${v}` : "0"} z ±10, ${zone.label}`}>
      <svg viewBox="0 0 320 200" role="img">
        {ZONES.map((z) => (
          <path key={z.from} d={arc(z.from + 0.15, z.to - 0.15, R)} stroke={z.color} strokeWidth="10" fill="none" strokeLinecap="round" />
        ))}
        {Array.from({ length: 21 }, (_, i) => i - 10).map((t) => {
          const [x1, y1] = point(t, R - 16);
          const [x2, y2] = point(t, R - (t % 5 === 0 ? 30 : 23));
          return <line key={t} x1={x1} y1={y1} x2={x2} y2={y2} className={`gauge-tick${t % 5 === 0 ? " major" : ""}`} />;
        })}
        <text x={point(-10, R + 4)[0] - 4} y={CY + 22} className="gauge-end" textAnchor="start">−10</text>
        <text x={point(10, R + 4)[0] + 4} y={CY + 22} className="gauge-end" textAnchor="end">+10</text>
        <g className="gauge-needle" style={{ transform: `rotate(${rot}deg)`, transformOrigin: `${CX}px ${CY}px` }}>
          <path d={`M${CX - 7},${CY - 64} L${CX},${CY - 92} L${CX + 7},${CY - 64} Z`} fill="var(--text)" />
        </g>
        <path d={arc(-10, 10, 60)} stroke="var(--border-strong)" strokeWidth="1" fill="none" />
        <text x={CX} y={CY - 6} textAnchor="middle" className="gauge-value" fill={zone.color}>
          {v > 0 ? `+${v}` : v < 0 ? `−${Math.abs(v)}` : "0"}
        </text>
        <text x={CX} y={CY + 26} textAnchor="middle" className="gauge-label" fill={zone.color}>
          {zone.label}
        </text>
      </svg>
      {caption && <figcaption className="muted small">{caption}</figcaption>}
    </figure>
  );
}
