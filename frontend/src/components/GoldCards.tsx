// Cards over gold's engine output (/api/instruments/XAUUSD/analysis) and the AI's last analysis. They show what FTI
// computed — with source, time and method — and say "zatím nedostupné" where FTI has nothing.
import type { ReactNode } from "react";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { formatDateTime, relativeTime, shortDate } from "../lib/format";
import type { AiAnalysis, GoldAnalysis } from "../lib/types";
import { AREA_CS } from "./AiPanel";
import { Icon } from "./Icon";
import { Card, Empty } from "./ui";
import { CenterBar } from "./Spark";

export const NA = "zatím nedostupné";

const signed = (v: number | null | undefined, d = 0) =>
  v === null || v === undefined ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toLocaleString("cs-CZ", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
const num = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined ? "—" : v.toLocaleString("cs-CZ", { minimumFractionDigits: d, maximumFractionDigits: d });

/** Why a gold card is empty: the analysis is not there (phone version, first start) — said, not hidden. */
function Missing({ error, what }: { error?: Error; what: string }) {
  return <Empty>{`${what}: ${NA}.`}{error ? ` (${error.message})` : ""}</Empty>;
}

/** Score Overview: every factor −5 … +5 and the total −10 … +10, as the engine's scorecard has them. */
export function ScoreModules({ an, error, i = 0 }: { an?: GoldAnalysis; error?: Error; i?: number }) {
  const sc = an?.scorecard;
  return (
    <Card title="Skóre modulů" icon={<Icon name="chart" size={16} />} i={i} id="moduly"
          extra={sc && <span className="card-note">faktor −5 … +5 · celkem −10 … +10</span>}>
      {!sc ? (
        <Missing error={error} what="Skóre modulů" />
      ) : (
        <>
          <ul className="mods">
            {sc.items.map((it) => (
              <li key={it.key} title={`${it.label} · skupina ${it.group} · výpočet FTI ${an ? formatDateTime(an.computed_at) : ""}\n${sc.note}`}>
                <span className="mod-label">{it.label}</span>
                {it.score === null ? (
                  <span className="mod-na">{NA}</span>
                ) : (
                  <>
                    <CenterBar value={it.score} max={5} label={`${it.label} ${signed(it.score)} z 5`} />
                    <span className={`mod-val num ${it.score > 0 ? "pos" : it.score < 0 ? "neg" : "zero"}`}>{signed(it.score)}</span>
                  </>
                )}
              </li>
            ))}
          </ul>
          <p className="mods-total" title={sc.note}>
            Celkem <strong className={`num ${sc.final > 0 ? "pos" : sc.final < 0 ? "neg" : "zero"}`}>{signed(sc.final)}</strong> z ±10 · {sc.final_label}
          </p>
        </>
      )}
    </Card>
  );
}

const REC_CLASS: Record<string, string> = { LONG: "bias-pos", SHORT: "bias-neg", "NO TRADE": "bias-zero" };

function aiOut(a: AiAnalysis) {
  return (a.output ?? {}) as { doporuceni?: string; shrnuti?: string; jistota?: string; horizont?: string };
}

/** The last AI analysis, short: recommendation, summary, when it was made, which FTI data it used. */
export function AiSummary({ code, i = 0 }: { code: string; i?: number }) {
  const hist = useAsync(() => api.aiAnalyses(code, "trade"), [code]);
  const a = hist.data?.analyses[0];
  const o = a ? aiOut(a) : null;
  const areas = a ? [...new Set((a.facts ?? []).map((f) => f.oblast).filter((x): x is string => !!x))].map((x) => AREA_CS[x] ?? x) : [];
  return (
    <Card title="AI shrnutí" icon={<Icon name="spark" size={16} />} i={i} id="ai-shrnuti"
          extra={<a className="card-link" href={`#/ai/${code}`}>Celá analýza <Icon name="chevronRight" size={14} /></a>}>
      {a && o ? (
        <>
          <p className="ai-rec">
            <span className={`bias ${REC_CLASS[o.doporuceni ?? "NO TRADE"] ?? "bias-zero"}`}>{o.doporuceni ?? "NO TRADE"}</span>
            {(o.jistota || o.horizont) && <span>{[o.jistota && `jistota ${o.jistota}`, o.horizont].filter(Boolean).join(" · ")}</span>}
          </p>
          {o.shrnuti && <p className="ai-sum-text">{o.shrnuti}</p>}
          <dl className="meta-list">
            <dt>Vytvořeno</dt>
            <dd>{formatDateTime(a.created_at)} ({relativeTime(a.created_at)})</dd>
            <dt>Použitá data</dt>
            <dd>{(a.facts ?? []).length} faktů FTI{areas.length ? ` — ${areas.join(", ")}` : ""}</dd>
            {a.engine_computed_at && (
              <>
                <dt>Výpočet FTI</dt>
                <dd>{formatDateTime(a.engine_computed_at)}</dd>
              </>
            )}
            <dt>Model</dt>
            <dd>{a.providers?.length ? a.providers.join(", ") : a.model ?? "—"}</dd>
          </dl>
        </>
      ) : (
        <Empty>
          {hist.loading ? "Načítám…" : code === "XAUUSD" ? "AI analýza zatím nevznikla — spustíš ji v AI Advisor." : "AI analýza se zatím dělá jen pro zlato."}
        </Empty>
      )}
      <p className="ai-disclaimer">AI se může mýlit, čísla pochází z dat FTI.</p>
    </Card>
  );
}

/** "Last 5 signals": FTI does not keep signal results yet — said plainly; the last AI analysis is shown as it is. */
export function LastSignals({ i = 0 }: { i?: number }) {
  const hist = useAsync(() => api.aiAnalyses("XAUUSD", "trade"), []);
  const a = hist.data?.analyses[0];
  return (
    <Card title="Posledních 5 signálů" icon={<Icon name="history" size={16} />} i={i} id="signaly">
      <p className="hint" style={{ marginTop: 0 }}>
        Historie signálů s výsledkem: <strong>{NA}</strong>. FTI zatím neukládá, jestli signál došel k cíli, nebo ke stop-lossu, takže žádnou
        úspěšnost neukazuje.
      </p>
      {a ? (
        <table className="dtable">
          <thead>
            <tr>
              <th>Čas</th>
              <th>AI doporučení</th>
              <th>Výsledek</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="num">{formatDateTime(a.created_at)}</td>
              <td>
                <span className={`bias ${REC_CLASS[aiOut(a).doporuceni ?? "NO TRADE"] ?? "bias-zero"}`}>{aiOut(a).doporuceni ?? "NO TRADE"}</span>
              </td>
              <td className="muted">nevyhodnocuje se</td>
            </tr>
          </tbody>
        </table>
      ) : (
        <Empty>{hist.loading ? "Načítám…" : "Zatím žádná AI analýza."}</Empty>
      )}
    </Card>
  );
}

/** FTI's own rule-based summary (not AI). */
export function FtiSummary({ an, i = 0 }: { an?: GoldAnalysis; i?: number }) {
  const s = an?.summary;
  if (!s) return null;
  return (
    <Card title="Shrnutí FTI" icon={<Icon name="info" size={16} />} i={i} id="shrnuti" extra={<span className="card-note">pevná pravidla, ne AI</span>}>
      <p className="ai-sum-text">{s.text}</p>
      {s.outlook.length > 0 && (
        <ul className="plain-list">
          {s.outlook.map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ul>
      )}
      <p className="src">{s.note} Stav k {shortDate(s.date)}.</p>
    </Card>
  );
}

/** COT: how the funds are positioned (CFTC, weekly). */
export function CotCard({ an, error, i = 0 }: { an?: GoldAnalysis; error?: Error; i?: number }) {
  const c = an?.cot;
  return (
    <Card title="COT — pozice fondů" icon={<Icon name="users" size={16} />} i={i} id="cot"
          extra={c && <span className="card-note">CFTC · data k {shortDate(c.as_of)}</span>}>
      {!c ? (
        <Missing error={error} what="COT" />
      ) : (
        <>
          <ul className="plain-list">
            {c.texts.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
          <div className="table-scroll">
            <table className="dtable">
              <thead>
                <tr>
                  <th>Skupina</th>
                  <th>Netto</th>
                  <th>Za týden</th>
                  <th>Za 4 týdny</th>
                  <th>COT index 3 roky</th>
                </tr>
              </thead>
              <tbody>
                {c.groups.map((g) => (
                  <tr key={g.key} title={g.who}>
                    <td>{g.label}</td>
                    <td className="num">{signed(g.net)}</td>
                    <td className="num">{signed(g.change_1w)}</td>
                    <td className="num">{signed(g.change_4w)}</td>
                    <td className="num">{g.index_3y == null ? "—" : num(g.index_3y, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="src">
            {c.source_label}. {c.schedule?.next_release && `Další report ${formatDateTime(c.schedule.next_release)}.`}
          </p>
        </>
      )}
    </Card>
  );
}

const ARROW: Record<number, string> = { 1: "↑", 0: "→", [-1]: "↓" };

/** Gold's technique as the engine computed it (daily): trend, momentum, volatility, and the trend on every TF. */
export function TechCard({ an, error, i = 0 }: { an?: GoldAnalysis; error?: Error; i?: number }) {
  const t = an?.technical;
  return (
    <Card title="Technika zlata (výpočet FTI)" icon={<Icon name="chart" size={16} />} i={i} id="technika-fti"
          extra={t && <span className="card-note">denní data k {shortDate(t.as_of)}</span>}>
      {!t ? (
        <Missing error={error} what="Technika" />
      ) : (
        <>
          <div className="facts-row">
            <Fact label="Trend" value={t.trend_label} tip="Průměry 50/200, týdenní trend, struktura a regrese 50 dní" />
            <Fact label="Technické skóre" value={`${signed(t.tech_score)} z ±100`} tip="Vážený součet ukazatelů níže" />
            <Fact label="RSI 14" value={num(t.rsi14, 1)} tip={`RSI(14) z denních závěrů — ${t.rsi_state ?? ""}`} />
            <Fact label="Od SMA 50" value={t.sma50_pct == null ? "—" : `${signed(t.sma50_pct, 2)} %`} tip="Vzdálenost ceny od 50denního průměru" />
            <Fact label="Od SMA 200" value={t.sma200_pct == null ? "—" : `${signed(t.sma200_pct, 2)} %`} tip="Vzdálenost ceny od 200denního průměru" />
            <Fact label="Kolísavost 20 d" value={t.volatility20 == null ? "—" : `${num(t.volatility20, 1)} %`} tip="Roční historická volatilita z 20 denních výnosů" />
          </div>
          {t.trend_age_text && <p className="hint">{t.trend_age_text}</p>}
          {(t.groups ?? []).map((g) => (
            <div key={g.key} className="table-scroll">
              <table className="dtable">
                <caption>{g.title}</caption>
                <tbody>
                  {g.items.map((it) => (
                    <tr key={it.name} title={it.text}>
                      <td>{it.name}</td>
                      <td className="num">{it.value}</td>
                      <td className={it.signal > 0 ? "pos" : it.signal < 0 ? "neg" : "zero"} aria-label={it.signal > 0 ? "nahoru" : it.signal < 0 ? "dolů" : "neutrálně"}>
                        {ARROW[it.signal] ?? "→"}
                      </td>
                      <td className="muted">{it.text}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          {an?.mtf && (
            <div className="table-scroll">
              <table className="dtable">
                <caption>Trend na časových rámcích (EMA 20/50, ADX, struktura)</caption>
                <tbody>
                  {an.mtf.timeframes.map((r) => (
                    <tr key={r.tf} title={`${r.text} · data k ${formatDateTime(r.as_of)}`}>
                      <td>{r.tf_label}</td>
                      <td className={r.direction === "up" ? "pos" : r.direction === "down" ? "neg" : "zero"}>{r.word}</td>
                      <td>{r.strength ?? ""}</td>
                      <td className="num">ADX {num(r.adx, 1)}</td>
                      <td className="muted">{r.text}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function Fact({ label, value, tip }: { label: string; value: ReactNode; tip: string }) {
  return (
    <div className="fact" title={tip}>
      <span className="label">{label}</span>
      <strong className="num">{value}</strong>
    </div>
  );
}

/** Supports, resistances and Fibonacci levels from the engine. */
export function LevelsCard({ an, error, i = 0 }: { an?: GoldAnalysis; error?: Error; i?: number }) {
  const t = an?.technical;
  const res = [...(t?.resistances ?? [])].sort((a, b) => b.price - a.price);
  const sup = [...(t?.supports ?? [])].sort((a, b) => b.price - a.price);
  return (
    <Card title="Zóny: podpory a rezistence" icon={<Icon name="layers" size={16} />} i={i} id="zony"
          extra={t && <span className="card-note">denní data k {shortDate(t.as_of)}</span>}>
      {!t ? (
        <Missing error={error} what="Zóny" />
      ) : (
        <>
          <div className="table-scroll">
            <table className="dtable">
              <thead>
                <tr>
                  <th>Úroveň</th>
                  <th>Cena</th>
                  <th>Od ceny</th>
                  <th>Dotyky</th>
                </tr>
              </thead>
              <tbody>
                {res.map((l, k) => (
                  <tr key={`r${l.price}`} title={`${l.label} · výpočet FTI z denních svíček`}>
                    <td className="neg">R{res.length - k} · {l.label}</td>
                    <td className="num">{num(l.price)}</td>
                    <td className="num">{signed(l.pct, 2)} %</td>
                    <td className="num">{l.touches ?? "—"}</td>
                  </tr>
                ))}
                <tr className="lvl-now">
                  <td>Cena</td>
                  <td className="num">{num(t.last_price)}</td>
                  <td />
                  <td />
                </tr>
                {sup.map((l, k) => (
                  <tr key={`s${l.price}`} title={`${l.label} · výpočet FTI z denních svíček`}>
                    <td className="pos">S{k + 1} · {l.label}</td>
                    <td className="num">{num(l.price)}</td>
                    <td className="num">{signed(l.pct, 2)} %</td>
                    <td className="num">{l.touches ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {t.fibonacci && t.fibonacci.length > 0 && (
            <>
              <h3 className="sub">Fibonacci</h3>
              <p className="hint">{t.fibonacci_text}</p>
              <ul className="chips">
                {t.fibonacci.map((f) => (
                  <li key={f.ratio} className="chip num" title={`${signed(f.pct, 2)} % od ceny`}>
                    {num(f.ratio * 100, 1)} % · {num(f.price)}
                  </li>
                ))}
              </ul>
            </>
          )}
          {an?.decision && (
            <>
              <h3 className="sub">Co by změnilo obraz</h3>
              <div className="two-col-list">
                <ul className="plain-list">
                  {an.decision.bull.filter((x) => x.kind === "price").map((x) => (
                    <li key={x.title} className="pos">{x.title} <small className="muted">— {x.detail}</small></li>
                  ))}
                </ul>
                <ul className="plain-list">
                  {an.decision.bear.filter((x) => x.kind === "price").map((x) => (
                    <li key={x.title} className="neg">{x.title} <small className="muted">— {x.detail}</small></li>
                  ))}
                </ul>
              </div>
            </>
          )}
        </>
      )}
    </Card>
  );
}

/** Long-run seasonality of gold by month. */
export function SeasonCard({ an, error, i = 0 }: { an?: GoldAnalysis; error?: Error; i?: number }) {
  const g = an?.seasonality_long?.gold;
  const now = new Date().getMonth() + 1;
  return (
    <Card title="Sezónnost zlata" icon={<Icon name="calendar" size={16} />} i={i} id="sezonnost"
          extra={<span className="card-note">průměrná měsíční změna, ne předpověď</span>}>
      {!g ? (
        <Missing error={error} what="Sezónnost" />
      ) : (
        <>
          {an?.seasonality && <p className="hint" style={{ marginTop: 0 }}>{an.seasonality.current_text} {an.seasonality.next_text}</p>}
          <div className="table-scroll">
            <table className="dtable">
              <thead>
                <tr>
                  <th>Měsíc</th>
                  <th>Ø 5 let</th>
                  <th>Ø 10 let</th>
                  <th>Ø 15 let</th>
                  <th>Růst v 10 letech</th>
                </tr>
              </thead>
              <tbody>
                {g.months.map((m) => (
                  <tr key={m.month} className={m.month === now ? "is-now" : ""}>
                    <td>{m.name}</td>
                    {[m.avg5, m.avg10, m.avg15].map((v, k) => (
                      <td key={k} className={`num ${v == null ? "" : v > 0 ? "pos" : v < 0 ? "neg" : ""}`}>{v == null ? "—" : `${signed(v, 2)} %`}</td>
                    ))}
                    <td className="num">{m.win10 == null ? "—" : `${num(m.win10, 0)} % (n ${m.n10})`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {an?.seasonality?.note && <p className="src">{an.seasonality.note}</p>}
        </>
      )}
    </Card>
  );
}

/** The dollar (synthetic DXY) and what it means for gold. */
export function DxyCard({ an, error, i = 0 }: { an?: GoldAnalysis; error?: Error; i?: number }) {
  const d = an?.dxy;
  return (
    <Card title="Dolarový index DXY (přepočet)" icon={<Icon name="globe" size={16} />} i={i} id="dxy">
      {!d ? (
        <Missing error={error} what="DXY" />
      ) : (
        <>
          <p className="big-num num" title={`${d.source}${d.verified ? `\n${d.verified}` : ""}`}>{num(d.price, 2)}</p>
          <p className="hint" style={{ marginTop: 0 }}>{d.text}</p>
          <p className="src">{d.source} {d.verified}</p>
        </>
      )}
    </Card>
  );
}

/** Headline risk from the news (wars, sanctions, pandemics …) as the engine sorted it. */
export function HeadlineRisk({ an, i = 0 }: { an?: GoldAnalysis; i?: number }) {
  const h = an?.headline_risk;
  if (!h) return null;
  return (
    <Card title={`Riziko ze zpráv: ${h.word}`} icon={<Icon name="bolt" size={16} />} i={i} id="riziko-zprav">
      <ul className="news">
        {h.items.slice(0, 6).map((n) => (
          <li key={n.url}>
            <a href={n.url} target="_blank" rel="noreferrer">
              <span className="news-tags">{n.topic && <span className="mtag">{n.topic}</span>}</span>
              <span className="news-title">{n.title}</span>
              <span className="news-meta">{n.source} · {relativeTime(n.published_at)} <Icon name="external" size={12} /></span>
            </a>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** The verdict's factors (fundament, technique, COT …) with their weights. */
export function VerdictFactors({ an, i = 0 }: { an?: GoldAnalysis; i?: number }) {
  const v = an?.verdict;
  if (!v) return null;
  return (
    <Card title="Faktory verdiktu FTI" icon={<Icon name="target" size={16} />} i={i} id="faktory" extra={<span className="card-note">pravidla, ne AI</span>}>
      <ul className="mods">
        {v.factors.map((f) => (
          <li key={f.key} title={`${f.sentence}\nváha ${Math.round(f.weight * 100)} % · ${f.detail}`}>
            <span className="mod-label">{f.label}</span>
            <CenterBar value={f.score} max={1} label={`${f.label} ${signed(f.score, 2)}`} />
            <span className={`mod-val num ${f.direction === "up" ? "pos" : f.direction === "down" ? "neg" : "zero"}`}>{signed(f.score, 2)}</span>
          </li>
        ))}
      </ul>
      <p className="src">{v.summary} Jistota: {v.confidence}.</p>
    </Card>
  );
}
