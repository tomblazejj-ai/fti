import { useEffect, useRef, useState } from "react";

/** Animated number (eases from the previous value; no animation on the very first value). */
export function useCountUp(value: number, ms = 800): number {
  const [shown, setShown] = useState(value);
  const from = useRef<number | null>(null);
  useEffect(() => {
    const a = from.current;
    if (a === null || typeof requestAnimationFrame !== "function") {
      from.current = value;
      setShown(value);
      return;
    }
    const start = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / ms);
      setShown(a + (value - a) * (1 - (1 - k) ** 3));
      if (k < 1) raf = requestAnimationFrame(tick);
      else from.current = value;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, ms]);
  return shown;
}

export function scoreText(n: number): string {
  return n > 0 ? `+${n}` : n < 0 ? `−${Math.abs(n)}` : "0";
}

export function tone(n: number): "pos" | "neg" | "zero" {
  return n > 0 ? "pos" : n < 0 ? "neg" : "zero";
}

/** Score −10…+10 as a half-circle gauge whose needle swings in when it appears. */
export function ScoreGauge({ score, size = 120, label = true }: { score: number; size?: number; label?: boolean }) {
  const [drawn, setDrawn] = useState(0);
  useEffect(() => {
    const id = window.setTimeout(() => setDrawn(score), 60);
    return () => window.clearTimeout(id);
  }, [score]);
  const angle = (drawn / 10) * 90; // −90° … +90°
  const shown = Math.round(useCountUp(drawn, 900));
  const t = tone(score);
  return (
    <svg className={`gauge gauge-${t}`} width={size} height={(size * 96) / 120} viewBox="0 0 120 96" role="img" aria-label={`Skóre ${scoreText(score)} z 10`}>
      <defs>
        <linearGradient id="gauge-grad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" style={{ stopColor: "var(--down)" }} />
          <stop offset="0.5" style={{ stopColor: "var(--border)" }} />
          <stop offset="1" style={{ stopColor: "var(--up)" }} />
        </linearGradient>
      </defs>
      <path d="M12 60 A48 48 0 0 1 108 60" className="gauge-track" />
      <path d="M12 60 A48 48 0 0 1 108 60" className="gauge-arc" stroke="url(#gauge-grad)" pathLength={1} />
      <text x="12" y="74" textAnchor="middle" className="gauge-end">−10</text>
      <text x="108" y="74" textAnchor="middle" className="gauge-end">+10</text>
      <g className="gauge-needle" style={{ transform: `rotate(${angle}deg)` }}>
        <line x1="60" y1="60" x2="60" y2="24" />
        <circle cx="60" cy="60" r="5.5" />
      </g>
      {label && (
        <text x="60" y="92" textAnchor="middle" className="gauge-num">
          {scoreText(shown)}
        </text>
      )}
    </svg>
  );
}

const PAIR: Record<string, [string, string, string, string]> = {
  EURUSD: ["€", "$", "var(--accent)", "var(--up)"],
  GBPUSD: ["£", "$", "var(--warn)", "var(--up)"],
  USDJPY: ["$", "¥", "var(--up)", "var(--down)"],
};

/** Small picture for every market: gold bar, oil drop, or the two currencies. */
export function MarketIcon({ code, size = 40 }: { code: string; size?: number }) {
  if (code === "XAUUSD") {
    return (
      <svg width={size} height={size} viewBox="0 0 40 40" className="micon" aria-hidden="true">
        <circle cx="20" cy="20" r="19" style={{ fill: "var(--gold-bg)" }} />
        <path d="M11 25 L14 15 H26 L29 25 Z" style={{ fill: "var(--zone-gold)" }} />
        <path d="M14.8 17 H25.2 L25.8 19 H14.2 Z" style={{ fill: "var(--on-accent)" }} fillOpacity="0.45" />
      </svg>
    );
  }
  if (code === "USOIL") {
    return (
      <svg width={size} height={size} viewBox="0 0 40 40" className="micon" aria-hidden="true">
        <circle cx="20" cy="20" r="19" style={{ fill: "var(--surface-2)" }} />
        <path d="M20 9 C16 15 13 19 13 23 a7 7 0 0 0 14 0 C27 19 24 15 20 9 Z" style={{ fill: "var(--text)" }} />
        <path d="M17 23 a3 3 0 0 0 3 3" style={{ stroke: "var(--text-muted)" }} strokeWidth="1.6" fill="none" strokeLinecap="round" />
      </svg>
    );
  }
  const [a, b, ca, cb] = PAIR[code] ?? ["?", "?", "var(--text-muted)", "var(--text-muted)"];
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" className="micon" aria-hidden="true">
      <circle cx="15" cy="16" r="12" style={{ fill: ca }} />
      <circle cx="26" cy="25" r="12" style={{ fill: cb, stroke: "var(--surface)" }} strokeWidth="2" />
      <text x="15" y="20.5" textAnchor="middle" fontSize="12" fontWeight="800" style={{ fill: "var(--on-accent)" }}>{a}</text>
      <text x="26" y="29.5" textAnchor="middle" fontSize="12" fontWeight="800" style={{ fill: "var(--on-accent)" }}>{b}</text>
    </svg>
  );
}
