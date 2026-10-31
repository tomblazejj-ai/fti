import { useState } from "react";
import { CandleChart } from "../components/CandleChart";
import { Icon } from "../components/Icon";
import { ErrorState, Loading } from "../components/ui";
import { useTickers } from "../hooks/useTickers";
import { formatDateTime, relativeTime, shortDate } from "../lib/format";
import type { MarketCard } from "../lib/types";
import { priceText, scoreText, tone, useMarkets } from "./Markets";

const LIVE_SYMBOL: Record<string, string> = { XAUUSD: "PAXGUSD", EURUSD: "EURUSD", GBPUSD: "GBPUSD" };
const LINE_ONLY = new Set(["USDJPY", "USOIL"]);

/** One market: score, why, what speaks against it, what to watch, retail, chart. */
export function MarketDetail({ code }: { code: string }) {
  const data = useMarkets();
  if (data.error && !data.data) return <main className="page mi-page"><ErrorState message={data.error.message} onRetry={data.reload} /></main>;
  if (!data.data) return <main className="page mi-page"><Loading label="Načítám trh…" /></main>;
  const m = data.data.markets.find((x) => x.code === code);
  if (!m) return <main className="page mi-page"><p className="state state-unavailable">Trh „{code}“ v přehledu není.</p></main>;
  return (
    <main className="page mi-page">
      <a className="mi-back" href="#/"><Icon name="chevronLeft" size={16} /> Všechny trhy</a>
      <Hero m={m} />
      {m.gold && <GoldPlan m={m} />}
      <div className="md-grid">
        <section className="md-card md-args">
          <h2 className="mi-h">{m.bias === "SHORT" ? "ARGUMENTY PODPORUJÍCÍ POKLES" : m.bias === "LONG" ? "ARGUMENTY PODPORUJÍCÍ RŮST" : "CO MLUVÍ PRO RŮST"}</h2>
          <Args items={m.for} empty="Žádný faktor teď tento směr výrazně nepodporuje." />
          <h2 className="mi-h">{m.bias === "NEUTRÁLNÍ" ? "CO MLUVÍ PRO POKLES" : "PROTIARGUMENTY A RIZIKA"}</h2>
          <Args items={m.against} empty="Žádný faktor teď výrazně nejde proti." />
          <h2 className="mi-h">CO DÁL SLEDOVAT</h2>
          {m.watch.length ? (
            <ul className="md-watch">
              {m.watch.map((w) => (
                <li key={`${w.datetime}-${w.title}`}>
                  <span>
                    <strong>{w.when}:</strong> {w.title}
                    {(w.forecast || w.previous) && (
                      <small className="muted"> · {w.forecast ? `prognóza ${w.forecast}` : ""}{w.forecast && w.previous ? ", " : ""}{w.previous ? `minule ${w.previous}` : ""}</small>
                    )}
                  </span>
                  <span className={`md-impact imp-${w.impact}`}>{w.impact_text}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted small">V příštích dnech v kalendáři nic důležitého. <a href="#/kalendar">Celý kalendář</a></p>
          )}
        </section>
        <div className="md-side">
          {m.retail && <Retail m={m} />}
          <Breakdown m={m} />
        </div>
      </div>
      <section className="md-card md-chart" aria-label={`Graf ${m.name}`}>
        <h2 className="mi-h">GRAF</h2>
        <CandleChart code={m.code} digits={m.digits > 3 ? 4 : m.digits} initialTf="D1" lineOnly={LINE_ONLY.has(m.code)} />
      </section>
      {m.news.length > 0 && (
        <section className="md-card">
          <h2 className="mi-h">ZPRÁVY K TRHU</h2>
          <ul className="md-news">
            {m.news.map((n) => (
              <li key={n.url}>
                <a href={n.url} target="_blank" rel="noreferrer">{n.title}</a>
                <span className="muted small">{n.source} · {relativeTime(n.published_at)}{n.translated ? " · strojový překlad" : ""}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <p className="mi-note muted small">
        Přepočteno {formatDateTime(data.data.computed_at)}. {m.missing.length > 0 && `Bez dat: ${m.missing.join(", ")} — skóre je přepočtené z ostatních kategorií. `}
        Není to investiční doporučení.
      </p>
    </main>
  );
}

function Hero({ m }: { m: MarketCard }) {
  const t = useTickers();
  const live = LIVE_SYMBOL[m.code] ? t?.live.find((q) => q.symbol === LIVE_SYMBOL[m.code]) : undefined;
  const ch = live?.change_pct ?? m.price?.change_pct ?? null;
  return (
    <section className={`md-hero t-${tone(m.score10)}`}>
      <div>
        <span className="mi-eyebrow">FUNDAMENTÁLNÍ DETAIL TRHU</span>
        <h1 className="md-name">{m.name.replace("/", "")}</h1>
        <p className="md-word">{m.word}</p>
        <div className="md-chips">
          <span className={`md-bias ${m.bias === "LONG" ? "pos" : m.bias === "SHORT" ? "neg" : ""}`}>{m.bias}</span>
          {m.trend && <span className="md-chip">Trend: {m.trend.toLowerCase()}</span>}
          <span className="md-chip">
            {priceText(m, live?.price)}
            {ch !== null && <b className={tone(ch)}> {ch > 0 ? "+" : ch < 0 ? "−" : ""}{Math.abs(ch).toLocaleString("cs-CZ")} %</b>}
            {!live && m.price && !m.price.live && <small> · k {shortDate(m.price.as_of)}</small>}
          </span>
        </div>
      </div>
      <div className="md-score" aria-label={`Skóre ${scoreText(m.score10)} z 10`}>
        <strong className={tone(m.score10)}>{scoreText(m.score10)}</strong>
        <span>/ 10</span>
      </div>
    </section>
  );
}

function Args({ items, empty }: { items: MarketCard["for"]; empty: string }) {
  if (!items.length) return <p className="muted small">{empty}</p>;
  return (
    <ul className="md-list">
      {items.map((a) => (
        <li key={a.label}>
          <span className="md-tag">{a.label}</span> {a.text}
        </li>
      ))}
    </ul>
  );
}

function Retail({ m }: { m: MarketCard }) {
  const r = m.retail!;
  return (
    <section className="md-card md-retail" aria-label="Retail sentiment">
      <span className="mi-eyebrow">RETAIL SENTIMENT</span>
      <div className="rs-bar" role="img" aria-label={`${Math.round(r.long_pct)} % long, ${Math.round(r.short_pct)} % short`}>
        <i className="rs-long" style={{ width: `${r.long_pct}%` }} />
        <i className="rs-short" style={{ width: `${r.short_pct}%` }} />
      </div>
      <div className="rs-legend">
        <strong className="pos">{Math.round(r.long_pct)} % LONG</strong>
        <strong className="neg">{Math.round(r.short_pct)} % SHORT</strong>
      </div>
      <div className="rs-score">
        <span>
          <span className="mi-eyebrow">FUNDAMENTÁLNÍ SKÓRE</span>
          <small>{m.word}</small>
        </span>
        <strong className={tone(m.score10)}>{scoreText(m.score10)} / 10</strong>
      </div>
      <p className={`rs-box rs-${r.tone}`}>
        <strong>{r.head}</strong> {r.text}
      </p>
      <p className="muted small">{r.source}{r.as_of ? ` Data k ${shortDate(r.as_of)}.` : ""}</p>
    </section>
  );
}

function Breakdown({ m }: { m: MarketCard }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="md-card md-break">
      <button type="button" className="md-break-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="mi-eyebrow">ROZPIS SKÓRE</span>
        <span className="muted small">{m.raw > 0 ? "+" : ""}{m.raw} z ±{m.possible} {open ? "▲" : "▼"}</span>
      </button>
      <ul className="md-comps">
        {m.components.map((c) => (
          <li key={c.key}>
            <span className="md-comp-label">{c.label}</span>
            <span className={`md-comp-score ${c.score === null ? "na" : tone(c.score)}`}>
              {c.score === null ? "—" : scoreText(c.score)}
              <small>/±{c.max}</small>
            </span>
            {open && <p className="small muted">{c.text}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function GoldPlan({ m }: { m: MarketCard }) {
  const g = m.gold!;
  return (
    <section className={`md-card md-plan a-${g.action}`}>
      <div>
        <span className="mi-eyebrow">OBCHODNÍ PLÁN ZLATA · METODIKA FUNDED MIND</span>
        <p className="md-plan-text">{g.headline}</p>
      </div>
      <div className="md-plan-links">
        <a className="mi-open" href="#/pomocnik">Checklist a plán <Icon name="chevronRight" size={16} /></a>
        <a className="md-link" href="#/instrument/XAUUSD">Podrobný rozbor zlata</a>
      </div>
    </section>
  );
}
