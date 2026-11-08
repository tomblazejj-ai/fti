/**
 * GitHub Actions OIDC — the cloud run of FTI proves who it is with a short-lived token that GitHub signs (RS256),
 * so no password for the cloud has to be stored in GitHub. Accepted only when every claim matches the policy:
 * issuer GitHub, our audience, our repository, the main branch, an expected event, not expired, and a valid
 * signature by one of GitHub's published keys (cached for an hour).
 */

export const GITHUB_ISSUER = "https://token.actions.githubusercontent.com";
export const JWKS_URL = `${GITHUB_ISSUER}/.well-known/jwks`;

export interface OidcPolicy {
  repository: string;
  ref: string;
  audience: string;
  events: string[];
}

export type Jwk = JsonWebKey & { kid?: string };
export type FetchJwks = () => Promise<Jwk[]>;

export const fetchJwks: FetchJwks = async () => {
  const r = await fetch(JWKS_URL);
  if (!r.ok) throw new Error(`JWKS ${r.status}`);
  return ((await r.json()) as { keys: Jwk[] }).keys;
};

let cache: { at: number; keys: Jwk[] } | null = null;

export function resetJwksCache(): void {
  cache = null;
}

function b64url(s: string): Uint8Array {
  let t = s.replace(/-/g, "+").replace(/_/g, "/");
  while (t.length % 4) t += "=";
  const bin = atob(t);
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

function part<T>(s: string): T | null {
  try {
    return JSON.parse(new TextDecoder().decode(b64url(s))) as T;
  } catch {
    return null;
  }
}

interface Claims {
  iss?: string;
  aud?: string | string[];
  repository?: string;
  ref?: string;
  event_name?: string;
  exp?: number;
  nbf?: number;
}

/** true only for a genuine, unexpired GitHub Actions token of this repository's main branch and our audience. */
export async function verifyGithubOidc(token: string, policy: OidcPolicy, now: Date, getKeys: FetchJwks = fetchJwks): Promise<boolean> {
  const parts = token.split(".");
  if (parts.length !== 3) return false;
  const header = part<{ alg?: string; kid?: string }>(parts[0]);
  const c = part<Claims>(parts[1]);
  if (!header || !c || header.alg !== "RS256" || typeof header.kid !== "string") return false;
  const t = now.getTime() / 1000;
  const aud = Array.isArray(c.aud) ? c.aud : [c.aud];
  if (c.iss !== GITHUB_ISSUER || !aud.includes(policy.audience)) return false;
  if (c.repository !== policy.repository || c.ref !== policy.ref || !policy.events.includes(c.event_name ?? "")) return false;
  if (typeof c.exp !== "number" || c.exp < t) return false;
  if (typeof c.nbf === "number" && c.nbf > t + 60) return false;
  let jwk = cache && Date.now() - cache.at < 3_600_000 ? cache.keys.find((k) => k.kid === header.kid) : undefined;
  if (!jwk) {
    try {
      const keys = await getKeys();
      cache = { at: Date.now(), keys };
      jwk = keys.find((k) => k.kid === header.kid);
    } catch {
      return false;
    }
  }
  if (!jwk) return false;
  const { kid: _kid, ...material } = jwk;
  try {
    const key = await crypto.subtle.importKey("jwk", { ...material, alg: "RS256", ext: true }, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
                                              false, ["verify"]);
    return await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, b64url(parts[2]), new TextEncoder().encode(`${parts[0]}.${parts[1]}`));
  } catch {
    return false;
  }
}
