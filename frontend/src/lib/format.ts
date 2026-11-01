export const LOCALE = "cs-CZ";

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(LOCALE, { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** "2026-09-25" -> "25. 9. 2026" */
export function shortDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  const [y, m, d] = isoDate.slice(0, 10).split("-").map(Number);
  return y && m && d ? `${d}. ${m}. ${y}` : isoDate;
}

/** Czech plural: 1 den, 2–4 dny, 5+ dní. */
export function plural(n: number, one: string, few: string, many: string): string {
  if (n === 1) return one;
  if (n >= 2 && n <= 4) return few;
  return many;
}

export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "nikdy";
  const diffMs = now.getTime() - new Date(iso).getTime();
  const future = diffMs < 0;
  const mins = Math.round(Math.abs(diffMs) / 60000);
  if (mins < 1) return future ? "za chvíli" : "právě teď";
  let text: string;
  if (mins < 60) text = `${mins} min`;
  else if (mins < 60 * 48) text = `${Math.round(mins / 60)} h`;
  else {
    const days = Math.round(mins / 1440);
    text = future ? `${days} ${plural(days, "den", "dny", "dní")}` : `${days} ${plural(days, "dnem", "dny", "dny")}`;
  }
  return future ? `za ${text}` : `před ${text}`;
}

/** "1 h 25 min", "25 min", "3 dny" — for the countdowns. */
export function countdown(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  if (m < 60) return `${m} min`;
  if (m < 48 * 60) {
    const h = Math.floor(m / 60);
    const rest = m % 60;
    return rest ? `${h} h ${rest} min` : `${h} h`;
  }
  const d = Math.round(m / 1440);
  return `${d} ${plural(d, "den", "dny", "dní")}`;
}

/** Price with the market's decimals, Czech style ("4 012,35"). */
export function price(v: number | null | undefined, digits: number): string {
  if (v === undefined || v === null) return "—";
  const d = digits > 3 ? 4 : digits;
  return v.toLocaleString(LOCALE, { minimumFractionDigits: d, maximumFractionDigits: d });
}

/** "+0,42 %" / "−1,10 %" with a real minus sign. */
export function pct(v: number): string {
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toLocaleString(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} %`;
}
