// Small line-icon set (24×24, stroke = currentColor), drawn here so the app
// needs no icon font or CDN.
const PATHS: Record<string, string> = {
  home: "M3 11l9-7 9 7 M5 10v10h14V10 M10 20v-6h4v6",
  chart: "M3 3v18h18 M7 15l4-4 3 3 5-6",
  calendar: "M4 6h16v14H4z M4 10h16 M8 3v5 M16 3v5",
  news: "M4 5h13v14H6a2 2 0 0 1-2-2z M17 9h3v8a2 2 0 0 1-2 2 M7 9h7 M7 13h7",
  bolt: "M13 2L4 14h7l-1 8 9-12h-7z",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 7v5l3 2",
  line: "M3 17l5-6 4 4 4-7 5 5",
  globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M3 12h18 M12 3a14 14 0 0 1 0 18 M12 3a14 14 0 0 0 0 18",
  chevronLeft: "M15 18l-6-6 6-6",
  chevronRight: "M9 18l6-6-6-6",
  chevronDown: "M6 9l6 6 6-6",
  external: "M14 4h6v6 M20 4l-9 9 M18 14v6H4V6h6",
  arrowUp: "M12 19V5 M5 12l7-7 7 7",
  arrowDown: "M12 5v14 M19 12l-7 7-7-7",
  users: "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M2 21a7 7 0 0 1 14 0 M17 4a4 4 0 0 1 0 7 M19 21a6 6 0 0 0-3-5",
  layers: "M12 3l9 5-9 5-9-5z M3 13l9 5 9-5",
  spark: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z",
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

/** The app's mark: three candles and a rising line on a blue tile. */
export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="brand-mark">
      <defs>
        <linearGradient id="bm-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#2563eb" />
          <stop offset="1" stopColor="#4f46e5" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#bm-bg)" />
      <path d="M9 10v14 M16 7v17 M23 5v13" stroke="#bfdbfe" strokeWidth="1.4" strokeLinecap="round" />
      <rect x="7" y="14" width="4" height="7" rx="1" fill="#fff" />
      <rect x="14" y="11" width="4" height="9" rx="1" fill="#fff" />
      <rect x="21" y="7" width="4" height="8" rx="1" fill="#fff" />
      <path d="M5 26 L12 22 L18 23 L27 15" stroke="#34d399" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
