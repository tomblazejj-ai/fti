import { useCallback, useEffect, useRef, useState } from "react";
import { GoldMark } from "../components/Icon";
import { MarketBanner } from "../components/MarketBanner";
import { useTickers } from "../hooks/useTickers";
import { Pills } from "../components/Panel";
import { StatusBar } from "../components/StatusBar";
import { ErrorState, Loading, StaleNotice, Unavailable } from "../components/ui";
import { useAsync, useInterval } from "../hooks/useAsync";
import { ApiError, api } from "../lib/api";
import { PRIMARY_HORIZON, isStale, signed, usd } from "../lib/format";
import type { Analysis, DashboardInstrument, Horizon, SystemStatus } from "../lib/types";
import { CalendarTable } from "./detail/CalendarTable";
import { CotTab } from "./detail/CotTab";
import { FundTab } from "./detail/FundTab";
import { KeyNews } from "./detail/KeyNews";
import { NewsTab } from "./detail/NewsTab";
import { Overview } from "./detail/Overview";
import { SeasonalityTab } from "./detail/SeasonalityTab";
import { SourcesTab, sourceProblems } from "./detail/SourcesTab";
import { TechTab } from "./detail/TechTab";
import { Panel } from "../components/Panel";

export type Tab = "overview" | "tech" | "cot" | "season" | "calendar" | "news" | "fund" | "sources";
export const TABS: { key: Tab; label: string }[] = [
  { key: "overview", label: "Přehled" },
  { key: "tech", label: "Technika" },
  { key: "cot", label: "COT" },
  { key: "season", label: "Sezónnost" },
  { key: "calendar", label: "Kalendář" },
  { key: "news", label: "Zprávy" },
  { key: "fund", label: "Fundament" },
  { key: "sources", label: "Zdroje" },
];

export function InstrumentDetail({ code, tab }: { code: string; tab: Tab }) {
  const dash = useAsync(() => api.dashboard(), []);
  const info = dash.data?.instruments.find((i) => i.code === code);
  const running = dash.data?.status.cycle_running ?? false;
  const summary = info?.summary;
  const notFresh = Boolean(summary && (!summary.computed || isStale(summary.computed_at, dash.data?.status.refresh_interval_minutes)));
  const poll = useCallback(() => dash.reload(), [dash.reload]);
  useInterval(poll, running || notFresh ? 5000 : 120000);

  if (dash.error && !dash.data) return <main className="page"><ErrorState message={dash.error.message} onRetry={dash.reload} /></main>;
  if (!dash.data) return <main className="page"><Loading /></main>;
  if (!info) {
    return (
      <main className="page">
        <p className="state state-unavailable">Neznámý instrument „{code}“.</p>
      </main>
    );
  }
  if (info.status !== "live") return <ComingSoon info={info} />;
  return <LiveDetail info={info} status={dash.data.status} onStatusReload={dash.reload} tab={tab} />;
}

