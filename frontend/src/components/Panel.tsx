import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

/** The dashboard tile: title + instrument tag, optional actions, body. */
export function Panel({
  title,
  tag,
  icon,
  actions,
  note,
  className = "",
  children,
  id,
}: {
  title: string;
  tag?: string;
  icon?: IconName;
  actions?: ReactNode;
  note?: ReactNode;
  className?: string;
  children: ReactNode;
  id?: string;
}) {
  const headingId = id ? `${id}-title` : undefined;
  return (
    <section className={`panel ${className}`} aria-labelledby={headingId} id={id}>
      <header className="panel-head">
        <h2 id={headingId} className="panel-title">
          {icon && (
            <span className="panel-icon">
              <Icon name={icon} size={16} />
            </span>
          )}
          {title}
          {tag && <span className="panel-tag">{tag}</span>}
        </h2>
        <div className="panel-actions">
          {note && <span className="panel-note">{note}</span>}
          {actions}
        </div>
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}

/** Pill switch (time frames, chart type, tabs inside a panel). */
export function Pills<T extends string>({
  options,
  value,
  onChange,
  label,
  size = "sm",
}: {
  options: { value: T; label: ReactNode; title?: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
  size?: "sm" | "md";
}) {
  return (
    <div className={`pills pills-${size}`} role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className={`pill${o.value === value ? " is-active" : ""}`}
          aria-pressed={o.value === value}
          title={o.title}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** −5…+5 (or any signed integer) score chip, green/red/grey. */
export function ScoreChip({ value, big = false }: { value: number | null; big?: boolean }) {
  if (value === null) return <span className={`score-chip is-na${big ? " big" : ""}`} title="data nejsou k dispozici">—</span>;
  const tone = value > 0 ? "pos" : value < 0 ? "neg" : "zero";
  return (
    <span className={`score-chip is-${tone}${big ? " big" : ""}`}>
      {value > 0 ? `+${value}` : value < 0 ? `−${Math.abs(value)}` : "0"}
    </span>
  );
}
