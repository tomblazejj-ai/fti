import { CandleChart } from "../../components/CandleChart";
import { Donut } from "../../components/Donut";
import { Gauge } from "../../components/Gauge";
import { Icon } from "../../components/Icon";
import { Panel, ScoreChip } from "../../components/Panel";
import { Unavailable } from "../../components/ui";
import { formatDate, formatDateTime, shortDate, signed } from "../../lib/format";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
}
import type { Analysis, Cot, Decision, DecisionItem, Level, Mtf, Scorecard, TrendBlend, TrendDir, WrittenSummary } from "../../lib/types";
import { CalendarTable } from "./CalendarTable";
import { KeyNews } from "./KeyNews";
import { ScoreHistory, ScoreOverview } from "../../components/Tra";
import { HeadlineRiskPanel, NewsLockBanner } from "./Methodology";

const ICON: Record<TrendDir, string> = { up: "▲", down: "▼", sideways: "◆" };
const TONE: Record<TrendDir, string> = { up: "bull", down: "bear", sideways: "flat" };
const ACTION_TONE = { long: "bull", short: "bear", wait: "flat" } as const;
const ACTION_ICON = { long: "▲", short: "▼", wait: "◆" } as const;

export function chartLevels(a: Analysis): (Level & { kind: "support" | "resistance" })[] {
  const out: (Level & { kind: "support" | "resistance" })[] = [];
  if (a.verdict.support) out.push({ ...a.verdict.support, kind: "support" });
  if (a.verdict.resistance) out.push({ ...a.verdict.resistance, kind: "resistance" });
  return out;
}

export function Overview({ analysis, onTab }: { analysis: Analysis; onTab: (t: string) => void }) {
  return (
    <div className="ov">
      <VerdictBanner a={analysis} />
      <NewsLockBanner calendar={analysis.calendar} quiet />
      <div className="grid g-chart">
        <Panel title="Graf" tag="XAU/USD" icon="candles" className="span-8">
          <CandleChart code="XAUUSD" levels={chartLevels(analysis)} unit="ceny v USD" />
        </Panel>
        <SummaryPanel s={analysis.summary} />
      </div>
      {analysis.tra && (
        <div className="grid g-chart">
          <ScoreOverview pack={analysis.tra.xau} tag="XAU/USD" subject="zlato" note={analysis.tra.proxies_note} className="span-4" />
          <ScoreHistory code="XAUUSD" pack={analysis.tra.xau} momentum={analysis.tra.momentum?.xau} refreshKey={Date.parse(analysis.computed_at)}
                        className="span-8" />
        </div>
      )}
      <div className="grid g-3">
        <ScorePanel sc={analysis.scorecard} />
        <Panel title="Technika" tag="XAU/USD" icon="gauge" note="denní graf">
          {analysis.technical ? (
            <>
              <Gauge value={Math.round(analysis.technical.tech_score / 10)} />
              <p className="center small muted">{analysis.technical.trend_label} · RSI {analysis.technical.rsi14 ?? "—"}</p>
              <button type="button" className="link-more" onClick={() => onTab("tech")}>Celá technika <Icon name="chevronRight" size={14} /></button>
            </>
          ) : (
            <Unavailable>Cena zlata teď není k dispozici.</Unavailable>
          )}
        </Panel>
        <Panel title="Ekonomický kalendář" tag="XAU/USD" icon="calendar">
          <CalendarTable calendar={analysis.calendar} />
        </Panel>
      </div>
      <div className="grid g-2">
        <DecisionPanel d={analysis.decision} />
        <TrendPanel mtf={analysis.mtf} />
      </div>
      <HeadlineRiskPanel h={analysis.headline_risk} />
      <div className="grid g-2">
        <KeyNews mood={analysis.news} />
        <CotMini cot={analysis.cot} onMore={() => onTab("cot")} />
      </div>
    </div>
  );
}

