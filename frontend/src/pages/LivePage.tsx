import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { Card, Empty, Pills } from "../components/ui";
import { STATIC, apiBase } from "../lib/api";
import type { LiveCandles, LiveQuote, LiveSnapshot } from "../lib/types";

const TFS = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"] as const;
type Tf = (typeof TFS)[number];

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

/** The live stream (Server-Sent Events): a new snapshot whenever a price changes; reconnects by itself. */
function useLiveStream(): { snap: LiveSnapshot | null; error: string | null; connected: boolean } {
  const [snap, setSnap] = useState<LiveSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (STATIC) {
      setError("Živý terminál zatím běží jen v aplikaci na PC.");
      return;
    }
    let es: EventSource | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const open = () => {
      es = new EventSource(`${apiBase()}/api/live/stream`);
      es.onopen = () => {
        setConnected(true);
        setError(null);
      };
      es.onmessage = (e) => setSnap(JSON.parse(e.data) as LiveSnapshot);
      es.onerror = () => {
        setConnected(false);
        es?.close();
        fetch(`${apiBase()}/api/live/snapshot`)
          .then(async (r) => (r.ok ? null : ((await r.json()) as { detail?: string }).detail ?? `chyba ${r.status}`))
          .then((msg) => setError(msg ?? "Spojení se přerušilo — připojuji znovu…"))
          .catch(() => setError("FTI neodpovídá — připojuji znovu…"));
        if (!closed) retry = setTimeout(open, 5000);
      };
    };
    open();
    return () => {
      closed = true;
      clearTimeout(retry);
      es?.close();
    };
  }, []);
  return { snap, error, connected };
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

const W = 960;
const H = 340;
const PAD = { top: 12, right: 78, bottom: 24, left: 8 };

function LiveChart({ code, digits, version }: { code: string; digits: number; version: number }) {
  const [tf, setTf] = useState<Tf>("M1");
  const [data, setData] = useState<LiveCandles | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const last = useRef(0);
  useEffect(() => {
    setData(null);
    last.current = 0;
  }, [code, tf]);
  useEffect(() => {
    const now = Date.now();
    if (now - last.current < 2000 && data) return; // at most every 2 s, the stream says when something changed
    last.current = now;
    fetch(`${apiBase()}/api/live/candles?code=${encodeURIComponent(code)}&tf=${tf}&limit=120`)
      .then(async (r) => {
        if (!r.ok) throw new Error(((await r.json()) as { detail?: string }).detail ?? `chyba ${r.status}`);
        return (await r.json()) as LiveCandles;
      })
      .then((d) => {
        setData(d);
        setErr(null);
      })
      .catch((e: Error) => setErr(e.message));
  }, [code, tf, version, data]);
  const rows = data?.candles ?? [];
  const scale = useMemo(() => {
    if (!rows.length) return null;
    const lo = Math.min(...rows.map((r) => r[3]));
    const hi = Math.max(...rows.map((r) => r[2]));
    const pad = (hi - lo) * 0.06 || 1;
    return { lo: lo - pad, hi: hi + pad };
  }, [rows]);
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const step = rows.length ? plotW / rows.length : 1;
  const x = (i: number) => PAD.left + step * (i + 0.5);
  const y = (v: number) => (scale ? PAD.top + (1 - (v - scale.lo) / (scale.hi - scale.lo)) * plotH : 0);
  const lastRow = rows[rows.length - 1];
  return (
    <div className="cchart">
      <div className="cchart-bar">
        <Pills label="Časový rámec" options={TFS.map((t) => ({ value: t, label: t }))} value={tf} onChange={setTf} />
        {data && <small className="hint">{data.product} · svíčky ze {data.price_type === "mid" ? "středu bid/ask" : data.price_type}</small>}
      </div>
      <div className="cchart-box">
        {err && !rows.length ? (
          <p className="cchart-msg">{err}</p>
        ) : !rows.length || !scale ? (
          <p className="cchart-msg">Načítám svíčky…</p>
        ) : (
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Živý graf ${code} ${tf}`}>
            {rows.map((r, i) => {
              const up = r[4] >= r[1];
              const bw = Math.max(1, step * 0.6);
              return (
                <g key={r[0]} className={up ? "cc-bull" : "cc-bear"}>
                  <line x1={x(i)} x2={x(i)} y1={y(r[2])} y2={y(r[3])} />
                  <rect x={x(i) - bw / 2} width={bw} y={y(Math.max(r[1], r[4]))} height={Math.max(1, Math.abs(y(r[1]) - y(r[4])))} rx="1" />
                </g>
              );
            })}
            {lastRow && (
              <>
                <line x1={PAD.left} x2={W - PAD.right} y1={y(lastRow[4])} y2={y(lastRow[4])} className="cc-last" />
                <text x={W - PAD.right + 6} y={y(lastRow[4]) + 4} className="cc-tick">{fmt(lastRow[4], digits)}</text>
              </>
            )}
          </svg>
        )}
      </div>
    </div>
  );
}

/** LIVE terminal (test version): XAUUSD, EURUSD, US500 and NAS100 streamed with their state, source and quote time. */
export function LivePage() {
  const { snap, error, connected } = useLiveStream();
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
              <LiveChart code={cur.code} digits={cur.digits} version={snap?.version ?? 0} />
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
