/**
 * FTI cloud Worker (variant A).
 *
 * The Python engine on the user's PC stays the only place where FTI computes. After each cycle it
 * uploads the snapshot files the phone app reads; this Worker keeps them in D1 and serves them at
 * /data/<file>.json next to the phone build of the app — so the phone works even when the PC is off,
 * always showing when the PC computed the data.
 *
 *   GET  /internal/manifest            name → SHA-256 of what D1 holds (the PC uploads only changes)
 *   PUT  /internal/snapshot/<file>     one file, raw JSON text (header X-Sha256, X-Computed-At)
 *   POST /internal/sync-done           a summary row for the sync log
 *   GET  /data/<file>.json             the stored file (public, like the phone version today)
 *   GET  /api/cloud/status             when the PC last delivered results
 *   everything else                    the static phone app
 *
 * /internal/* needs the SYNC_TOKEN secret (the PC) or a GitHub Actions OIDC token of GITHUB_REPO's main branch
 * (the cloud run every 30 minutes — no password stored in GitHub, see ./oidc.ts). The Worker never parses the big files (Workers Free gives
 * 10 ms of CPU per request): it stores the text as it came.
 */

import { type FetchJwks, fetchJwks, verifyGithubOidc } from "./oidc";

export interface Env {
  DB: D1Database;
  ASSETS: Fetcher;
  SYNC_TOKEN?: string;
  GITHUB_REPO?: string; // e.g. "tomblazejj-ai/fti" — whose GitHub Actions may write
  GITHUB_DISPATCH_TOKEN?: string; // secret: starts the cloud run every 30 minutes (./dispatch.ts)
  GITHUB_WORKFLOW?: string;
  OIDC_AUDIENCE?: string;
}

export const OIDC_EVENTS = ["schedule", "workflow_dispatch", "push"];

export interface Row {
  body: string;
  synced_at: string;
  computed_at: string | null;
}

export interface SyncEntry {
  at: string;
  uploaded: number;
  unchanged: number;
  bytes: number;
  problems: number;
  computed_at: string | null;
}

export interface Store {
  manifest(): Promise<Record<string, string>>;
  count(): Promise<number>;
  has(name: string): Promise<boolean>;
  put(name: string, body: string, sha: string, computedAt: string | null, syncedAt: string): Promise<void>;
  get(name: string): Promise<Row | null>;
  logSync(entry: SyncEntry, pruneBefore: string): Promise<void>;
  lastSync(): Promise<SyncEntry | null>;
}

export const MAX_BYTES = 1_900_000; // one D1 row holds at most 2 000 000 bytes
export const MAX_FILES = 60;
const NAME = /^[A-Za-z0-9][A-Za-z0-9.\-]{0,80}\.json$/;
const SHA = /^[0-9a-f]{64}$/;
const KEEP_LOG_DAYS = 30;

