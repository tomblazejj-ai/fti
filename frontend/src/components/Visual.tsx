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
          <stop offset="0" stopColor="#f87171" />
          <stop offset="0.5" stopColor="#cbd5e1" />
          <stop offset="1" stopColor="#34d399" />
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
  EURUSD: ["€", "$", "#2563eb", "#0f766e"],
  GBPUSD: ["£", "$", "#7c3aed", "#0f766e"],
  USDJPY: ["$", "¥", "#0f766e", "#dc2626"],
};

/** Small picture for every market: gold bar, oil drop, or the two currencies. */
export function MarketIcon({ code, size = 40 }: { code: string; size?: number }) {
  if (code === "XAUUSD") {
    return (
      <svg width={size} height={size} viewBox="0 0 40 40" className="micon" aria-hidden="true">
        <circle cx="20" cy="20" r="19" fill="#fef3c7" />
        <path d="M11 25 L14 15 H26 L29 25 Z" fill="#f59e0b" />
        <path d="M14.8 17 H25.2 L25.8 19 H14.2 Z" fill="#fde68a" />
      </svg>
    );
  }
  if (code === "USOIL") {
    return (
      <svg width={size} height={size} viewBox="0 0 40 40" className="micon" aria-hidden="true">
        <circle cx="20" cy="20" r="19" fill="#e2e8f0" />
        <path d="M20 9 C16 15 13 19 13 23 a7 7 0 0 0 14 0 C27 19 24 15 20 9 Z" fill="#1e293b" />
        <path d="M17 23 a3 3 0 0 0 3 3" stroke="#94a3b8" strokeWidth="1.6" fill="none" strokeLinecap="round" />
      </svg>
    );
  }
  const [a, b, ca, cb] = PAIR[code] ?? ["?", "?", "#64748b", "#64748b"];
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" className="micon" aria-hidden="true">
      <circle cx="15" cy="16" r="12" fill={ca} />
      <circle cx="26" cy="25" r="12" fill={cb} stroke="#fff" strokeWidth="2" />
      <text x="15" y="20.5" textAnchor="middle" fontSize="12" fontWeight="800" fill="#fff">{a}</text>
      <text x="26" y="29.5" textAnchor="middle" fontSize="12" fontWeight="800" fill="#fff">{b}</text>
    </svg>
  );
}
