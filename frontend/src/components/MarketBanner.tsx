import { useTickers } from "../hooks/useTickers";
import { signed, usd } from "../lib/format";

function when(iso: string): string {
  return new Date(iso).toLocaleString("cs-CZ", { weekday: "long", hour: "2-digit", minute: "2-digit" });
}

/** Is spot gold trading now? If not: since when, until when, and what PAXG did meanwhile. */
export function MarketBanner() {
  const t = useTickers();
  const m = t?.market;
  if (!m) return null;
  if (m.open) {
    return (
      <div className="mkt mkt-open" role="status">
        <span className="live-dot" aria-hidden="true" />
        <strong>Trh je otevřený</strong>
        <span className="muted">
          · ceny živě, technika se přepočítává každých 5 minut
          {m.closes_at && ` · ${m.weekly_close ? "týdenní uzavření" : "denní pauza"} ${when(m.closes_at)}`}
        </span>
      </div>
    );
  }
  const w = t?.weekend;
  return (
    <div className="mkt mkt-closed" role="status">
      <span className="live-dot is-off" aria-hidden="true" />
      <div>
        <strong>Spotový trh se zlatem je zavřený ({m.reason})</strong>
        {m.next_open && <span> — otevře se {when(m.next_open)} (obvykle, bez svátků).</span>}
        <p className="muted small">
          Graf, technika i trendy ukazují stav při uzavření trhu{w ? ` (${when(w.spot_close_time)}, ${usd(w.spot_close)})` : ""} — to je
          správně, nové svíčky přibudou po otevření.
          {w && (
            <>
              {" "}
              Token PAXG se obchoduje i teď: <strong>{usd(w.paxg_now)}</strong> (
              <span className={w.change_pct > 0 ? "tone-bullish" : w.change_pct < 0 ? "tone-bearish" : ""}>{signed(w.change_pct, 2)} %</span>{" "}
              od uzavření) — naznačuje, kudy může trh otevřít, ale víkendový obchod je slabý.
            </>
          )}
        </p>
      </div>
    </div>
  );
}
