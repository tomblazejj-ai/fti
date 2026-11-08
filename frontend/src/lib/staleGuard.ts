/**
 * The phone version reads the snapshot the PC last sent. A label like "živá kotace" was true when the
 * PC computed it, but it must not stay on the screen hours later while the PC is off. Before the app
 * shows a snapshot, every price whose quote time is older than the limit is downgraded to STALE with
 * its real time — the app never presents an old price as current.
 */

const CURRENT = new Set(["LIVE", "NEAR_REAL_TIME", "INDICATIVE"]);
export const STALE_AFTER_MIN = 20;

type Json = Record<string, unknown>;

function quoteTime(o: Json): string | null {
  const lq = o.last_quote as Json | undefined;
  const q = o.quality as Json | undefined;
  return (lq?.time as string) ?? (q?.as_of as string) ?? (o.as_of as string) ?? null;
}

function downgrade(o: Json, at: string): void {
  const lq = o.last_quote as Json | undefined;
  const timeCs = (lq?.time_cs as string) ?? (o.quote_time_cs as string) ?? new Date(at).toLocaleString("cs-CZ");
  const text = `Poslední kotace ${timeCs} — novější data z FTI na PC zatím nepřišla, cena není aktuální.`;
  o.quality = { ...(o.quality as Json), status: "STALE", label: "zastaralé", text };
  if (lq) o.last_quote = { ...lq, tradable_now: false, note: text };
  if (o.live === true) o.live = false;
}

/** Walks the snapshot and downgrades every outdated "live" price. Returns the same object. */
export function guardStale<T>(body: T, now: Date = new Date(), limitMin = STALE_AFTER_MIN): T {
  const visit = (node: unknown): void => {
    if (Array.isArray(node)) {
      node.forEach(visit);
      return;
    }
    if (!node || typeof node !== "object") return;
    const o = node as Json;
    const q = o.quality as Json | undefined;
    if (q && typeof q.status === "string" && CURRENT.has(q.status)) {
      const at = quoteTime(o);
      const age = at ? (now.getTime() - new Date(at).getTime()) / 60000 : Infinity;
      if (!(age <= limitMin)) downgrade(o, at ?? now.toISOString());
    }
    Object.values(o).forEach(visit);
  };
  visit(body);
  return body;
}
