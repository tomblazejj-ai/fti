import { useTickers } from "../hooks/useTickers";
import { pct, price, shortDate } from "../lib/format";

// FX and spot gold stop with the spot market; the token price runs on over the weekend.
const FOLLOWS_SPOT = new Set(["PAXGUSD", "DXY", "EURUSD", "GBPUSD"]);

/** Live quotes (Kraken, every 60 s) + daily closes (marked with their date). */
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
          const weekend = closed && q.live && FOLLOWS_SPOT.has(q.symbol);
          return (
            <span
              key={q.symbol}
              className={`tick${q.live ? "" : " is-daily"}`}
              title={!q.live ? `${q.source}, denní závěr k ${shortDate(q.as_of)}` : weekend ? `${q.source} — spotový trh je zavřený` : `${q.source}, živě`}
            >
              <span className="tick-name">{q.label}</span>
              <span key={q.price} className="tick-price flash">{price(q.price, q.digits)}</span>
              {ch !== null && !weekend && <span className={`tick-ch ${ch > 0 ? "pos" : ch < 0 ? "neg" : ""}`}>{pct(ch)}</span>}
              {weekend && <span className="tick-d">víkend</span>}
              {!q.live && <span className="tick-d">denní</span>}
            </span>
          );
        })}
      </div>
    </div>
  );
}
