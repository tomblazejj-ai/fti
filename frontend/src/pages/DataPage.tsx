import { useState, type CSSProperties } from "react";
import { MarketChip, QualityBadge } from "../components/Bits";
import { Icon } from "../components/Icon";
import { Card, Empty, ErrorState, Skeleton } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { STATIC, api } from "../lib/api";
import { formatDateTime, shortDate } from "../lib/format";
import type { AiTestResult, AuditRow, MarketStateInfo, ProbeRow, SourcesResponse } from "../lib/types";

const SRC_STATUS: Record<string, string> = {
  ok: "v pořádku",
  delayed: "data se zpožděním",
  stale: "zastaralá data",
  outage: "výpadek (poslední pokus selhal)",
  unavailable: "nedostupný",
  unknown: "zatím nezkoušeno",
};

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
      {!STATIC && <AiCard />}
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
              <th>Výpadky a poznámky</th>
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
                <td>
                  {r.outage_count} {r.outage_count === 1 ? "výpadek" : "výpadků"}
                  {r.counting_since && <small>od {formatDateTime(r.counting_since)}</small>}
                  {r.last_error && r.last_error_at && <small>poslední výpadek {formatDateTime(r.last_error_at)}: {r.last_error}</small>}
                  {r.rejected_count > 0 && <small>odmítnutá data (kontrola kvality): {r.rejected_count}{r.last_rejected ? ` — ${r.last_rejected}` : ""}</small>}
                  {r.unsupported_tfs.length > 0 && <small>rámce, které zdroj nenabízí (není chyba): {r.unsupported_tfs.join(", ")}</small>}
                  {r.error_count > r.outage_count && <small>dříve zapsáno celkem {r.error_count} (včetně nepodporovaných rámců)</small>}
                </td>
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
        Bez připojeného brokera je cena XAUUSD nedostupná a CFD také — PAXG ani referenční řada NBP se za zlato nikdy nedosazují.
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
          <li key={k.name}><span>{k.label}: <strong>{k.set ? `nastaven${k.hint ? ` (${k.hint})` : ""}` : "nenastaven"}</strong></span></li>
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

/** AI on Groq's FREE plan: the key (stored only on this PC), on/off, the connection test, today's
 * usage against FTI's own caps, the limits Groq reports, and which AI tasks have their inputs. */
