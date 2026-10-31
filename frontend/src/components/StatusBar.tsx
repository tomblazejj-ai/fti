import { useState } from "react";
import { api } from "../lib/api";
import { formatDateTime, plural, relativeTime } from "../lib/format";
import type { SystemStatus } from "../lib/types";

/**
 * Data freshness + manual refresh. A refresh runs a full ingestion cycle on
 * the backend (FRED, CFTC, central-bank RSS, GDELT) — typically 20–60 s,
 * mostly spent respecting the sources' own rate limits.
 */
export function StatusBar({ status, onRefreshed }: { status: SystemStatus | undefined; onRefreshed: () => void }) {
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string>();
  const [showWarnings, setShowWarnings] = useState(false);

  const running = refreshing || status?.cycle_running;
  const warnings = status?.last_cycle_warnings ?? [];

  async function refresh() {
    setRefreshing(true);
    setRefreshError(undefined);
    try {
      await api.refresh("XAUUSD");
      onRefreshed();
    } catch (err) {
      setRefreshError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <div className="statusbar" role="region" aria-label="Stav dat">
      <div className="statusbar-info">
        <span className={`dot ${running ? "dot-running" : status?.last_cycle_error ? "dot-error" : "dot-ok"}`} aria-hidden="true" />
        {running ? (
          <span>Stahuji data z FRED, CFTC, centrálních bank a GDELT… (obvykle 20–60 s)</span>
        ) : status?.last_cycle_finished_at ? (
          <span title={formatDateTime(status.last_cycle_finished_at)}>
            Aktualizováno {relativeTime(status.last_cycle_finished_at)}
            {status.next_scheduled_run_at && <> · další automatická aktualizace {relativeTime(status.next_scheduled_run_at)}</>}
          </span>
        ) : status ? (
          <span>Od spuštění zatím neproběhlo žádné stažení dat.</span>
        ) : (
          <span>Zjišťuji stav dat…</span>
        )}
        {warnings.length > 0 && !running && (
          <button type="button" className="link-btn" onClick={() => setShowWarnings((v) => !v)} aria-expanded={showWarnings}>
            {warnings.length} {plural(warnings.length, "upozornění ke zdroji", "upozornění ke zdrojům", "upozornění ke zdrojům")}
          </button>
        )}
      </div>
      <button type="button" className="btn" onClick={refresh} disabled={Boolean(running)}>
        {running ? "Aktualizuji…" : "Obnovit data"}
      </button>
      {refreshError && <p className="statusbar-error" role="alert">Obnovení se nepovedlo: {refreshError}</p>}
      {status?.last_cycle_error && !running && (
        <p className="statusbar-error" role="alert">Poslední stažení dat selhalo: {status.last_cycle_error}</p>
      )}
      {showWarnings && (
        <ul className="statusbar-warnings">
          {warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
