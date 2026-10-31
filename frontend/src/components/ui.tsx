import type { ReactNode } from "react";
import {
  DIRECTION_LABELS,
  IMPACT_LABELS,
  LONG_THRESHOLD,
  QUALITY_LABELS,
  SHORT_THRESHOLD,
  relativeTime,
  scoreText,
  signed,
} from "../lib/format";
import type { DataQuality, Direction, Impact } from "../lib/types";

const DIRECTION_ICON: Record<Direction, string> = { BULLISH: "▲", BEARISH: "▼", NEUTRAL: "●" };
const IMPACT_ICON: Record<Impact, string> = { bullish: "▲", bearish: "▼", neutral: "●" };
const QUALITY_ICON: Record<DataQuality, string> = { ok: "✓", partial: "◐", unavailable: "⊘" };

// Color never carries meaning alone: every state is icon + word + color.
export function DirectionBadge({ direction, size = "md" }: { direction: Direction; size?: "sm" | "md" | "lg" }) {
  return (
    <span className={`badge badge-${size} tone-${direction.toLowerCase()}`}>
      <span aria-hidden="true">{DIRECTION_ICON[direction]}</span> {DIRECTION_LABELS[direction]}
    </span>
  );
}

export function ImpactTag({ impact }: { impact: Impact }) {
  return (
    <span className={`tag tone-${impact}`}>
      <span aria-hidden="true">{IMPACT_ICON[impact]}</span> {IMPACT_LABELS[impact]}
    </span>
  );
}

export function QualityTag({ quality }: { quality: DataQuality }) {
  return (
    <span className={`tag quality-${quality}`}>
      <span aria-hidden="true">{QUALITY_ICON[quality]}</span> {QUALITY_LABELS[quality]}
    </span>
  );
}

/**
 * Diverging 0–100 meter. The neutral midpoint (50) is the anchor; the fill
 * runs from 50 toward the score. Bias thresholds (35 / 65) are drawn so the
 * reader can see how far the score is from flipping.
 */
export function ScoreMeter({ score, compact = false }: { score: number; compact?: boolean }) {
  const clamped = Math.max(0, Math.min(100, score));
  const from = Math.min(50, clamped);
  const to = Math.max(50, clamped);
  const tone = clamped >= LONG_THRESHOLD ? "bullish" : clamped <= SHORT_THRESHOLD ? "bearish" : clamped > 50 ? "lean-bull" : clamped < 50 ? "lean-bear" : "neutral";
  return (
    <div
      className={`meter ${compact ? "meter-compact" : ""}`}
      role="img"
      aria-label={`Skóre ${scoreText(score)} ze 100; SHORT při ${SHORT_THRESHOLD} a méně, LONG při ${LONG_THRESHOLD} a více`}
    >
      <div className="meter-track">
        <div className="meter-zone meter-zone-short" style={{ width: `${SHORT_THRESHOLD}%` }} />
        <div className="meter-zone meter-zone-long" style={{ left: `${LONG_THRESHOLD}%`, width: `${100 - LONG_THRESHOLD}%` }} />
        <div className={`meter-fill fill-${tone}`} style={{ left: `${from}%`, width: `${to - from}%` }} />
        <div className="meter-mid" />
        <div className="meter-marker" style={{ left: `${clamped}%` }} />
      </div>
      {!compact && (
        <div className="meter-scale" aria-hidden="true">
          <span style={{ left: "0%" }}>0</span>
          <span style={{ left: `${SHORT_THRESHOLD}%` }}>SHORT ≤{SHORT_THRESHOLD}</span>
          <span style={{ left: "50%" }}>50</span>
          <span style={{ left: `${LONG_THRESHOLD}%` }}>LONG ≥{LONG_THRESHOLD}</span>
          <span style={{ left: "100%" }}>100</span>
        </div>
      )}
    </div>
  );
}

/** A −1…+1 value as a small diverging bar around a zero line. */
export function SignalBar({ value }: { value: number }) {
  const v = Math.max(-1, Math.min(1, value));
  const width = Math.abs(v) * 50;
  const tone = v > 0.05 ? "bullish" : v < -0.05 ? "bearish" : "neutral";
  return (
    <span className="signal-bar" role="img" aria-label={`${signed(v, 2)} na stupnici −1 až +1`}>
      <span className="signal-track" />
      <span className={`signal-fill fill-${tone}`} style={{ left: `${v >= 0 ? 50 : 50 - width}%`, width: `${width}%` }} />
      <span className="signal-zero" />
    </span>
  );
}

/** Signed contribution inside the pillar's own ±weight capacity. */
export function ContributionBar({ points, weight, unavailable }: { points: number; weight: number; unavailable?: boolean }) {
  if (unavailable) {
    return (
      <div className="contrib contrib-na" role="img" aria-label="Nehodnoceno: chybí použitelná data">
        <div className="contrib-track" />
      </div>
    );
  }
  const pct = weight ? Math.min(1, Math.abs(points) / weight) * 50 : 0;
  const left = points >= 0 ? 50 : 50 - pct;
  const tone = points > 0.05 ? "bullish" : points < -0.05 ? "bearish" : "neutral";
  return (
    <div className="contrib" role="img" aria-label={`${signed(points)} z ±${weight} bodů`} title={`${signed(points)} z ±${weight} b.`}>
      <div className="contrib-track" />
      <div className={`contrib-fill fill-${tone}`} style={{ left: `${left}%`, width: `${pct}%` }} />
      <div className="contrib-zero" />
    </div>
  );
}

export function Section({ id, title, subtitle, actions, children, className = "" }: {
  id?: string;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={`card section ${className}`} aria-labelledby={id ? `${id}-title` : undefined}>
      <header className="section-head">
        <div>
          <h2 id={id ? `${id}-title` : undefined}>{title}</h2>
          {subtitle && <p className="section-sub">{subtitle}</p>}
        </div>
        {actions && <div className="section-actions">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

export function Loading({ label = "Načítám…" }: { label?: string }) {
  return (
    <div className="state state-loading" role="status">
      <span className="spinner" aria-hidden="true" /> {label}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <strong>Data se nepodařilo načíst.</strong> <span>{message}</span>
      {onRetry && (
        <button type="button" className="btn btn-ghost" onClick={onRetry}>
          Zkusit znovu
        </button>
      )}
    </div>
  );
}

export function Unavailable({ children }: { children: ReactNode }) {
  return (
    <div className="state state-unavailable">
      <span aria-hidden="true">⊘</span> {children}
    </div>
  );
}

export function ExternalLink({ href, children }: { href: string | null; children: ReactNode }) {
  if (!href) return <>{children}</>;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

/** Shown instead of pretending old numbers are current. */
export function StaleNotice({ computedAt, running }: { computedAt: string; running: boolean }) {
  return (
    <p className="stale-notice" role="status">
      <span aria-hidden="true">⚠</span> Data jsou stará ({relativeTime(computedAt).replace("před ", "")}) —{" "}
      {running
        ? "právě stahuji aktuální, výhled se sám obnoví asi do minuty."
        : "aktuální se nepodařilo stáhnout. Klikni na „Obnovit data“."}
    </p>
  );
}
