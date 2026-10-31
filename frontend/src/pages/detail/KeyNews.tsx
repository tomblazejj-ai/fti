import { Panel } from "../../components/Panel";
import { Unavailable } from "../../components/ui";
import { relativeTime } from "../../lib/format";
import type { NewsMood } from "../../lib/types";

const IMPACT = {
  bullish: { icon: "▲", word: "pro růst zlata", tone: "bull" },
  bearish: { icon: "▼", word: "pro pokles zlata", tone: "bear" },
  neutral: { icon: "◆", word: "bez jasného směru", tone: "flat" },
} as const;

/** The few headlines with the most weight for gold right now. */
export function KeyNews({ mood }: { mood: NewsMood | null | undefined }) {
  const items = mood?.key ?? [];
  return (
    <Panel title="Hlavní zprávy pro zlato" tag="XAU/USD" icon="news" id="keynews" note={mood ? `za ${mood.hours} h` : undefined}>
      {items.length === 0 ? (
        <Unavailable>Za poslední dny žádná zpráva s jasným dopadem na zlato.</Unavailable>
      ) : (
        <>
          {mood && (
            <div className="mood">
              <span className="mood-bar" aria-hidden="true">
                <span className="mood-up" style={{ flexGrow: Math.max(mood.bullish, 0.01) }} />
                <span className="mood-down" style={{ flexGrow: Math.max(mood.bearish, 0.01) }} />
              </span>
              <span className="small">
                <span className="tone-bullish">▲ {mood.bullish} pro růst</span> · <span className="tone-bearish">▼ {mood.bearish} pro pokles</span> z{" "}
                {mood.count} zpráv
              </span>
            </div>
          )}
          <ul className="keynews">
            {items.map((n) => {
              const im = IMPACT[n.impact];
              return (
                <li key={n.url} className={`keynews-item k-${im.tone}`}>
                  <a href={n.url} target="_blank" rel="noreferrer" className="keynews-title">
                    {n.title}
                  </a>
                  <div className="keynews-meta small">
                    <span className={`k-impact k-${im.tone}`}>
                      <span aria-hidden="true">{im.icon}</span> {im.word}
                    </span>
                    {n.factors.map((f) => (
                      <span key={f} className="chip">{f}</span>
                    ))}
                    {n.gold && <span className="chip chip-gold">o zlatě</span>}
                    <span className="muted">
                      {n.source} · {relativeTime(n.published_at)}
                      {n.translated && " · strojový překlad"}
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </Panel>
  );
}