function AiCard() {
  const st = useAsync(() => api.aiStatus(), []);
  const [key, setKey] = useState("");
  const [gkey, setGkey] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [test, setTest] = useState<AiTestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try {
      await fn();
      setMsg({ ok: true, text: ok });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
      st.reload();
    }
  };
  const g = st.data?.groq;
  const on = g?.provider === "groq" || g?.provider === "gemini";
  return (
    <Card title="AI — Gemini Free, záloha Groq Free (zdarma)" icon={<Icon name="spark" size={16} />} i={1} id="ai">
      <p className="hint" style={{ marginTop: 0 } as CSSProperties}>
        FTI používá jen bezplatné tarify: Google Gemini (Flash, bez zapnutého billingu) jako hlavní a Groq Free jako zálohu.
        Platební kartu ani jinou platební metodu nikde nezadávej a v Google AI Studio nezapínej billing. Když se bezplatné limity
        vyčerpají (HTTP 429), výsledek je NO TRADE „AI nedostupná“ — FTI nikdy nepřepne na placeného poskytovatele.
        AI jen vykládá výpočty FTI — ceny, skóre ani BIAS nepočítá.
      </p>
      {st.error && !st.data ? <ErrorState message={st.error.message} onRetry={st.reload} /> : !g ? <Skeleton rows={3} /> : (
        <>
          <p>
            <span className={`src-dot src-${g.state === "ready" ? "ok" : g.state === "off" ? "unknown" : "down"}`} />
            <strong>{g.text}</strong>{g.until ? ` Znovu ${formatDateTime(g.until)}.` : ""}
          </p>
          {g.limits_changed && (
            <p className="msg-err">
              Groq změnil limity ({g.limits_changed.model}: {g.limits_changed.old} → {g.limits_changed.new}). Zkontroluj v konzoli Groq, že máš pořád tarif Free bez platební metody.
            </p>
          )}

          {g.calls_cap !== undefined && (
            <p className="ai-counter">
              Volání AI dnes: <strong>{g.calls_today} / {g.calls_cap}</strong>
              <small> (Gemini i Groq dohromady, denní strop FTI; nový den od 1:00 SEČ)</small>
            </p>
          )}
          <h3 className="sub">Klíč GEMINI_API_KEY — hlavní (uloží se jen na tomto PC)</h3>
          <p className="muted">
            {g.keys?.gemini ? "Klíč Gemini je uložený." : "Klíč zatím není uložený — FTI zatím používá Groq."} Klíč získáš zdarma na
            aistudio.google.com → Get API key (projekt bez billingu).
          </p>
          <div className="form-row">
            <input type="password" autoComplete="off" placeholder="vlož klíč z aistudio.google.com (začíná AIza)" value={gkey}
                   onChange={(e) => setGkey(e.target.value)} aria-label="Klíč Gemini" />
            <button type="button" className="btn-primary" disabled={busy || !gkey.trim()}
                    onClick={() => act(async () => { await api.setKey("GEMINI_API_KEY", gkey); setGkey(""); }, "Klíč Gemini uložen.")}>
              Uložit klíč
            </button>
            {g.keys?.gemini && (
              <>
                <button type="button" className="btn" disabled={busy}
                        onClick={() => act(async () => setTest(await api.aiTestGemini()), "Test Gemini proběhl.")}>
                  Otestovat Gemini
                </button>
                <button type="button" className="btn" disabled={busy} onClick={() => act(() => api.setKey("GEMINI_API_KEY", ""), "Klíč Gemini smazán.")}>
                  Smazat klíč
                </button>
              </>
            )}
          </div>

          <h3 className="sub">Klíč GROQ_API_KEY — záloha (uloží se jen na tomto PC)</h3>
          <p className="muted">{g.key_set ? "Klíč je uložený. Z bezpečnostních důvodů se nikde nezobrazuje." : "Klíč zatím není uložený."}</p>
          <div className="form-row">
            <input type="password" autoComplete="off" placeholder="vlož klíč z console.groq.com (začíná gsk_)" value={key}
                   onChange={(e) => setKey(e.target.value)} aria-label="Klíč Groq" />
            <button type="button" className="btn-primary" disabled={busy || !key.trim()}
                    onClick={() => act(async () => { await api.setKey("GROQ_API_KEY", key); setKey(""); }, "Klíč uložen.")}>
              Uložit klíč
            </button>
            {g.key_set && (
              <button type="button" className="btn" disabled={busy} onClick={() => act(() => api.setKey("GROQ_API_KEY", ""), "Klíč smazán.")}>
                Smazat klíč
              </button>
            )}
          </div>

          <div className="form-row">
            <button type="button" className="btn" disabled={busy || !g.keys?.groq}
                    onClick={() => act(async () => setTest(await api.aiTest()), "Test proběhl.")}>
              Otestovat Groq
            </button>
            <button type="button" className={on ? "btn" : "btn-primary"} disabled={busy || (!on && !g.key_set)}
                    onClick={() => act(() => api.updateSettings({ ai: { provider: on ? "none" : "gemini" } }), on ? "AI vypnuta." : "AI zapnuta (Gemini, záloha Groq).")}>
              {on ? "Vypnout AI" : "Zapnout AI"}
            </button>
            {on && (
              <button type="button" className="btn" disabled={busy}
                      onClick={() => act(() => api.updateSettings({ ai: { auto_analyses: !g.auto_analyses } }),
                                         g.auto_analyses ? "Automatické analýzy vypnuty." : "Automatické analýzy zapnuty.")}>
                Automatické analýzy při významné změně: {g.auto_analyses ? "zapnuto" : "vypnuto"}
              </button>
            )}
            {(g.state === "paused" || g.state === "billing") && (
              <button type="button" className="btn" disabled={busy} onClick={() => act(() => api.aiResume(), "AI znovu povolena.")}>
                Znovu povolit AI
              </button>
            )}
          </div>
          {msg && <p className={msg.ok ? "msg-ok" : "msg-err"}>{msg.text}</p>}
          {test && (
            <p className={test.ok ? "msg-ok" : "msg-err"}>
              {test.text}
              {test.seconds !== undefined && ` Odpověď za ${test.seconds} s.`}
              {test.models && ` Dostupné bezplatné modely: ${test.models.join(", ") || "žádný"}.`}
              {test.limits?.requests_per_day !== undefined &&
                ` Groq hlásí pro tento účet ${test.limits.requests_per_day} dotazů denně a ${test.limits.tokens_per_minute ?? "?"} tokenů za minutu.`}
            </p>
          )}

          <h3 className="sub">Dnešní spotřeba (vlastní limity FTI)</h3>
          <ul className="news">
            <li><span>Dotazy: <strong>{g.usage.requests} z {g.usage.cap}</strong> (od {g.usage.reserve_from} jen důležité události), neúspěšné {g.usage.failed}</span></li>
            <li><span>Tokeny: <strong>{g.usage.tokens.toLocaleString("cs-CZ")} z {g.usage.token_cap.toLocaleString("cs-CZ")}</strong></span></li>
            <li><span>Nejvýš {g.usage.per_minute_cap} dotazů za minutu a nejvýš 90 % minutového limitu tokenů Groq</span></li>
          </ul>

          <h3 className="sub">Limity, které Groq hlásí pro tento účet</h3>
          <div className="twrap">
            <table className="dtable">
              <thead><tr><th>Model</th><th>Dotazů denně</th><th>Tokenů za minutu</th><th>Stav</th></tr></thead>
              <tbody>
                {Object.entries(g.models).map(([m, s]) => (
                  <tr key={m}>
                    <td>{m}</td>
                    <td>{s.limits?.requests_per_day ?? "—"}{s.limits?.requests_left_today !== undefined && <small>zbývá {s.limits.requests_left_today}</small>}</td>
                    <td>{s.limits?.tokens_per_minute ?? "—"}</td>
                    <td>{s.paused_until && new Date(s.paused_until) > new Date() ? `pauza do ${formatDateTime(s.paused_until)} (${s.reason})` : "k dispozici"}
                      {s.limits?.seen_at && <small>zjištěno {formatDateTime(String(s.limits.seen_at))}</small>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="note">„—“ = Groq je zatím nenahlásil (zjistí se při prvním dotazu nebo testu).</p>

          <h3 className="sub">Co AI umí</h3>
          <ul className="news">
            {(st.data?.tasks ?? []).map((t) => (
              <li key={t.id}><span>{t.ready ? "✓" : "○"} <strong>{t.name}</strong>{t.ready ? (t.cooldown_min ? ` — nejvýš jednou za ${t.cooldown_min} min` : "") : ` — nepřipraveno: ${t.why_not}`}</span></li>
            ))}
          </ul>
          <p className="note">Podmínky Groq Free ověřeny {shortDate(g.terms_checked)}. Cena: {g.cost}.</p>
        </>
      )}
    </Card>
  );
}
