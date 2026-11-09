import { useState } from "react";
import { useAsync } from "../hooks/useAsync";
import { STATIC, api } from "../lib/api";
import { formatDateTime, shortDate } from "../lib/format";
import type { AiAnalysis, AiFact, AiPoint, AiRunResult } from "../lib/types";
import { Icon } from "./Icon";
import { Card, Empty } from "./ui";

interface MarketOut {
  shrnuti?: string;
  bias?: string;
  pro?: AiPoint[];
  proti?: AiPoint[];
  sledovat?: AiPoint[];
  chybi?: string[];
  jistota?: string;
}

export const when = (k?: string | null) => (!k ? "" : k.length <= 10 ? shortDate(k) : formatDateTime(k));

export function runText(r: AiRunResult): string {
  if (r.status === "cached") return "Data se od posledního výkladu nezměnila — AI se znovu neptala.";
  if (r.status === "cooldown") return `Další AI výklad nejdřív ${formatDateTime(r.until)} — zatím platí ten poslední.`;
  return `${r.text}${r.until ? ` Znovu ${formatDateTime(r.until)}.` : ""}`;
}

/** The AI interpretation of one market (Gemini Free, backup Groq Free). It only explains what FTI's engine computed;
 * every number is checked against the engine's facts, and an answer that fails is not shown as verified. */