function VerdictBanner({ a }: { a: Analysis }) {
  const v = a.verdict;
  const tone = ACTION_TONE[v.action];
  const sc = a.scorecard;
  return (
    <section className={`verdict tone-${tone}`} aria-labelledby="verdict-title">
      <div className="verdict-main">
        <h1 id="verdict-title" className="verdict-dir">
          <span className="verdict-arrow" aria-hidden="true">{ACTION_ICON[v.action]}</span> {v.direction_text}
        </h1>
        <p className="verdict-action">
          <strong>{v.action_text}</strong> {v.timing}
        </p>
        <p className="verdict-why muted">
          {v.summary} · jistota <strong>{v.confidence}</strong> · přepočteno {formatTime(a.computed_at)} (každých 5 min)
        </p>
      </div>
      <div className="verdict-side">
        {a.mtf && <TrendPills mtf={a.mtf} />}
        {sc && (
          <div className="final-mini" title={sc.note}>
            <span className="muted small">Celkové skóre</span>
            <ScoreChip value={sc.final} big />
            <span className="small">{sc.final_label}</span>
          </div>
        )}
      </div>
    </section>
  );
}

export function TrendPills({ mtf }: { mtf: Mtf }) {
  return (
    <div className="tpills" aria-label="Trend">
      {[mtf.intraday, mtf.swing, mtf.overall].map((b) => (b ? <TrendPill key={b.key} b={b} /> : null))}
    </div>
  );
}

function TrendPill({ b }: { b: TrendBlend }) {
  return (
    <span className={`tpill t-${TONE[b.lean]}`}>
      <span className="tpill-label">{b.label.replace(" trend", "")}</span>
      <strong>
        <span aria-hidden="true">{ICON[b.lean]}</span> {b.word}
      </strong>
    </span>
  );
}

function SummaryPanel({ s }: { s: WrittenSummary | null | undefined }) {
  return (
    <Panel title="Shrnutí" tag="XAU/USD" icon="sparkle" className="span-4 summary-panel">
      {!s ? (
        <Unavailable>Shrnutí se složí při příští aktualizaci.</Unavailable>
      ) : (
        <div className="sum">
          <p className="sum-date muted">{formatDate(s.date)}</p>
          <p className="sum-text">{s.text}</p>
          <ul className="sum-list">
            {s.bullets.map((b) => <li key={b}>{b}</li>)}
          </ul>
          {s.outlook.length > 0 && (
            <>
              <h3 className="sum-h">Technický výhled</h3>
              <ul className="sum-list">
                {s.outlook.map((b) => <li key={b}>{b}</li>)}
              </ul>
            </>
          )}
          <p className="sum-note muted small">{s.note}</p>
        </div>
      )}
    </Panel>
  );
}

function ScorePanel({ sc }: { sc: Scorecard | null | undefined }) {
  return (
    <Panel title="Skóre faktorů" tag="XAU/USD" icon="layers">
      {!sc ? (
        <Unavailable>Skóre se spočítá při příští aktualizaci.</Unavailable>
      ) : (
        <>
          <ul className="score-grid">
            {sc.items.map((i) => (
              <li key={i.key}>
                <span>{i.label}</span>
                <ScoreChip value={i.score} />
              </li>
            ))}
          </ul>
          <div className={`final-row ${sc.final > 0 ? "is-pos" : sc.final < 0 ? "is-neg" : ""}`}>
            <span>
              Celkové skóre <span className="muted small">(−10 až +10)</span>
            </span>
            <span className="final-right">
              <span className="small">{sc.final_label}</span>
              <ScoreChip value={sc.final} big />
            </span>
          </div>
          <p className="muted small">{sc.note}</p>
        </>
      )}
    </Panel>
  );
}

const KIND_ICON: Record<string, "chart" | "bank" | "users" | "line" | "target"> = { price: "target", fund: "bank", cot: "users", trend: "line", dxy: "chart" };

