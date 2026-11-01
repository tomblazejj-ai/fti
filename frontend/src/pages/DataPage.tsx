import { useState, type CSSProperties } from "react";
import { MarketChip, QualityBadge } from "../components/Bits";
import { Icon } from "../components/Icon";
import { Card, Empty, ErrorState, Skeleton } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { STATIC, api } from "../lib/api";
import { formatDateTime } from "../lib/format";
import type { AuditRow, MarketStateInfo, ProbeRow, SourcesResponse } from "../lib/types";

const SRC_STATUS: Record<string, string> = { ok: "funguje", degraded: "poslední pokus selhal", down: "nefunguje", unknown: "zatím nezkoušeno" };

/** What data FTI really uses for every instrument, the health of every source, and the
 * connection of real broker quotes (MT5 / OANDA) — everything free. */
export function DataPage() {
  const audit = useAsync(() => api.audit(), []);
  const src = useAsync(() => api.sources(), []);
  return (
    <main className="page">
      <header className="page-head rise">
        <h1>Data a zdroje</h1>
        <p>Co FTI u každého instrumentu skutečně používá, odkud to je a jak je to čerstvé. Náhrady (proxy) jsou vždy označené.</p>
      </header>
      {!STATIC && src.data && <Connect s={src.data} onChange={() => { src.reload(); audit.reload(); }} />}
      <Card title="Audit instrumentů" icon={<Icon name="layers" size={16} />} i={2} id="audit"
            extra={audit.data && <span className="card-note">zjištěno {formatDateTime(audit.data.computed_at)}</span>}>
        {audit.error && !audit.data ? <ErrorState message={audit.error.message} onRetry={audit.reload} /> :
          !audit.data ? <Skeleton rows={6} /> : <AuditTable rows={audit.data.rows} />}
      </Card>
      {!STATIC && <SourceTest />}
      <Card title="Stav zdrojů" icon={<Icon name="clock" size={16} />} i={3} id="zdroje">
        {src.error && !src.data ? <ErrorState message={src.error.message} onRetry={src.reload} /> :
          !src.data ? <Skeleton rows={4} /> : <Sources s={src.data} />}
      </Card>
    </main>
  );
}

/** One real request per source: content and freshness checked, not just "HTTP 200". */
function SourceTest() {
  const [rows, setRows] = useState<ProbeRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [at, setAt] = useState<string | null>(null);
  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.dataTest();
      setRows(r.rows);
      setAt(r.tested_at);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Test dostupnosti zdrojů" icon={<Icon name="bolt" size={16} />} i={2} id="test"
          extra={<button type="button" className="btn-primary" onClick={run} disabled={busy}>{busy ? "Testuji…" : "Otestovat všechny zdroje"}</button>}>
      <p className="hint" style={{ marginTop: 0 } as CSSProperties}>
        Každý zdroj dostane jeden skutečný dotaz. Kontroluje se obsah a stáří nejnovějšího údaje vůči obvyklému rytmu zdroje — ne jen to, že server odpověděl.
      </p>
      {err && <p className="msg-err">{err}</p>}
      {rows && (
        <div className="twrap">
          <table className="dtable">
            <thead>
              <tr><th>Zdroj</th><th>Výsledek</th><th>Nejnovější údaj</th><th>Záznamů</th><th>Odezva</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}>
                  <td>{r.name}</td>
                  <td><span className={`src-dot src-${r.ok ? "ok" : "down"}`} />{r.ok ? "funguje" : "problém"}{r.error && <small>{r.error}</small>}</td>
                  <td><QualityBadge q={r.quality} /> {r.latest ? formatDateTime(r.latest) : "—"}</td>
                  <td>{r.records}</td>
                  <td>{r.ms} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {at && <p className="note">Otestováno {formatDateTime(at)}.</p>}
    </Card>
  );
}

