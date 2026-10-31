import { useTickers } from "../hooks/useTickers";
import { shortDate } from "../lib/format";
import type { Quote } from "../lib/types";

function price(q: Quote): string {
  return q.price.toLocaleString("cs-CZ", { minimumFractionDigits: q.digits, maximumFractionDigits: q.digits });
}

// FX and spot gold stop with the spot market; Bitcoin trades 24/7.
const FOLLOWS_SPOT = new Set(["PAXGUSD", "DXY", "EURUSD", "GBPUSD"]);

/** Live quotes (Kraken, every 60 s) + daily closes (FRED, marked with their date). */
export function TickerBar() {
  const t = useTickers();
  const quotes = [...(t?.live ?? []), ...(t?.daily ?? [])];
  const closed = t?.market && !t.market.open;
  if (!quotes.length) return <div className="ticker" aria-hidden="true" />;
  return (
    <div className="ticker" role="region" aria-label="Kurzy trhů">
      <span className="ticker-label">
        <span className={`live-dot${closed ? " is-off" : ""}`} aria-hidden="true" /> {closed ? "Trh zavřen" : "Živě"}
      </span>
      <div className="ticker-track">
        {quotes.map((q) => {
          const ch = q.change_pct;
          const tone = ch === null ? "" : ch > 0 ? "pos" : ch < 0 ? "neg" : "";
          const weekend = closed && q.live && FOLLOWS_SPOT.has(q.symbol);
          return (
            <span
              key={q.symbol}
              className={`tick${q.live ? "" : " is-daily"}${weekend ? " is-closed" : ""}`}
              title={
                !q.live
                  ? `${q.source}, denní závěr k ${shortDate(q.as_of)}`
                  : weekend
                    ? `${q.source} — spotový trh je zavřený, tohle je víkendový obchod (jen orientačně)`
                    : `${q.source}, živě`
              }
            >
              <span className="tick-name">{q.label}</span>
              <span className="tick-price">{price(q)}</span>
              {ch !== null && !weekend && (
                <span className={`tick-ch ${tone}`}>
                  {ch > 0 ? "+" : ch < 0 ? "−" : ""}
                  {Math.abs(ch).toLocaleString("cs-CZ", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} %
                </span>
              )}
              {weekend && <span className="tick-d">víkend</span>}
              {!q.live && <span className="tick-d">D</span>}
            </span>
          );
        })}
      </div>
    </div>
  );
}