export function AiPanel({ code, i = 6 }: { code: string; i?: number }) {
  const hist = useAsync(() => api.aiAnalyses(code, "market"), [code]);
  const status = useAsync(() => (STATIC ? Promise.resolve(null) : api.aiStatus()), []);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<AiRunResult | null>(null);
  if (STATIC) {
    // the phone shows the last interpretation the cloud made — read only
    const last = hist.data?.analyses[0];
    return last ? (
      <Card title="Výklad AI" icon={<Icon name="spark" size={16} />} i={i} id="ai"
            extra={<span className="card-note">poslední výklad z cloudu</span>}>
        <AiMarket a={last} />
      </Card>
    ) : null;
  }
  const a = msg?.analysis ?? hist.data?.analyses[0] ?? null;
  const g = status.data?.groq;
  const ready = g?.state === "ready";
  const run = async () => {
    setBusy(true);
    try {
      setMsg(await api.aiAnalyze("market", code));
    } catch (e) {
      setMsg({ status: "unavailable", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
      status.reload();
    }
  };
  return (
    <Card title="Výklad AI" icon={<Icon name="spark" size={16} />} i={i} id="ai"
          extra={<span className="card-note">Gemini Free / Groq Free · vykládá jen výpočty FTI</span>}>
      {status.error && !status.data ? (
        <Empty>AI výklad teď není k dispozici — zbytek FTI funguje normálně.</Empty>
      ) : (
        <>
          {a ? <AiMarket a={a} /> : <Empty>{g ? "K tomuto trhu zatím žádný AI výklad není." : "Zjišťuji stav AI…"}</Empty>}
          <div className="form-row">
            <button type="button" className="btn-primary" onClick={run} disabled={busy || !ready}>
              {busy ? "AI vykládá…" : a ? "Aktualizovat výklad" : "Vytvořit AI výklad"}
            </button>
            {g && !ready && (
              <span className="muted">
                {g.text}{g.until ? ` Znovu ${formatDateTime(g.until)}.` : ""} <a href="#/data">Nastavení AI</a>
              </span>
            )}
          </div>
          {msg && msg.status !== "ok" && <p className={msg.status === "cached" || msg.status === "cooldown" ? "msg-ok" : "msg-err"}>{runText(msg)}</p>}
        </>
      )}
    </Card>
  );
}

function AiMarket({ a }: { a: AiAnalysis }) {
  const o = (a.output ?? {}) as MarketOut;
  const v = a.validation;
  const facts = new Map((a.facts ?? []).map((f) => [f.id, f]));
  const body = (
    <>
      {o.shrnuti && <p><strong>{o.shrnuti}</strong></p>}
      {o.bias && <p>{o.bias}</p>}
      <Points title="Co BIAS podporuje" items={o.pro} facts={facts} />
      <Points title="Co jde proti" items={o.proti} facts={facts} />
      <Points title="Co sledovat" items={o.sledovat} facts={facts} />
      {o.chybi && o.chybi.length > 0 && <p className="hint">Chybí data: {o.chybi.join(", ")}</p>}
      {o.jistota && <p className="muted">Jistota výkladu: {o.jistota}</p>}
    </>
  );
  return (
    <div className="ai-out">
      <p className="ai-meta">
        {formatDateTime(a.created_at)} · {a.model ?? "AI"} ·{" "}
        {v?.ok ? <span className="qb qb-live">ověřeno proti datům FTI</span> : <span className="qb qb-stale">neověřeno</span>}
      </p>
      {v?.ok ? body : (
        <>
          <p className="msg-err">
            Odpověď AI neprošla kontrolou
            {v && v.unknown_numbers.length > 0 ? ` (čísla, která ve výpočtech FTI nejsou: ${v.unknown_numbers.join(", ")})` : ""}.
            Platí rozbor FTI výše.
          </p>
          <details className="ai-raw">
            <summary>Zobrazit neověřený text AI</summary>
            {body}
          </details>
        </>
      )}
      <Facts facts={a.facts ?? []} />
      <p className="note">
        Vychází z výpočtu FTI z {formatDateTime(a.engine_computed_at)}. Skóre a BIAS počítá engine FTI, AI je jen vykládá. Není to investiční doporučení.
      </p>
    </div>
  );
}

function Points({ title, items, facts }: { title: string; items?: AiPoint[]; facts: Map<string, AiFact> }) {
  if (!items || !items.length) return null;
  return (
    <>
      <h3 className="sub">{title}</h3>
      <ul className="ai-points">
        {items.map((p, idx) => (
          <li key={idx}>
            {p.text}{" "}
            {p.fakta.map((id) => {
              const f = facts.get(id);
              return <span key={id} className="ai-ref" title={f ? `${f.co}: ${String(f.hodnota)}` : "neznámý fakt"}>{id}</span>;
            })}
          </li>
        ))}
      </ul>
    </>
  );
}

function Facts({ facts }: { facts: AiFact[] }) {
  if (!facts.length) return null;
  return (
    <details className="ai-facts">
      <summary>Fakta z FTI, ze kterých AI vycházela ({facts.length})</summary>
      <ul>
        {facts.map((f) => (
          <li key={f.id}>
            <span className="ai-ref">{f.id}</span> {f.co}: <strong>{String(f.hodnota)}</strong>{" "}
            <small>{f.zdroj}{f.k ? ` · ${when(f.k)}` : ""}</small>
            {f.text && <small className="ai-fact-text">{f.text}</small>}
          </li>
        ))}
      </ul>
    </details>
  );
}

interface TradeScenario {
  typ: "LONG" | "SHORT" | "NO TRADE";
  popis: string;
  potvrzeni: AiPoint[];
  invalidace: AiPoint[];
}

interface TradeOut {
  shrnuti?: string;
  doporuceni?: "LONG" | "SHORT" | "NO TRADE";
  bias?: string;
  horizont?: string;
  jistota?: string;
  technika?: AiPoint[];
  fundament?: AiPoint[];
  zpravy_sentiment?: AiPoint[];
  intermarket?: AiPoint[];
  pro?: AiPoint[];
  proti?: AiPoint[];
  scenare?: TradeScenario[];
  rizika?: AiPoint[];
  vztah_k_enginu?: { shoda: string; text: string; fakta: string[] };
  chybejici_data?: string[];
}

const REC_CLASS: Record<string, string> = { LONG: "bias-pos", SHORT: "bias-neg", "NO TRADE": "bias-zero" };
const ROLE_CS: Record<string, string> = { makro: "Makro a fundament", technika: "Technika", synteza: "Hlavní analytik" };
export const AREA_CS: Record<string, string> = {
  trh: "Trh a cena", technika: "Technika", fundament: "Fundament (FRED, model FTI)", engine: "Pravidlový verdikt FTI",
  dolar: "Dolar (DXY)", mezitrh: "Mezitrh", pozice: "Pozice (COT)", volatilita: "Volatilita", kalendar: "Kalendář",
  zpravy: "Zprávy", sezonnost: "Sezónnost", kvalita: "Kvalita dat", specialista: "Závěry AI specialistů",
};

/** The complex AI analysis (LONG / SHORT / NO TRADE): several AI roles over FTI's common context. An AI scenario for
 * the user's own decision — FTI never trades. Every number is checked against FTI's facts, which are listed below. */
export function AiTradePanel({ code, i = 7 }: { code: string; i?: number }) {
  const hist = useAsync(() => api.aiAnalyses(code, "trade"), [code]);
  const status = useAsync(() => (STATIC ? Promise.resolve(null) : api.aiStatus()), []);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<AiRunResult | null>(null);
  if (code !== "XAUUSD") return null;
  if (STATIC) {
    // the phone shows the last analysis the cloud made (every 30 minutes the cloud decides whether a new one is due)
    const last = hist.data?.analyses[0];
    return (
      <Card title="Komplexní AI analýza" icon={<Icon name="spark" size={16} />} i={i} id="ai-trade"
            extra={<span className="card-note">z cloudu · obchody zadáváš ty</span>}>
        {last ? <TradeView a={last} /> : <Empty>{hist.loading ? "Načítám analýzu…" : "Cloud zatím žádnou analýzu neuložil."}</Empty>}
      </Card>
    );
  }
  const a = msg?.analysis ?? hist.data?.analyses[0] ?? null;
  const g = status.data?.groq;
  const ready = g?.state === "ready";
  const run = async () => {
    setBusy(true);
    try {
      setMsg(await api.aiAnalyze("trade", code));
    } catch (e) {
      setMsg({ status: "unavailable", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
      status.reload();
    }
  };
  return (
    <Card title="Komplexní AI analýza" icon={<Icon name="spark" size={16} />} i={i} id="ai-trade"
          extra={<span className="card-note">více AI rolí · Gemini Free / Groq Free · obchody zadáváš ty</span>}>
      {a ? <TradeView a={a} /> : <Empty>{g ? "Komplexní analýza zatím nevznikla." : "Zjišťuji stav AI…"}</Empty>}
      <div className="form-row">
        <button type="button" className="btn-primary" onClick={run} disabled={busy || !ready}>
          {busy ? "AI analyzuje (až 2 minuty)…" : a ? "Aktualizovat analýzu" : "Vytvořit analýzu"}
        </button>
        {g && !ready && (
          <span className="muted">
            {g.text}{g.until ? ` Znovu ${formatDateTime(g.until)}.` : ""} <a href="#/data">Nastavení AI</a>
          </span>
        )}
      </div>
      {msg && msg.status !== "ok" && <p className={msg.status === "cached" || msg.status === "cooldown" ? "msg-ok" : "msg-err"}>{runText(msg)}</p>}
    </Card>
  );
}

function TradeView({ a }: { a: AiAnalysis }) {
  const o = (a.output ?? {}) as TradeOut;
  const v = a.validation;
  const facts = new Map((a.facts ?? []).map((f) => [f.id, f]));
  const rec = o.doporuceni ?? "NO TRADE";
  const body = (
    <>
      <p className="ai-rec">
        <span className={`bias ${REC_CLASS[rec] ?? "bias-zero"}`}>{rec}</span>
        <span>bias {o.bias} · {o.horizont} · jistota {o.jistota}</span>
      </p>
      {o.shrnuti && <p><strong>{o.shrnuti}</strong></p>}
      {o.vztah_k_enginu && (
        <p className={o.vztah_k_enginu.shoda === "souhlasí" ? "hint" : "msg-err"}>
          Vůči pravidlovému verdiktu FTI: <strong>{o.vztah_k_enginu.shoda}</strong> — {o.vztah_k_enginu.text}{" "}
          {o.vztah_k_enginu.fakta.map((id) => <Ref key={id} id={id} facts={facts} />)}
        </p>
      )}
      <div className="ai-scen">
        {(o.scenare ?? []).map((s, idx) => (
          <div key={idx} className="ai-scen-box">
            <p><span className={`bias ${REC_CLASS[s.typ] ?? "bias-zero"}`}>{s.typ}</span> {s.popis}</p>
            <Points title="Potvrzení" items={s.potvrzeni} facts={facts} />
            <Points title="Invalidace" items={s.invalidace} facts={facts} />
          </div>
        ))}
      </div>
      <Points title="Pro doporučení" items={o.pro} facts={facts} />
      <Points title="Proti doporučení" items={o.proti} facts={facts} />
      <Points title="Technika" items={o.technika} facts={facts} />
      <Points title="Fundament a makro" items={o.fundament} facts={facts} />
      <Points title="Zprávy a sentiment" items={o.zpravy_sentiment} facts={facts} />
      <Points title="Mezitržní vztahy" items={o.intermarket} facts={facts} />
      <Points title="Rizika" items={o.rizika} facts={facts} />
      {o.chybejici_data && o.chybejici_data.length > 0 && <p className="hint">Chybějící nebo zastaralá data: {o.chybejici_data.join("; ")}</p>}
    </>
  );
  return (
    <div className="ai-out">
      <p className="ai-meta">
        {formatDateTime(a.created_at)} · {(a.providers ?? []).join(", ") || "AI"} · {a.tokens ? `${a.tokens.in + a.tokens.out} tokenů` : ""}
        {a.seconds ? ` · ${Math.round(a.seconds)} s` : ""} ·{" "}
        {v?.ok ? <span className="qb qb-live">ověřeno proti datům FTI</span> : <span className="qb qb-stale">neověřeno</span>}
      </p>
      {v?.ok ? body : (
        <>
          <p className="msg-err">
            Analýza neprošla kontrolou
            {v && v.unknown_numbers.length > 0 ? ` (čísla, která v datech FTI nejsou: ${v.unknown_numbers.join(", ")})` : ""}
            {v?.rules && v.rules.length > 0 ? ` — ${v.rules.join(" ")}` : ""}
            {v?.attribution && v.attribution.length > 0 ? ` — kontrola FTI: ${v.attribution.join("; ")}` : ""}.
          </p>
          <details className="ai-raw"><summary>Zobrazit neověřenou analýzu</summary>{body}</details>
        </>
      )}
      <Removed a={a} />
      {a.stages && a.stages.length > 0 && (
        <details className="ai-facts">
          <summary>Jak analýza vznikla — AI role a modely ({a.stages.length})</summary>
          <ul>
            {a.stages.map((s) => (
              <li key={s.role}>
                <strong>{ROLE_CS[s.role] ?? s.role}</strong>: {s.provider} · {s.model} · {s.tokens.in}+{s.tokens.out} tokenů · {s.seconds} s ·{" "}
                {s.validation?.ok ? "ověřeno" : "neprošlo kontrolou — do závěru nezahrnuto"}
                <small className="ai-fact-text">použitá fakta: {s.facts_used.join(", ")}</small>
              </li>
            ))}
          </ul>
        </details>
      )}
      <GroupedFacts facts={a.facts ?? []} />
      <p className="note">
        Vychází z výpočtu FTI z {formatDateTime(a.engine_computed_at)}. AI scénář je podklad pro tvé rozhodnutí — FTI nikdy neobchoduje. Není to investiční doporučení.
      </p>
    </div>
  );
}

/** What FTI's independent check (rules, no AI) removed from the answers of the AI roles, and why. */
function Removed({ a }: { a: AiAnalysis }) {
  const items = [
    ...(a.validation?.removed ?? []).map((r) => ({ ...r, role: "synteza" })),
    ...(a.stages ?? []).filter((s) => s.role !== "synteza").flatMap((s) => (s.validation?.removed ?? []).map((r) => ({ ...r, role: s.role }))),
  ];
  if (!items.length) return <p className="small muted">Nezávislá kontrola FTI: všechny body sedí na citovaná data.</p>;
  return (
    <details className="ai-facts">
      <summary>Nezávislá kontrola FTI odstranila {items.length} {items.length === 1 ? "bod" : items.length < 5 ? "body" : "bodů"}</summary>
      <ul>
        {items.map((r, idx) => (
          <li key={idx}>
            <strong>{ROLE_CS[r.role] ?? r.role}:</strong> „{r.text}“
            <small className="ai-fact-text">{r.problem}</small>
          </li>
        ))}
      </ul>
    </details>
  );
}

function Ref({ id, facts }: { id: string; facts: Map<string, AiFact> }) {
  const f = facts.get(id);
  return <span className="ai-ref" title={f ? `${f.co}: ${String(f.hodnota)}` : "neznámý fakt"}>{id}</span>;
}

function GroupedFacts({ facts }: { facts: AiFact[] }) {
  if (!facts.length) return null;
  const groups = new Map<string, AiFact[]>();
  for (const f of facts) groups.set(f.oblast ?? "jiné", [...(groups.get(f.oblast ?? "jiné") ?? []), f]);
  return (
    <details className="ai-facts">
      <summary>Data, se kterými AI pracovala ({facts.length} údajů)</summary>
      {[...groups.entries()].map(([area, list]) => (
        <div key={area}>
          <h3 className="sub">{AREA_CS[area] ?? area}</h3>
          <ul>
            {list.map((f) => (
              <li key={f.id}>
                <span className="ai-ref">{f.id}</span> {f.co}: <strong>{String(f.hodnota)}</strong>{" "}
                <small>{f.zdroj}{f.k ? ` · ${when(f.k)}` : ""}{f.puvod_casu ? ` (${f.puvod_casu})` : ""}</small>
                {f.text && <small className="ai-fact-text">{f.text}</small>}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </details>
  );
}