export function d1Store(db: D1Database): Store {
  return {
    async manifest() {
      const { results } = await db.prepare("SELECT name, sha FROM snapshots").all<{ name: string; sha: string }>();
      return Object.fromEntries(results.map((r) => [r.name, r.sha]));
    },
    async count() {
      return (await db.prepare("SELECT COUNT(*) AS n FROM snapshots").first<number>("n")) ?? 0;
    },
    async has(name) {
      return (await db.prepare("SELECT 1 AS x FROM snapshots WHERE name = ?").bind(name).first("x")) !== null;
    },
    async put(name, body, sha, computedAt, syncedAt) {
      await db
        .prepare(
          "INSERT INTO snapshots (name, body, sha, computed_at, synced_at) VALUES (?, ?, ?, ?, ?) " +
            "ON CONFLICT(name) DO UPDATE SET body = excluded.body, sha = excluded.sha, " +
            "computed_at = excluded.computed_at, synced_at = excluded.synced_at",
        )
        .bind(name, body, sha, computedAt, syncedAt)
        .run();
    },
    async get(name) {
      return await db.prepare("SELECT body, synced_at, computed_at FROM snapshots WHERE name = ?").bind(name).first<Row>();
    },
    async logSync(e, pruneBefore) {
      await db.batch([
        db
          .prepare("INSERT INTO sync_log (at, uploaded, unchanged, bytes, problems, computed_at) VALUES (?, ?, ?, ?, ?, ?)")
          .bind(e.at, e.uploaded, e.unchanged, e.bytes, e.problems, e.computed_at),
        db.prepare("DELETE FROM sync_log WHERE at < ?").bind(pruneBefore),
      ]);
    },
    async lastSync() {
      return await db
        .prepare("SELECT at, uploaded, unchanged, bytes, problems, computed_at FROM sync_log ORDER BY id DESC LIMIT 1")
        .first<SyncEntry>();
    },
  };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

/** Constant-time comparison, so the token cannot be guessed from response times. */
export function sameSecret(given: string, expected: string): boolean {
  const a = new TextEncoder().encode(given);
  const b = new TextEncoder().encode(expected);
  if (a.length === 0 || a.length !== b.length) return false; // reveals only the length, which is fixed anyway
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

function authorized(req: Request, token: string | undefined): boolean {
  if (!token || token.length < 32) return false; // no secret set = nobody may write
  const header = req.headers.get("authorization") ?? "";
  return header.startsWith("Bearer ") && sameSecret(header.slice(7), token);
}

async function allowed(req: Request, env: Env, now: Date, jwks: FetchJwks): Promise<boolean> {
  if (authorized(req, env.SYNC_TOKEN)) return true;
  const header = req.headers.get("authorization") ?? "";
  if (!env.GITHUB_REPO || !header.startsWith("Bearer ")) return false;
  return verifyGithubOidc(header.slice(7), { repository: env.GITHUB_REPO, ref: "refs/heads/main",
                                              audience: env.OIDC_AUDIENCE ?? "fti-cloud", events: OIDC_EVENTS }, now, jwks);
}

async function internal(req: Request, env: Env, store: Store, path: string, now: Date, jwks: FetchJwks): Promise<Response> {
  if (!(await allowed(req, env, now, jwks))) return json({ error: "unauthorized" }, 401);
  if (path === "/internal/manifest" && req.method === "GET") return json({ files: await store.manifest() });
  const m = path.match(/^\/internal\/snapshot\/(.+)$/);
  if (m && req.method === "PUT") {
    const name = decodeURIComponent(m[1]);
    const sha = req.headers.get("x-sha256") ?? "";
    if (!NAME.test(name) || !SHA.test(sha)) return json({ error: "bad name or hash" }, 400);
    if (Number(req.headers.get("content-length") ?? 0) > MAX_BYTES) return json({ error: "too large" }, 413);
    if (!(await store.has(name)) && (await store.count()) >= MAX_FILES) return json({ error: "too many files" }, 400);
    const body = await req.text();
    if (new TextEncoder().encode(body).length > MAX_BYTES) return json({ error: "too large" }, 413);
    await store.put(name, body, sha, req.headers.get("x-computed-at"), now.toISOString());
    return json({ ok: true });
  }
  if (path === "/internal/sync-done" && req.method === "POST") {
    const b = (await req.json().catch(() => ({}))) as Partial<SyncEntry>;
    const n = (v: unknown) => (Number.isFinite(Number(v)) ? Math.max(0, Math.trunc(Number(v))) : 0);
    const prune = new Date(now.getTime() - KEEP_LOG_DAYS * 86_400_000).toISOString();
    await store.logSync(
      { at: now.toISOString(), uploaded: n(b.uploaded), unchanged: n(b.unchanged), bytes: n(b.bytes), problems: n(b.problems),
        computed_at: typeof b.computed_at === "string" ? b.computed_at.slice(0, 40) : null },
      prune,
    );
    return json({ ok: true });
  }
  return json({ error: "not found" }, 404);
}

export async function handle(req: Request, env: Env, store: Store, now: Date = new Date(), jwks: FetchJwks = fetchJwks): Promise<Response> {
  const path = new URL(req.url).pathname;
  if (path.startsWith("/internal/")) return internal(req, env, store, path, now, jwks);
  if (path.startsWith("/data/") && (req.method === "GET" || req.method === "HEAD")) {
    const name = decodeURIComponent(path.slice("/data/".length));
    if (!NAME.test(name)) return json({ detail: "Neznámý soubor." }, 404);
    const row = await store.get(name);
    if (!row) return json({ detail: "Data ještě nejsou v cloudu — přijdou po nejbližším běhu (každých 30 minut)." }, 404);
    return new Response(req.method === "HEAD" ? null : row.body, {
      headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-cache",
                 "x-fti-synced-at": row.synced_at, ...(row.computed_at ? { "x-fti-computed-at": row.computed_at } : {}) },
    });
  }
  if (path === "/api/cloud/status" && req.method === "GET") {
    return json({ last_sync: await store.lastSync(), checked_at: now.toISOString() });
  }
  if (path.startsWith("/api/")) return json({ detail: "Tahle část v cloudové verzi zatím není." }, 404);
  return env.ASSETS.fetch(req);
}
