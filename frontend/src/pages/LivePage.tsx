import { useEffect, useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { CandleChart } from "../components/CandleChart";
import { Card, Empty } from "../components/ui";
import { useLive } from "../hooks/useLive";
import type { LiveQuote } from "../lib/types";

function fmt(v: number | null | undefined, digits: number): string {
  if (v === null || v === undefined) return "—";
  return v.toLocaleString("cs-CZ", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function signed(v: number | null | undefined, digits: number, suffix = ""): string {
  if (v === null || v === undefined) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmt(Math.abs(v), digits)}${suffix}`;
}

function clock(iso?: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function QuoteTile({ q, selected, onSelect }: { q: LiveQuote; selected: boolean; onSelect: () => void }) {
  const prev = useRef<number | null | undefined>(q.mid);
  const [flash, setFlash] = useState<"" | "up" | "down">("");
  useEffect(() => {
    if (q.mid !== undefined && q.mid !== null && prev.current !== undefined && prev.current !== null && q.mid !== prev.current) {
      setFlash(q.mid > prev.current ? "up" : "down");
      const t = setTimeout(() => setFlash(""), 600);
      prev.current = q.mid;
      return () => clearTimeout(t);
    }
    prev.current = q.mid;
  }, [q.mid]);
  const d = q.digits;
  const tone = (q.change ?? 0) > 0 ? "pos" : (q.change ?? 0) < 0 ? "neg" : "";
  return (
    <button type="button" className={`ltile${selected ? " is-sel" : ""} st-${q.status.toLowerCase()}`} onClick={onSelect}
            aria-pressed={selected}>
      <span className="ltile-head">
        <strong>{q.label}</strong>
        <span className="ltile-badges">
          <span className={`lbadge mk-${(q.market_status ?? "").toLowerCase()}`} title="Stav trhu podle rozvrhu instrumentu">
            {q.market_status === "OPEN" ? "TRH OTEVŘEN" : q.market_status_cs ?? "trh ?"}
          </span>
          <span className={`lbadge st-${q.status.toLowerCase()}`} title={q.notes.join(" ")}>{q.status}</span>
        </span>
      </span>
      {q.banner && <span className="ltile-banner">{q.banner}</span>}
      <span className={`ltile-price flash-${flash}`}>{fmt(q.mid, d)}</span>
      <span className={`ltile-chg t-${tone}`}>
        {signed(q.change, d)} ({signed(q.change_pct, 2, " %")})
        <small>{q.prev_close_day ? ` proti závěru ${q.prev_close_day}` : " bez předchozího závěru"}</small>
      </span>
      <span className="ltile-ba">
        <span>Bid <b>{fmt(q.bid, d)}</b></span>
        <span>Ask <b>{fmt(q.ask, d)}</b></span>
        <span>Spread <b>{fmt(q.spread, d)}</b></span>
      </span>
      <span className="ltile-meta">
        {clock(q.quote_time)} · stáří {q.age_s !== undefined && q.age_s !== null ? `${fmt(q.age_s, 1)} s` : "—"}
        {q.time_basis === "receive" ? " (čas příjmu, zdroj čas neuvádí)" : ""}
      </span>
      <span className="ltile-src">{q.product ?? "bez zdroje"}{q.failover ? " · ZÁLOHA" : ""}</span>
      {q.notes.length > 0 && <span className="ltile-note">{q.notes[0]}</span>}
    </button>
  );
}

/** LIVE terminal (test version): XAUUSD, EURUSD, US500 and NAS100 streamed with their state, source and quote time. */
export function LivePage() {
  const { snap, error, connected } = useLive();
  const [sel, setSel] = useState("XAUUSD");
  const quotes = snap?.instruments ?? [];
  const cur = quotes.find((q) => q.code === sel) ?? quotes[0];
  return (
    <main className="page live-page">
      <header className="page-head rise">
        <h1>Živě <span className={`lconn${connected ? " is-on" : ""}`}>{connected ? "stream připojen" : "stream nepřipojen"}</span></h1>
        <p>XAUUSD, EURUSD, US500 a NAS100 · ceny přicházejí samy, bez obnovení stránky · u každé ceny zdroj, čas kotace a stav</p>
      </header>
      {error && !quotes.length ? (
        <Card><Empty>{error}</Empty></Card>
      ) : !quotes.length ? (
        <Card><Empty>Připojuji živý stream…</Empty></Card>
      ) : (
        <>
          {quotes.some((q) => q.banner) && (
            <p className="lbanner" role="alert">
              {quotes.filter((q) => q.banner).map((q) => q.label).join(", ")}: TRH OTEVŘEN – DATA NEAKTUÁLNÍ — tyto ceny
              nejsou živé a FTI z nich nevydá obchodní signál.
            </p>
          )}
          <div className="lgrid">
            {quotes.map((q) => <QuoteTile key={q.code} q={q} selected={q.code === cur?.code} onSelect={() => setSel(q.code)} />)}
          </div>
          {cur && (
            <Card title={`${cur.label} — živý graf`} icon={<Icon name="line" size={16} />} i={1} id="live-graf">
              <CandleChart key={cur.code} code={cur.code} digits={cur.digits} initialTf="M1" fixedFeed="live" />
            </Card>
          )}
          {cur && (
            <Card title="Zdroje a jejich stav" icon={<Icon name="layers" size={16} />} i={2} id="live-zdroje">
              <div className="twrap">
                <table className="dtable">
                  <thead>
                    <tr><th>Zdroj</th><th>Role</th><th>Stáří kotace</th><th>V seanci</th><th>Shoda s hlavním zdrojem</th></tr>
                  </thead>
                  <tbody>
                    {cur.providers.map((p) => (
                      <tr key={p.provider}>
                        <td>{p.provider}<small>{p.product}</small></td>
                        <td>{p.role === "primary" ? "hlavní" : p.role === "backup" ? "záloha" : "kontrola"}</td>
                        <td>{p.age_s !== null ? `${fmt(p.age_s, 1)} s` : "—"}{p.fresh ? " · živě" : ""}</td>
                        <td>{p.in_session ? "ano" : "ne"}</td>
                        <td>{p.compat ? p.compat.text : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="note">
                Stav trhu se řídí rozvrhem instrumentu, stav dat kotacemi: LIVE = kotace nejvýš 15 s stará; DELAYED = spojení
                je, ale zdroj teď nedodává; UNAVAILABLE = spojení se zdrojem není; HISTORICAL = jen poslední uložená cena.
                Svíčky jsou z ceny bid jako u brokera. US500 a NAS100 jsou CFD kotace
                (ne samotné indexy). Záloha převezme cenu jen po ověřené shodě s hlavním zdrojem. FTI neobchoduje; bez živé ceny
                nevydává obchodní signál.
              </p>
            </Card>
          )}
        </>
      )}
    </main>
  );
}
