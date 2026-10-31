import type { CalendarEvent } from "./types";

// Funded Mind, "Fundamentální zprávy": never enter 2 h before a red (high-impact) release,
// after it wait until the market shows a direction. Recomputed in the browser every few
// seconds so the countdown is live between the 5-minute data refreshes.
export const LOCK_HOURS = 2;
export const CONFIRM_MINUTES = 60;

export interface LiveLock {
  state: "lock" | "after" | "clear";
  event: CalendarEvent | null;
  minutes: number | null; // to the release (lock) or since it (after)
  next: CalendarEvent | null; // the next red release, whatever the state
  minutesToNext: number | null;
}

export function newsLock(events: CalendarEvent[], now: Date, lockHours = LOCK_HOURS, confirmMinutes = CONFIRM_MINUTES): LiveLock {
  let after: LiveLock | null = null;
  let next: CalendarEvent | null = null;
  let minutesToNext: number | null = null;
  for (const e of events) {
    if (e.importance < 3 || !e.datetime) continue;
    const minutes = (new Date(e.datetime).getTime() - now.getTime()) / 60000;
    if (minutes > 0 && (minutesToNext === null || minutes < minutesToNext)) {
      next = e;
      minutesToNext = minutes;
    }
    if (minutes <= 0 && minutes >= -confirmMinutes && !after) {
      after = { state: "after", event: e, minutes: Math.floor(-minutes), next: null, minutesToNext: null };
    }
  }
  if (next && minutesToNext !== null && minutesToNext <= lockHours * 60) {
    return { state: "lock", event: next, minutes: Math.ceil(minutesToNext), next, minutesToNext };
  }
  if (after) return { ...after, next, minutesToNext };
  return { state: "clear", event: null, minutes: null, next, minutesToNext };
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
  return `${d} ${d >= 5 ? "dní" : "dny"}`;
}
