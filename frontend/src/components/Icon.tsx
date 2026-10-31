// Small line-icon set (24×24, stroke = currentColor), drawn here so the app
// needs no icon font or CDN.
const PATHS: Record<string, string> = {
  chart: "M3 3v18h18 M7 15l4-4 3 3 5-6",
  candles: "M7 4v3 M7 15v5 M5 7h4v8H5z M17 3v5 M17 14v6 M15 8h4v6h-4z",
  gauge: "M4 18a8 8 0 1 1 16 0 M12 18l4-6",
  calendar: "M4 6h16v14H4z M4 10h16 M8 3v5 M16 3v5",
  news: "M4 5h13v14H6a2 2 0 0 1-2-2z M17 9h3v8a2 2 0 0 1-2 2 M7 9h7 M7 13h7",
  users: "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M2 21a7 7 0 0 1 14 0 M17 4a4 4 0 0 1 0 7 M19 21a6 6 0 0 0-3-5",
  target: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M12 12h.01",
  sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z M19 16l.7 1.8 1.8.7-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7z",
  layers: "M12 3l9 5-9 5-9-5z M3 13l9 5 9-5",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z M12 1v2 M12 21v2 M4.2 4.2l1.4 1.4 M18.4 18.4l1.4 1.4 M1 12h2 M21 12h2 M4.2 19.8l1.4-1.4 M18.4 5.6l1.4-1.4",
  bank: "M3 10l9-6 9 6 M5 10v8 M9 10v8 M15 10v8 M19 10v8 M3 20h18",
  bolt: "M13 2L4 14h7l-1 8 9-12h-7z",
  arrowUp: "M12 19V5 M5 12l7-7 7 7",
  arrowDown: "M12 5v14 M19 12l-7 7-7-7",
  chevronLeft: "M15 18l-6-6 6-6",
  chevronRight: "M9 18l6-6-6-6",
  refresh: "M21 12a9 9 0 1 1-3-6.7 M21 4v5h-5",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 11v6 M12 7h.01",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 7v5l3 2",
  line: "M3 17l5-6 4 4 4-7 5 5",
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 18, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {PATHS[name].split(" M").map((d, i) => (
        <path key={i} d={i === 0 ? d : `M${d}`} />
      ))}
    </svg>
  );
}

/** The app's mark: a small gold bar. */
export function GoldMark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <defs>
        <linearGradient id="gm-top" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffe39a" />
          <stop offset="1" stopColor="#e2a72e" />
        </linearGradient>
        <linearGradient id="gm-side" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#c98a1c" />
          <stop offset="1" stopColor="#8a5a0c" />
        </linearGradient>
      </defs>
      <path d="M9 9h14l5 10H4z" fill="url(#gm-top)" />
      <path d="M4 19h24v4H4z" fill="url(#gm-side)" />
      <path d="M11 11h10" stroke="#fff6d5" strokeWidth="1.2" strokeLinecap="round" opacity="0.8" />
    </svg>
  );
}
