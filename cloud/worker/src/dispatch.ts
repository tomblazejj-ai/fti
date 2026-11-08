/**
 * The reliable 30-minute clock of FTI without the PC. GitHub's own `schedule` is best effort: measured 31. 10.–8. 11.
 * it ran 3–5 times a day instead of 48 (median gap 106 min, longest 10.5 h). A Cloudflare Cron Trigger (free) asks
 * GitHub to start the workflow through its official API (workflow_dispatch) every 30 minutes instead.
 *
 * Needs the Worker secret GITHUB_DISPATCH_TOKEN: a fine-grained GitHub token for this one repository with only
 * "Actions: Read and write". Without it the clock does nothing and says so; GitHub's schedule stays as a backup.
 */

export interface DispatchEnv {
  GITHUB_REPO?: string;
  GITHUB_DISPATCH_TOKEN?: string;
  GITHUB_WORKFLOW?: string;
}

export interface DispatchResult {
  ok: boolean;
  status: number | null;
  text: string;
}

export async function dispatch(env: DispatchEnv, fetcher: typeof fetch = fetch): Promise<DispatchResult> {
  if (!env.GITHUB_REPO || !env.GITHUB_DISPATCH_TOKEN) {
    return { ok: false, status: null, text: "GITHUB_DISPATCH_TOKEN není nastavený — běh spouští jen plán GitHubu." };
  }
  const workflow = env.GITHUB_WORKFLOW ?? "mobil.yml";
  const r = await fetcher(`https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${workflow}/dispatches`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
      accept: "application/vnd.github+json",
      "x-github-api-version": "2022-11-28",
      "user-agent": "FTI-cloud-clock",
      "content-type": "application/json",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  if (r.status === 204) return { ok: true, status: 204, text: "Běh FTI na GitHubu spuštěn." };
  return { ok: false, status: r.status, text: `GitHub běh nespustil (HTTP ${r.status}).` };
}
