import { Icon } from "../components/Icon";
import { Panel } from "../components/Panel";
import { ErrorState, Loading } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { STATIC, api } from "../lib/api";
import { formatDateTime } from "../lib/format";
import type { MetodikaFile } from "../lib/types";

const STATUS_CLASS = { done: "is-done", changed: "is-changed", new: "is-new" } as const;

/** Funded Mind materials from the trader's folder and where each one shows up in the app. */
export function Metodika() {
  const m = useAsync(() => api.metodika(), []);
  if (m.error && !m.data) return <main className="page"><ErrorState message={m.error.message} onRetry={m.reload} /></main>;
  if (!m.data) return <main className="page"><Loading label="Kontroluji složku s materiály…" /></main>;
  const d = m.data;
  const waiting = d.counts.new + d.counts.changed;
  return (
    <main className="page">
      <div className="ov">
        <section className="panel meto-hero">
          <div>
            <span className="muted small">Metodika · {d.course}</span>
            <h1 className="meto-title">Podle čeho aplikace hodnotí trh</h1>
            <p className="small">
              Materiály ze složky <strong>{d.folder}</strong>. Co je zapracované, je vidět přímo v přehledu zlata a DXY. {d.how_to}
            </p>
          </div>
          {!STATIC && <div className="meto-counts">
            <span className="meto-count is-done"><strong>{d.counts.done}</strong> zapracováno</span>
            <span className={`meto-count ${waiting ? "is-new" : "is-zero"}`}><strong>{waiting}</strong> čeká na zapracování</span>
            <button type="button" className="link-more" onClick={m.reload}>
              <Icon name="refresh" size={14} /> Zkontrolovat složku znovu
            </button>
            <span className="muted small">zkontrolováno {formatDateTime(d.checked_at)}</span>
          </div>}
        </section>

        {!d.folder_exists && !STATIC && (
          <p className="state state-unavailable">
            Složka „Fundament Funded mind“ teď na ploše není. Aplikace dál počítá podle už zapracovaných materiálů.
          </p>
        )}

        <Panel title="Hlavní pravidla" tag="shrnutí kurzu" icon="sparkle">
          <ol className="meto-rules">
            {d.principles.map((p) => <li key={p}>{p}</li>)}
          </ol>
        </Panel>

        {(d.extras ?? []).length > 0 && (
          <Panel title="Videa a poznámky" tag="vložené mimo složku" icon="sparkle">
            <ul className="meto-files">
              {(d.extras ?? []).map((x) => (
                <li key={x.title} className="meto-file is-done">
                  <div className="meto-file-head">
                    <span className="meto-badge">zapracováno</span>
                    <strong>{x.title}</strong>
                    <span className="muted small">{x.source}</span>
                  </div>
                  <p className="small muted">{x.author}</p>
                  <p className="small">{x.summary}</p>
                  <p className="meto-used small">
                    {x.used_in.map((u) => <span key={u} className="meto-chip">{u}</span>)}
                  </p>
                </li>
              ))}
            </ul>
          </Panel>
        )}

        {!STATIC && <Panel title="Materiály" tag={`${d.files.length} souborů`} icon="layers">
          <ul className="meto-files">
            {d.files.map((f) => <FileRow key={f.file} f={f} />)}
          </ul>
          {d.missing.length > 0 && (
            <p className="muted small">Ve složce už nejsou (zapracované dřív): {d.missing.join(", ")}.</p>
          )}
        </Panel>}
      </div>
    </main>
  );
}

function FileRow({ f }: { f: MetodikaFile }) {
  return (
    <li className={`meto-file ${STATUS_CLASS[f.status]}`}>
      <div className="meto-file-head">
        <span className="meto-badge">{f.status_text}</span>
        <strong>{f.title ?? f.file}</strong>
        <span className="muted small">{f.file} · {f.size_kb.toLocaleString("cs-CZ")} kB</span>
      </div>
      {f.author && <p className="small muted">{f.author}</p>}
      {f.summary && <p className="small">{f.summary}</p>}
      {f.used_in.length > 0 && (
        <p className="meto-used small">
          {f.used_in.map((u) => <span key={u} className="meto-chip">{u}</span>)}
        </p>
      )}
      {f.preview && <pre className="meto-preview small">{f.preview}</pre>}
    </li>
  );
}
