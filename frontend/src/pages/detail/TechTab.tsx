import { CandleChart } from "../../components/CandleChart";
import { Gauge } from "../../components/Gauge";
import { Panel } from "../../components/Panel";
import { Unavailable } from "../../components/ui";
import { shortDate, signed, usd } from "../../lib/format";
import type { Analysis, Level, Signal, Technical } from "../../lib/types";
import { chartLevels, TrendPanel } from "./Overview";

const SIG = {
  1: { icon: "▲", tone: "bullish", word: "býčí" },
  0: { icon: "◆", tone: "neutral", word: "neutrální" },
  [-1]: { icon: "▼", tone: "bearish", word: "medvědí" },
} as const;

/** Chart first, one score, three lights — the detail is one click away. */
export function TechTab({ analysis }: { analysis: Analysis }) {
  const t = analysis.technical;
  return (
    <div className="ov">
      <Panel title="Graf" tag="XAU/USD" icon="candles">
        <CandleChart code="XAUUSD" levels={chartLevels(analysis)} initialTf="D1" unit="ceny v USD" />
      </Panel>
      {!t ? (
        <Unavailable>Cenová data zlata se nepodařilo stáhnout, technickou analýzu teď nelze spočítat.</Unavailable>
      ) : (
        <>
          <div className="grid g-3">
            <Panel title="Technické skóre" tag="D1" icon="gauge">
              <Gauge value={Math.round(t.tech_score / 10)} caption={`${t.trend_label} · data k ${shortDate(t.as_of)}`} />
            </Panel>
            <Panel title="Signály" tag="D1" icon="bolt">
              <Lights t={t} />
            </Panel>
            <Panel title="Klíčové úrovně" tag="D1" icon="target">
              <Levels t={t} />
            </Panel>
          </div>
          <TrendPanel mtf={analysis.mtf} />
          <details className="panel more-panel">
            <summary>Podrobně: všechny ukazatele, Fibonacci, změny ceny</summary>
            <Details t={t} />
          </details>
        </>
      )}
    </div>
  );
}

function Lights({ t }: { t: Technical }) {
  return (
    <ul className="lights">
      {t.groups.map((g) => {
        const scored = g.items.filter((i) => i.weight);
        const sum = scored.reduce((a, i) => a + i.signal * i.weight, 0);
        const w = scored.reduce((a, i) => a + i.weight, 0);
        const v = w ? sum / w : 0;
        const tone = !w ? "info" : v > 0.25 ? "bull" : v < -0.25 ? "bear" : "flat";
        const word = !w ? "informativní" : v > 0.25 ? "pro růst" : v < -0.25 ? "pro pokles" : "smíšené";
        return (
          <li key={g.key} className={`light l-${tone}`}>
            <span className="light-dot" aria-hidden="true" />
            <span className="light-head">
              <strong>{g.title}</strong>
              <span className="muted small">{word}</span>
            </span>
            <span className="light-items small">
              {g.items.map((i) => (
                <span key={i.name} title={i.text} className={`tone-${i.weight ? SIG[i.signal as Signal].tone : "neutral"}`}>
                  {i.weight ? SIG[i.signal as Signal].icon : "ⓘ"} {i.name.split(" (")[0]}
                </span>
              ))}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function lv(l: Level) {
  return l.price ? usd(l.price, 0) : `${signed(l.pct)} %`;
}

function Levels({ t }: { t: Technical }) {
  return (
    <ul className="lv-list">
      {[...t.resistances].reverse().map((l, i) => (
        <li key={`r${i}`} className="lv-res">
          <span className="lv-price">{lv(l)}</span>
          <span className="muted small">{l.label}{(l.touches ?? 1) > 1 ? ` · ${l.touches}×` : ""}</span>
          <span className="small">{signed(l.pct)} %</span>
        </li>
      ))}
      <li className="lv-now">
        <span className="lv-price">{t.last_price ? usd(t.last_price, 0) : "cena"}</span>
        <span className="small">aktuální cena</span>
        <span />
      </li>
      {t.supports.map((l, i) => (
        <li key={`s${i}`} className="lv-sup">
          <span className="lv-price">{lv(l)}</span>
          <span className="muted small">{l.label}{(l.touches ?? 1) > 1 ? ` · ${l.touches}×` : ""}</span>
          <span className="small">{signed(l.pct)} %</span>
        </li>
      ))}
    </ul>
  );
}

const CHANGE_LABELS: [keyof Technical["changes"], string][] = [
  ["1d", "Den"], ["5d", "Týden"], ["20d", "Měsíc"], ["60d", "3 měsíce"], ["250d", "Rok"],
];

function Details({ t }: { t: Technical }) {
  return (
    <div className="details-body">
      <div className="chg-row">
        {CHANGE_LABELS.map(([k, label]) => {
          const v = t.changes[k];
          return (
            <div key={k} className="chg">
              <span className="muted small">{label}</span>
              <strong className={v === null ? "muted" : v > 0 ? "tone-bullish" : v < 0 ? "tone-bearish" : ""}>{v === null ? "—" : `${signed(v)} %`}</strong>
            </div>
          );
        })}
      </div>
      <p className="small">{t.trend_age_text}</p>
      <div className="tech-grid">
        {t.groups.map((g) => (
          <section key={g.key} className="tech-group">
            <h3>{g.title}</h3>
            <ul className="indicator-list">
              {g.items.map((it) => {
                const s = SIG[it.signal as Signal];
                return (
                  <li key={it.name} className="indicator">
                    <span className={`ind-sig tone-${it.weight ? s.tone : "neutral"}`} aria-label={it.weight ? s.word : "informativní"}>
                      {it.weight ? s.icon : "ⓘ"}
                    </span>
                    <span className="ind-name">{it.name}</span>
                    <span className="ind-value">{it.value}</span>
                    <span className="ind-text">{it.text}</span>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
        {t.fibonacci.length > 0 && (
          <section className="tech-group">
            <h3>Fibonacci</h3>
            <p className="muted small">{t.fibonacci_text}</p>
            <table className="lvl-table">
              <tbody>
                {t.fibonacci.map((f) => (
                  <tr key={f.ratio}>
                    <td>{(f.ratio * 100).toFixed(1).replace(".", ",")} %</td>
                    {f.price ? <td className="num lvl-pct">{usd(f.price, 0)}</td> : null}
                    <td className="num">{signed(f.pct)} %</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
      </div>
      <p className="muted small">
        {t.unit === "USD"
          ? "Technika vychází z denních svíček PAXG/USD (Kraken) — token krytý fyzickým zlatem, sleduje spot XAUUSD."
          : "Záložní zdroj: denní futures index zlata z FRED (NASDAQQGLDI) — úrovně jen v %."}
      </p>
    </div>
  );
}
