// Capital.com Open API (DEMO) — verification outside the app (brief docs/fti-research.md, Etapa 1, step 2):
//   1. open a session, 2. find the epics for gold, EUR/USD, US500 and NAS100 (never guessed), with their market status,
//   delay and whether streaming prices are available, 3. connect the WebSocket, subscribe quotes + live M1 OHLC and
//   measure for N minutes how often quotes come, how old they are on arrival, the spread, and the session keep-alive.
//
//   node cloud/probe/capital_probe.mjs [minutes=60]
//
// Reads CAPITAL_API_KEY, CAPITAL_IDENTIFIER (the account's login e-mail — sent ONLY to Capital.com) and
// CAPITAL_API_PASSWORD (the API key's own password) from backend/.env, which the user fills in FTI (Data → Klíče).
// Read-only: no order, no position, no account change. The result goes to backend/cache/capital-probe-<time>.json.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const REST = "https://demo-api-capital.backend-capital.com/api/v1";
const WS = "wss://api-streaming-capital.backend-capital.com/connect";
const MINUTES = Number(process.argv[2] ?? 60);
const WANT = {
  XAUUSD: ["gold"],
  EURUSD: ["EUR/USD", "EURUSD"],
  US500: ["US 500", "US500"],
  NAS100: ["US Tech 100", "US100", "NAS100"],
};

function env() {
  const out = {};
  for (const line of readFileSync(join(ROOT, "backend", ".env"), "utf8").split(/\r?\n/)) {
    const i = line.indexOf("=");
    if (i > 0 && !line.trim().startsWith("#")) out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  for (const k of ["CAPITAL_API_KEY", "CAPITAL_IDENTIFIER", "CAPITAL_API_PASSWORD"])
    if (!out[k]) throw new Error(`V FTI chybí klíč ${k} (Data → Klíče).`);
  return out;
}

async function session(e) {
  const r = await fetch(`${REST}/session`, {
    method: "POST",
    headers: { "X-CAP-API-KEY": e.CAPITAL_API_KEY, "Content-Type": "application/json" },
    body: JSON.stringify({ identifier: e.CAPITAL_IDENTIFIER, password: e.CAPITAL_API_PASSWORD, encryptedPassword: false }),
  });
  if (!r.ok) throw new Error(`přihlášení selhalo: HTTP ${r.status} ${(await r.text()).slice(0, 200)}`);
  return { cst: r.headers.get("CST"), token: r.headers.get("X-SECURITY-TOKEN") };
}

async function get(s, path) {
  const r = await fetch(`${REST}${path}`, { headers: { CST: s.cst, "X-SECURITY-TOKEN": s.token } });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status} ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const e = env();
  const s = await session(e);
  console.log("Přihlášeno k DEMO API Capital.com.");
  const found = {};
  for (const [code, terms] of Object.entries(WANT)) {
    for (const term of terms) {
      const res = await get(s, `/markets?searchTerm=${encodeURIComponent(term)}`);
      const m = (res.markets ?? [])[0];
      if (m) {
        found[code] = m;
        console.log(`${code}: epic ${m.epic} | ${m.instrumentName} | stav ${m.marketStatus} | streaming ${m.streamingPricesAvailable} | zpoždění ${m.delayTime} | typ ${m.instrumentType}`);
        break;
      }
      await sleep(200);
    }
    if (!found[code]) console.log(`${code}: nenalezen (hledáno ${terms.join(", ")})`);
  }
  const epics = Object.values(found).map((m) => m.epic);
  const stats = Object.fromEntries(epics.map((ep) => [ep, { quotes: 0, gaps: [], ages: [], spreads: [], ohlc: 0, last: null }]));
  const ws = new WebSocket(WS);
  let cid = 0;
  const send = (destination, payload = {}) =>
    ws.send(JSON.stringify({ destination, correlationId: String(++cid), cst: s.cst, securityToken: s.token, payload }));
  ws.onopen = () => {
    send("marketData.subscribe", { epics });
    send("OHLCMarketData.subscribe", { epics, resolutions: ["MINUTE"], type: "classic" });
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    const now = Date.now();
    if (msg.destination === "quote") {
      const p = msg.payload, st = stats[p.epic];
      if (!st) return;
      if (st.last) st.gaps.push((now - st.last) / 1000);
      st.last = now;
      st.quotes++;
      if (p.timestamp) st.ages.push((now - p.timestamp) / 1000);
      if (p.ofr != null && p.bid != null) st.spreads.push(p.ofr - p.bid);
    } else if (msg.destination === "ohlc.event") {
      if (stats[msg.payload?.epic]) stats[msg.payload.epic].ohlc++;
    } else if (msg.status && msg.status !== "OK") {
      console.log("odpověď:", JSON.stringify(msg).slice(0, 300));
    }
  };
  const ping = setInterval(async () => {
    send("ping");
    try { await get(s, "/ping"); } catch (err) { console.log("ping REST selhal:", err.message); }
  }, 5 * 60 * 1000);
  const end = Date.now() + MINUTES * 60 * 1000;
  while (Date.now() < end) {
    await sleep(Math.min(60000, end - Date.now()));
    console.log(new Date().toISOString().slice(11, 19), epics.map((ep) => `${ep} ${stats[ep].quotes}`).join(" | "));
  }
  clearInterval(ping);
  ws.close();
  const med = (a) => (a.length ? [...a].sort((x, y) => x - y)[Math.floor(a.length / 2)] : null);
  const p95 = (a) => (a.length ? [...a].sort((x, y) => x - y)[Math.floor(0.95 * (a.length - 1))] : null);
  const summary = Object.fromEntries(Object.entries(stats).map(([ep, st]) => [ep, {
    quotes: st.quotes, per_minute: +(st.quotes / MINUTES).toFixed(1), gap_median_s: med(st.gaps), gap_max_s: st.gaps.length ? Math.max(...st.gaps) : null,
    age_median_s: med(st.ages), age_p95_s: p95(st.ages), spread_median: med(st.spreads), ohlc_events: st.ohlc,
  }]));
  console.log(JSON.stringify(summary, null, 1));
  mkdirSync(join(ROOT, "backend", "cache"), { recursive: true });
  const file = join(ROOT, "backend", "cache", `capital-probe-${new Date().toISOString().replace(/[:.]/g, "-")}.json`);
  writeFileSync(file, JSON.stringify({ minutes: MINUTES, markets: found, summary }, null, 1));
  console.log("Výsledek:", file);
}

main().catch((err) => { console.error("CHYBA:", err.message); process.exit(1); });
