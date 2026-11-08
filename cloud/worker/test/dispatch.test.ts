import { describe, expect, it } from "vitest";
import { dispatch } from "../src/dispatch";

describe("30-minute clock", () => {
  it("asks GitHub to run the FTI workflow on main", async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    const fake = (async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return new Response(null, { status: 204 });
    }) as unknown as typeof fetch;
    const r = await dispatch({ GITHUB_REPO: "tomblazejj-ai/fti", GITHUB_DISPATCH_TOKEN: "github_pat_x" }, fake);
    expect(r.ok).toBe(true);
    expect(calls[0].url).toBe("https://api.github.com/repos/tomblazejj-ai/fti/actions/workflows/mobil.yml/dispatches");
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ ref: "main" });
  });

  it("does nothing without a token and reports a refusal plainly", async () => {
    expect((await dispatch({ GITHUB_REPO: "tomblazejj-ai/fti" })).ok).toBe(false);
    const refused = (async () => new Response("{}", { status: 403 })) as unknown as typeof fetch;
    expect(await dispatch({ GITHUB_REPO: "a/b", GITHUB_DISPATCH_TOKEN: "x" }, refused)).toEqual({ ok: false, status: 403, text: "GitHub běh nespustil (HTTP 403)." });
  });
});
