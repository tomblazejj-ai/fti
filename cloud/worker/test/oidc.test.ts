import { beforeEach, describe, expect, it } from "vitest";
import { type Env, handle } from "../src/app";
import { type Jwk, resetJwksCache, verifyGithubOidc } from "../src/oidc";

const NOW = new Date("2026-11-08T12:00:00Z");
const T = NOW.getTime() / 1000;
const POLICY = { repository: "tomblazejj-ai/fti", ref: "refs/heads/main", audience: "fti-cloud", events: ["schedule", "workflow_dispatch", "push"] };
const enc = (o: unknown) => btoa(JSON.stringify(o)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
const b64 = (b: ArrayBuffer) => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");

let pair: CryptoKeyPair;
let jwk: Jwk;

async function token(claims: Record<string, unknown>, key = pair.privateKey, kid = "k1"): Promise<string> {
  const head = enc({ alg: "RS256", kid, typ: "JWT" });
  const body = enc({ iss: "https://token.actions.githubusercontent.com", aud: "fti-cloud", repository: "tomblazejj-ai/fti",
                     ref: "refs/heads/main", event_name: "schedule", exp: T + 300, nbf: T - 5, ...claims });
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(`${head}.${body}`));
  return `${head}.${body}.${b64(sig)}`;
}

beforeEach(async () => {
  resetJwksCache();
  pair = (await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]),
                                            hash: "SHA-256" }, true, ["sign", "verify"])) as CryptoKeyPair;
  jwk = { ...((await crypto.subtle.exportKey("jwk", pair.publicKey)) as JsonWebKey), kid: "k1" };
});

describe("GitHub Actions OIDC", () => {
  const keys = async () => [jwk];

  it("accepts a genuine token of our repository's main branch", async () => {
    expect(await verifyGithubOidc(await token({}), POLICY, NOW, keys)).toBe(true);
  });

  it("refuses another repository, branch, audience, event, an expired token, a forged signature", async () => {
    for (const bad of [{ repository: "someone/fork" }, { ref: "refs/heads/test" }, { aud: "other" }, { event_name: "pull_request" },
                       { exp: T - 1 }, { iss: "https://evil.example" }]) {
      expect(await verifyGithubOidc(await token(bad), POLICY, NOW, keys)).toBe(false);
    }
    const other = (await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]),
                                                     hash: "SHA-256" }, true, ["sign", "verify"])) as CryptoKeyPair;
    expect(await verifyGithubOidc(await token({}, other.privateKey), POLICY, NOW, keys)).toBe(false);
    expect(await verifyGithubOidc("not.a.jwt", POLICY, NOW, keys)).toBe(false);
  });

  it("lets the cloud run write, and nobody without a valid token", async () => {
    const env = { GITHUB_REPO: "tomblazejj-ai/fti", ASSETS: { fetch: async () => new Response("x") }, DB: {} } as unknown as Env;
    const store = { manifest: async () => ({ "markets.json": "a".repeat(64) }) } as never;
    const req = async (auth: string) =>
      handle(new Request("https://fti.example/internal/manifest", { headers: { authorization: auth } }), env, store, NOW, keys);
    expect((await req(`Bearer ${await token({})}`)).status).toBe(200);
    expect((await req(`Bearer ${await token({ repository: "x/y" })}`)).status).toBe(401);
    expect((await req("Bearer nothing")).status).toBe(401);
  });
});