function DecisionPanel({ d }: { d: Decision | null | undefined }) {
  return (
    <Panel title="Co rozhodne o směru" tag="XAU/USD" icon="target">
      {!d ? (
        <Unavailable>Spočítá se při příští aktualizaci.</Unavailable>
      ) : (
        <>
          <p className="dec-head">{d.headline}</p>
          <div className="dec-cols">
            <DecisionList title="Zlato poroste, když…" tone="bull" items={d.bull} />
            <DecisionList title="Zlato bude klesat, když…" tone="bear" items={d.bear} />
          </div>
          {d.events.length > 0 && (
            <div className="dec-events">
              <h3>Rozhodující události</h3>
              <ul>
                {d.events.map((e) => (
                  <li key={`${e.date}-${e.name}`}>
                    <span className="dec-date">{shortDate(e.date)}{e.time ? ` ${e.time}` : ""}</span>
                    <strong>{e.name}</strong>
                    {e.up_if && (
                      <span className="small">
                        <span className="tone-bullish">▲ {e.up_if}</span> · <span className="tone-bearish">▼ {e.down_if}</span>
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </Panel>
  );
}

function DecisionList({ title, tone, items }: { title: string; tone: "bull" | "bear"; items: DecisionItem[] }) {
  return (
    <div className={`dec-col dec-${tone}`}>
      <h3>
        <span aria-hidden="true">{tone === "bull" ? "▲" : "▼"}</span> {title}
      </h3>
      <ul>
        {items.map((i) => (
          <li key={i.title} className={i.active ? "is-active" : ""}>
            <span className="dec-ico"><Icon name={KIND_ICON[i.kind] ?? "target"} size={15} /></span>
            <span>
              <span className="dec-title">{i.title}</span>
              <span className="dec-detail muted small">{i.detail}</span>
            </span>
            {i.active && <span className="dec-now">platí teď</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function TrendPanel({ mtf, tag = "XAU/USD" }: { mtf: Mtf | null | undefined; tag?: string }) {
  return (
    <Panel title="Trend podle timeframu" tag={tag} icon="line" note={mtf?.price_time ? `poslední svíčka ${formatDateTime(mtf.price_time)}` : undefined}>
      {!mtf || !mtf.timeframes.length ? (
        <Unavailable>Ceny pro timeframy teď nejsou k dispozici.</Unavailable>
      ) : (
        <>
          <TrendPills mtf={mtf} />
          <div className="tf-strip">
            {mtf.timeframes.map((t) => (
              <div key={t.tf} className={`tfx t-${TONE[t.direction]}`} aria-label={`${t.tf}: ${t.word}, ${t.strength}`} role="group">
                <span className="tfx-name">{t.tf}</span>
                <span className="tfx-arrow" aria-hidden="true">{ICON[t.direction]}</span>
                <span className="tfx-word">{t.word}</span>
                <span className="tfx-str">
                  {[1, 2, 3].map((k) => (
                    <i key={k} className={k <= (t.strength === "silný" ? 3 : t.strength === "střední" ? 2 : 1) ? "on" : ""} />
                  ))}
                </span>
                <span className={`tfx-ch ${t.change_pct > 0 ? "pos" : t.change_pct < 0 ? "neg" : ""}`}>{signed(t.change_pct, 2)} %</span>
              </div>
            ))}
          </div>
          <p className="trend-advice">{mtf.advice}</p>
        </>
      )}
    </Panel>
  );
}

function CotMini({ cot, onMore }: { cot: Cot | null; onMore: () => void }) {
  const g = cot?.groups?.[0];
  return (
    <Panel title="COT – fondy" tag="Gold" icon="users" note={cot ? `k ${shortDate(cot.as_of)}` : undefined}>
      {!cot ? (
        <Unavailable>Data COT teď nejsou k dispozici.</Unavailable>
      ) : (
        <div className="cot-mini">
          <Donut long={g?.long ?? cot.spec_long} short={g?.short ?? cot.spec_short} label={g ? "Hedgeové fondy" : "Spekulanti"} size={130} />
          <div className="cot-mini-txt">
            <p><strong>{cot.texts[0]}</strong></p>
            <p className="small">
              Za týden <span className={cot.change_1w > 0 ? "tone-bullish" : "tone-bearish"}>{signed(cot.change_1w, 0)}</span> kontraktů · COT index{" "}
              {cot.cot_index_3y !== null ? Math.round(cot.cot_index_3y) : "—"}/100
            </p>
            {cot.schedule && <p className="muted small">Další report {formatDate(cot.schedule.next_release.slice(0, 10))} ve 21:30 (obvykle)</p>}
            <button type="button" className="link-more" onClick={onMore}>Detail COT <Icon name="chevronRight" size={14} /></button>
          </div>
        </div>
      )}
    </Panel>
  );
}
