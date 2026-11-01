import type { CSSProperties, ReactNode } from "react";

export function Loading({ label = "Načítám…" }: { label?: string }) {
  return (
    <div className="state state-loading" role="status">
      <span className="spinner" aria-hidden="true" /> {label}
    </div>
  );
}

/** Grey placeholder blocks while the first data arrive. */
export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="skeleton" aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <span key={i} />
      ))}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <strong>Data se nepodařilo načíst.</strong> <span>{message}</span>
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Zkusit znovu
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

/** Pill switch (filters, time frames, chart type). */
export function Pills<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: ReactNode; title?: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="pills" role="group" aria-label={label}>
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

/** A white card with a small heading; `i` staggers the fade-in. */
export function Card({ title, icon, extra, i = 0, className = "", children, id }: {
  title?: ReactNode;
  icon?: ReactNode;
  extra?: ReactNode;
  i?: number;
  className?: string;
  children: ReactNode;
  id?: string;
}) {
  return (
    <section className={`card rise ${className}`} style={{ "--i": i } as CSSProperties} id={id} aria-labelledby={id && title ? `${id}-h` : undefined}>
      {title && (
        <header className="card-head">
          <h2 id={id ? `${id}-h` : undefined}>
            {icon && <span className="card-ico">{icon}</span>}
            {title}
          </h2>
          {extra}
        </header>
      )}
      {children}
    </section>
  );
}