function LiveDetail({ info, status, onStatusReload, tab }: { info: DashboardInstrument; status: SystemStatus; onStatusReload: () => void; tab: Tab }) {
  const [refreshKey, setRefreshKey] = useState(0);
  const [horizon, setHorizon] = useState<Horizon>(PRIMARY_HORIZON);
  const scores = useAsync(() => api.scores(info.code), [info.code, refreshKey]);
  const analysis = useAsync(() => api.analysis(info.code), [info.code, refreshKey]);

  // Whenever a background cycle finishes, pull the fresh data.
  const lastFinished = useRef(status.last_cycle_finished_at);
  useEffect(() => {
    if (status.last_cycle_finished_at !== lastFinished.current) setRefreshKey((k) => k + 1);
    lastFinished.current = status.last_cycle_finished_at;
  }, [status.last_cycle_finished_at]);
  const stale = analysis.data ? isStale(analysis.data.computed_at, status.refresh_interval_minutes) : false;
  const analysisMissing = analysis.error instanceof ApiError && analysis.error.status === 404;
  const go = (t: string) => {
    window.location.hash = `#/instrument/${info.code}/${t}`;
  };

  return (
    <main className="page">
      <InstrumentHeader a={analysis.data} tab={tab} onTab={go} />
      <MarketBanner />
      <StatusBar status={status} onRefreshed={() => { setRefreshKey((k) => k + 1); onStatusReload(); }} />
      {analysis.data && stale && <StaleNotice computedAt={analysis.data.computed_at} running={status.cycle_running} />}

      {!analysis.data ? (
        analysis.loading ? (
          <Loading label="Načítám rozbor… (první výpočet po spuštění trvá asi minutu)" />
        ) : analysisMissing ? (
          <Unavailable>Rozbor se spočítá při první aktualizaci dat — chvíli počkej nebo klikni na „Obnovit data“.</Unavailable>
        ) : (
          <ErrorState message={analysis.error?.message ?? ""} onRetry={analysis.reload} />
        )
      ) : (
        <div className={`tab-view${stale ? " is-stale" : ""}`} role="tabpanel" aria-label={TABS.find((t) => t.key === tab)?.label} key={tab}>
          {tab === "overview" && <Overview analysis={analysis.data} onTab={go} />}
          {tab === "tech" && <TechTab analysis={analysis.data} />}
          {tab === "cot" && <CotTab cot={analysis.data.cot ?? null} cotUsd={analysis.data.cot_usd} />}
          {tab === "season" && <SeasonalityTab s={analysis.data.seasonality} long={analysis.data.seasonality_long} daily={analysis.data.season_daily} />}
          {tab === "sources" && <SourcesTab rows={analysis.data.sources_status} />}
          {tab === "calendar" && (
            <Panel title="Ekonomický kalendář" tag="XAU/USD" icon="calendar">
              <CalendarTable calendar={analysis.data.calendar} full />
            </Panel>
          )}
          {tab === "news" && (
            <div className="ov">
              <KeyNews mood={analysis.data.news} />
              <section className="panel">
                <NewsTab code={info.code} refreshKey={refreshKey} mood={analysis.data.news ?? null} />
              </section>
            </div>
          )}
          {tab === "fund" &&
            (scores.data ? (
              <section className="panel">
                <FundTab code={info.code} assetName={info.name} scores={scores.data} horizon={horizon} onHorizon={setHorizon} refreshKey={refreshKey} />
              </section>
            ) : scores.error ? (
              <ErrorState message={scores.error.message} onRetry={scores.reload} />
            ) : (
              <Loading />
            ))}
        </div>
      )}
    </main>
  );
}

function InstrumentHeader({ a, tab, onTab }: { a: Analysis | undefined; tab: Tab; onTab: (t: string) => void }) {
  const t = useTickers();
  const open = t?.market?.open ?? true;
  const live = t?.live.find((q) => q.symbol === "PAXGUSD");
  // while spot is shut, show the spot close, not the weekend token trade
  const price = open ? (live?.price ?? a?.mtf?.price ?? null) : (t?.weekend?.spot_close ?? a?.mtf?.price ?? null);
  const day = open ? (live?.change_pct ?? a?.technical?.changes["1d"] ?? null) : (a?.technical?.changes["1d"] ?? null);
  const problems = sourceProblems(a?.sources_status);
  return (
    <div className="ihead">
      <div className="ihead-id">
        <span className="coin" aria-hidden="true"><GoldMark size={26} /></span>
        <div>
          <h1 className="ihead-name">XAU/USD</h1>
          <span className="muted small">Zlato · spot (cena PAXG)</span>
        </div>
        {price !== null && (
          <div className="ihead-price">
            <strong>{usd(price)}</strong>
            {day !== null && <span className={day > 0 ? "pos" : day < 0 ? "neg" : ""}>{day > 0 ? "▲" : day < 0 ? "▼" : "◆"} {signed(day, 2)} %</span>}
            <span className="muted small">{open ? "živě · obnova 60 s" : "uzavření trhu"}</span>
          </div>
        )}
        {a?.sources_status && (
          <button type="button" className={`data-chip ${problems ? "warn" : "ok"}`} onClick={() => onTab("sources")}>
            {problems ? `⚠ ${problems} ${problems === 1 ? "zdroj zpožděný" : "zdroje zpožděné"}` : "✓ Data aktuální"}
          </button>
        )}
      </div>
      <nav className="ihead-tabs" aria-label="Rozbor">
        <Pills label="Rozbor" size="md" options={TABS.map((t) => ({ value: t.key, label: t.label }))} value={tab} onChange={(t) => onTab(t)} />
      </nav>
    </div>
  );
}

function ComingSoon({ info }: { info: DashboardInstrument }) {
  return (
    <main className="page">
      <section className="panel">
        <h1>
          {info.code} <span className="muted">{info.name}</span>
        </h1>
        <p className="state state-unavailable">
          <span aria-hidden="true">⊘</span> Připravujeme — rozbor pro {info.code} zatím není hotový. Nezobrazuje se žádný výhled ani skóre, protože z
          dat zatím nic spočítáno nebylo.
        </p>
      </section>
    </main>
  );
}
