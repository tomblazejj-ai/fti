import { describe, expect, it } from "vitest";
import { type Env, MAX_BYTES, MAX_FILES, type Row, type Store, type SyncEntry, handle, sameSecret } from "../src/app";

const TOKEN = "t".repeat(64);
const SHA = "a".repeat(64);
const NOW = new Date("2026-11-02T10:00:00Z");

function memoryStore(): Store & { rows: Map<string, Row & { sha: string }>; log: SyncEntry[] } {
  const rows = new Map<string, Row & { sha: string }>();
  const log: SyncEntry[] = [];
  return {
    rows,
    log,
    async manifest() {
      return Object.fromEntries([...rows].map(([k, v]) => [k, v.sha]));
    },
    async count() {
      return rows.size;
    },
    async has(name) {
      return rows.has(name);
    },
    async put(name, body, sha, computed_at, synced_at) {
      rows.set(name, { body, sha, computed_at, synced_at });
    },
    async get(name) {
      return rows.get(name) ?? null;
    },
    async logSync(e) {
      log.push(e);
    },
    async lastSync() {
      return log.at(-1) ?? null;
    },
  };
}

const env = (token: string | undefined = TOKEN): Env =>
  ({ SYNC_TOKEN: token, ASSETS: { fetch: async () => new Response("<html>app</html>") }, DB: {} }) as unknown as Env;

const req = (path: string, init: RequestInit = {}, token: string | null = TOKEN) =>
  new Request(`https://fti.example.workers.dev${path}`, {
    ...init,
    headers: { ...(token ? { authorization: `Bearer ${token}` } : {}), ...(init.headers as Record<string, string>) },
  });

describe("sync from the PC", () => {
  it("refuses everything without the right token, and when no token is set at all", async () => {
    const s = memoryStore();
    expect((await handle(req("/internal/manifest", {}, null), env(), s, NOW)).status).toBe(401);
    expect((await handle(req("/internal/manifest", {}, "x".repeat(64)), env(), s, NOW)).status).toBe(401);
    expect((await handle(req("/internal/manifest"), env(""), s, NOW)).status).toBe(401);
    const put = req("/internal/snapshot/markets.json", { method: "PUT", body: "{}", headers: { "x-sha256": SHA } }, null);
    expect((await handle(put, env(), s, NOW)).status).toBe(401);
    expect(s.rows.size).toBe(0);
  });

  it("stores a file as it came and reports its hash in the manifest", async () => {
    const s = memoryStore();
    const body = '{"computed_at":"2026-11-02T09:58:00+00:00","markets":[]}';
    const r = await handle(req("/internal/snapshot/markets.json", { method: "PUT", body,
      headers: { "x-sha256": SHA, "x-computed-at": "2026-11-02T09:58:00+00:00" } }), env(), s, NOW);
    expect(r.status).toBe(200);
    expect(s.rows.get("markets.json")).toEqual({ body, sha: SHA, computed_at: "2026-11-02T09:58:00+00:00", synced_at: NOW.toISOString() });
    const m = await (await handle(req("/internal/manifest"), env(), s, NOW)).json();
    expect(m).toEqual({ files: { "markets.json": SHA } });
  });

  it("rejects bad names, bad hashes, oversized files and more files than the free plan needs", async () => {
    const s = memoryStore();
    const put = (name: string, body: string, sha = SHA) =>
      handle(req(`/internal/snapshot/${name}`, { method: "PUT", body, headers: { "x-sha256": sha } }), env(), s, NOW);
    expect((await put("..%2Fsecret.json", "{}")).status).toBe(400);
    expect((await put("markets.txt", "{}")).status).toBe(400);
    expect((await put("markets.json", "{}", "nothex")).status).toBe(400);
    expect((await put("big.json", "x".repeat(MAX_BYTES + 1))).status).toBe(413);
    for (let i = 0; i < MAX_FILES; i++) await put(`f${i}.json`, "{}");
    expect((await put("one-more.json", "{}")).status).toBe(400);
    expect((await put("f1.json", '{"x":1}')).status).toBe(200); // replacing an existing file is fine
  });

  it("logs a finished sync with clean numbers only", async () => {
    const s = memoryStore();
    await handle(req("/internal/sync-done", { method: "POST", body: JSON.stringify({ uploaded: 3, unchanged: "x", bytes: -5,
      computed_at: "2026-11-02T09:58:00+00:00", evil: "<script>" }) }), env(), s, NOW);
    expect(s.log).toEqual([{ at: NOW.toISOString(), uploaded: 3, unchanged: 0, bytes: 0, problems: 0, computed_at: "2026-11-02T09:58:00+00:00" }]);
  });
});

describe("the phone", () => {
  it("gets the stored file with the time the PC delivered it", async () => {
    const s = memoryStore();
    await s.put("markets.json", '{"markets":[]}', SHA, "2026-11-02T09:58:00+00:00", "2026-11-02T09:59:00.000Z");
    const r = await handle(req("/data/markets.json", {}, null), env(), s, NOW);
    expect(r.status).toBe(200);
    expect(await r.text()).toBe('{"markets":[]}');
    expect(r.headers.get("x-fti-synced-at")).toBe("2026-11-02T09:59:00.000Z");
    expect(r.headers.get("x-fti-computed-at")).toBe("2026-11-02T09:58:00+00:00");
  });

  it("says plainly when the cloud has not delivered anything yet", async () => {
    const r = await handle(req("/data/markets.json", {}, null), env(), memoryStore(), NOW);
    expect(r.status).toBe(404);
    expect(((await r.json()) as { detail: string }).detail).toMatch(/každých 30 minut/);
  });

  it("shows when the PC last synced, without any secret", async () => {
    const s = memoryStore();
    await s.logSync({ at: "2026-11-02T09:59:00.000Z", uploaded: 2, unchanged: 14, bytes: 900, problems: 0, computed_at: null }, "");
    const body = (await (await handle(req("/api/cloud/status", {}, null), env(), s, NOW)).json()) as { last_sync: SyncEntry };
    expect(body.last_sync.at).toBe("2026-11-02T09:59:00.000Z");
    expect(JSON.stringify(body)).not.toContain(TOKEN);
  });

  it("serves the app itself from the static files", async () => {
    const r = await handle(req("/", {}, null), env(), memoryStore(), NOW);
    expect(await r.text()).toContain("app");
  });
});

describe("helpers", () => {
  it("compares secrets exactly", () => {
    expect(sameSecret(TOKEN, TOKEN)).toBe(true);
    expect(sameSecret(TOKEN.slice(1) + "u", TOKEN)).toBe(false);
    expect(sameSecret("", "")).toBe(false);
    expect(sameSecret("short", TOKEN)).toBe(false);
  });
});
