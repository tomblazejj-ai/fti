import { useTickers } from "../hooks/useTickers";
import { pct, price, shortDate } from "../lib/format";
import { MarketChip } from "./Bits";

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
          const closedNow = q.market ? q.market.state !== "OPEN" : weekend;
          return (
            <span
              key={q.symbol}
              className={`tick${q.live ? "" : " is-daily"}`}
              title={`${q.source}${q.kind_cs ? ` · ${q.kind_cs}` : ""}${q.quote_time_cs ? ` · ${q.quote_time_cs}` : q.as_of ? ` · k ${shortDate(q.as_of)}` : ""}`}
            >
              <span className="tick-name">{q.label}</span>
              <span key={q.price} className="tick-price flash">{price(q.price, q.digits)}</span>
              {ch !== null && !closedNow && <span className={`tick-ch ${ch > 0 ? "pos" : ch < 0 ? "neg" : ""}`}>{pct(ch)}</span>}
              {closedNow && <MarketChip m={q.market} />}
              {q.proxy && <span className="tick-d" title={q.kind_cs}>proxy</span>}
              {!q.live && !closedNow && <span className="tick-d">{q.quote_time_cs ?? "denní"}</span>}
            </span>
          );
        })}
        {(t?.unavailable ?? []).map((u) => (
          <span key={u.symbol} className="tick is-daily" title={u.reason}>
            <span className="tick-name">{u.label}</span>
            <span className="tick-d">bez zdroje</span>
          </span>
        ))}
      </div>
    </div>
  );
}