function AuditTable({ rows }: { rows: AuditRow[] }) {
  return (
    <div className="twrap">
      <table className="dtable">
        <thead>
          <tr>
            <th>Instrument</th>
            <th>Co FTI skutečně dostává</th>
            <th>Odkud</th>
            <th>Odpovídá?</th>
            <th>Omezení</th>
            <th>Doporučení</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.code}>
              <td>
                <strong>{r.symbol}</strong>
                <small>{r.name} · {r.itype_cs}</small>
              </td>
              <td>
                <QualityBadge q={{ status: r.status, label: r.status, as_of: null, age_hours: null, text: r.verdict }} /> {r.gets}
                {r.market && "state" in r.market && <small><MarketChip m={r.market as MarketStateInfo} /> {(r.market as MarketStateInfo).reason}</small>}
                {r.last_quote && "time_cs" in r.last_quote && (
                  <small>poslední hodnota {r.last_quote.time_cs}{r.last_quote.tradable_now ? " · živá kotace" : " · není aktuální obchodovatelná kotace"}</small>
                )}
              </td>
              <td>{r.source}</td>
              <td>{r.verdict}</td>
              <td><small>{r.limits}</small></td>
              <td><small>{r.recommendation}</small></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Sources({ s }: { s: SourcesResponse }) {
  if (!s.sources.length) return <Empty>Zdroje se ještě nezkoušely — počkej na první aktualizaci dat.</Empty>;
  return (
    <>
      {s.stale_inputs.length > 0 && (
        <div className="hint">
          <strong>Zobrazují se poslední uložená data, protože zdroj teď neodpovídá:</strong>
          <ul>
            {s.stale_inputs.map((x) => (
              <li key={x.label}>{x.label} — data stažená {formatDateTime(x.fetched_at)}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="twrap">
        <table className="dtable">
          <thead>
            <tr>
              <th>Zdroj</th>
              <th>Stav</th>
              <th>Poslední úspěch</th>
              <th>Odezva</th>
              <th>Záznamů</th>
              <th>Chyby</th>
            </tr>
          </thead>
          <tbody>
            {s.sources.map((r) => (
              <tr key={r.key}>
                <td>{r.name}</td>
                <td><span className={`src-dot src-${r.status}`} />{SRC_STATUS[r.status]}</td>
                <td>{formatDateTime(r.last_ok)}{r.data_as_of && <small>data k {formatDateTime(r.data_as_of)}</small>}</td>
                <td>{r.last_ms !== null ? `${Math.round(r.last_ms)} ms` : "—"}</td>
                <td>{r.last_records ?? "—"}</td>
                <td>{r.error_count}{r.last_error && <small>{r.last_error}</small>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** Real broker quotes for XAUUSD, CFDs and FX: the user's own MT5 terminal or an OANDA demo token. */
function Connect({ s, onChange }: { s: SourcesResponse; onChange: () => void }) {
  const [path, setPath] = useState(s.mt5.settings.terminal_path || s.mt5.terminals[0]?.path || "");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [key, setKey] = useState({ name: "FRED_API_KEY", value: "" });
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      setMsg({ ok: true, text: ok });
      onChange();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    }
  };
  return (
    <Card title="Skutečné kotace (XAUUSD, CFD, forex)" icon={<Icon name="bolt" size={16} />} i={1} id="pripojeni">
      <p className="hint" style={{ marginTop: 0 } as CSSProperties}>
        Bez připojeného brokera má XAUUSD jen denní referenční cenu (NBP) a CFD jsou nedostupné — PAXG se za zlato nikdy nedosazuje.
        Obě možnosti jsou zdarma. FTI z nich jen čte ceny, nikdy nezadává obchody.
      </p>
      <h3 className="sub">MetaTrader 5 na tomto PC</h3>
      {!s.mt5.package && <p className="msg-err">Knihovna MetaTrader5 zatím není nainstalovaná — bez ní MT5 nejde připojit.</p>}
      {s.mt5.terminals.length === 0 ? (
        <Empty>Na tomto PC nebyl nalezen žádný terminál MT5.</Empty>
      ) : (
        <div className="form-row">
          <select value={path} onChange={(e) => setPath(e.target.value)} aria-label="Terminál MT5">
            {s.mt5.terminals.map((t) => (
              <option key={t.path} value={t.path}>{t.name}{t.servers.length ? ` (${t.servers.join(", ")})` : ""}</option>
            ))}
          </select>
          {s.mt5.settings.enabled ? (
            <>
              <button type="button" className="btn" onClick={() => run(() => api.mt5Test(), "Terminál odpověděl, data se načítají.")}>Vyzkoušet</button>
              <button type="button" className="btn" onClick={() => run(() => api.updateSettings({ mt5: { enabled: false } }), "MT5 vypnut.")}>Vypnout</button>
            </>
          ) : (
            <button type="button" className="btn-primary" disabled={!s.mt5.package}
                    onClick={() => run(() => api.updateSettings({ mt5: { enabled: true, terminal_path: path } }), "MT5 zapnut. Terminál musí být přihlášený.")}>
              Připojit
            </button>
          )}
        </div>
      )}
      <h3 className="sub">Klíče (ukládají se jen na tomto PC)</h3>
      <ul className="news">
        {s.keys.map((k) => (
          <li key={k.name}><span>{k.label}: <strong>{k.set ? `nastaven (${k.hint})` : "nenastaven"}</strong></span></li>
        ))}
      </ul>
      <div className="form-row">
        <select value={key.name} onChange={(e) => setKey({ ...key, name: e.target.value })} aria-label="Který klíč">
          {s.keys.map((k) => <option key={k.name} value={k.name}>{k.name}</option>)}
        </select>
        <input type="password" autoComplete="off" placeholder="vlož klíč (prázdné = smazat)" value={key.value}
               onChange={(e) => setKey({ ...key, value: e.target.value })} aria-label="Hodnota klíče" />
        <button type="button" className="btn-primary" onClick={() => run(async () => { await api.setKey(key.name, key.value); setKey({ ...key, value: "" }); }, "Uloženo.")}>
          Uložit
        </button>
      </div>
      {msg && <p className={msg.ok ? "msg-ok" : "msg-err"}>{msg.text}</p>}
    </Card>
  );
}
