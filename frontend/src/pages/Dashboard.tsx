import { useMemo, type CSSProperties, type ReactNode } from "react";
import { EventList } from "../components/Bits";
import { CandleChart } from "../components/CandleChart";
import { LastSignals, NA, ScoreModules } from "../components/GoldCards";
import { Icon } from "../components/Icon";
import type { Level } from "../components/LwChart";
import { CenterBar, Meter, Segments, Sparkline } from "../components/Spark";
import { Card, Empty, ErrorState, Skeleton } from "../components/ui";
import { scoreText } from "../components/Visual";
import { useLive } from "../hooks/useLive";
import { useGoldAnalysis, useMarkets, useRegime } from "../hooks/useMarkets";
import { useNow } from "../hooks/useNow";
import { useTickers } from "../hooks/useTickers";
import { ApiError } from "../lib/api";
import { ftiDecision } from "../lib/decision";
import { formatDateTime, pct, price, relativeTime } from "../lib/format";
import { topQuotes } from "../lib/quotes";
import type { GoldAnalysis } from "../lib/types";

const DEC_CLASS: Record<string, string> = { LONG: "pos", SHORT: "neg", NEUTRAL: "zero", "NO TRADE": "none" };

export function goldLevels(an?: GoldAnalysis): Level[] {
  const t = an?.technical;
  if (!t) return [];
  return [
    ...(t.supports ?? []).map((s, i) => ({ price: s.price, kind: "support" as const, title: `S${i + 1}` })),
    ...(t.resistances ?? []).map((r, i) => ({ price: r.price, kind: "resistance" as const, title: `R${i + 1}` })),
  ];
}

function Kpi({ label, value, sub, chart, tip, i, muted }: { label: string; value: ReactNode; sub?: ReactNode; chart?: ReactNode; tip: string; i: number; muted?: boolean }) {
  return (
    <section className="kpi rise" style={{ "--i": i } as CSSProperties} title={tip} aria-label={label}>
      <p className="label">{label}</p>
      <p className={`kpi-value${muted ? " is-na" : ""}`}>{value}</p>
      {sub && <p className="kpi-sub">{sub}</p>}
      <div className="kpi-chart">{chart}</div>
    </section>
  );
}

/** Dashboard: FTI's decision for gold with its reason, five KPIs, the chart, module scores, events and signals. */
export function Dashboard() {
  const markets = useMarkets();
  const an = useGoldAnalysis();
  const live = useLive();
  const tickers = useTickers();
  const regime = useRegime();
  const now = useNow(20000);
  const levels = useMemo(() => goldLevels(an.data), [an.data]);

  if (markets.error && !markets.data && !an.data) {
    const missing = markets.error instanceof ApiError && markets.error.status === 404;
    return (
      <main className="page">
        {missing ? <Empty>Přehled se počítá při první aktualizaci dat — chvíli počkej (asi 2–3 minuty).</Empty> : <ErrorState message={markets.error.message} onRetry={markets.reload} />}
      </main>
    );
  }

  const goldLive = live.snap?.instruments.find((q) => q.code === "XAUUSD");
  const goldTick = [...(tickers?.live ?? []), ...(tickers?.daily ?? [])].find((q) => q.symbol === "XAUUSD");
  const marketOpen = goldLive?.market_status ? goldLive.market_status === "OPEN" : goldTick?.market ? goldTick.market.state === "OPEN" : tickers?.market?.open;
  const marketText = goldLive?.market_status_cs ?? goldTick?.market?.label ?? (marketOpen === undefined ? "stav trhu neověřen" : marketOpen ? "trh otevřen" : "trh zavřen");
  const decision = ftiDecision(an.data?.verdict, goldLive, marketOpen);
  const quotes = topQuotes(live.snap, tickers, an.data, regime.data);
  const gq = quotes[0];
  const stale = marketOpen === true && (gq.state === "DELAYED" || gq.state === "N/A");
  const gold = markets.data?.markets.find((m) => m.code === "XAUUSD");
  const t = an.data?.technical;
  const hist = t?.history?.slice(-60) ?? [];
  const reg = regime.data;
  const dim = (k: string) => reg?.dimensions.find((d) => d.key === k);
  const count = (s: string) => quotes.filter((q) => q.state === s).length;
  const late = (an.data?.sources_status ?? []).filter((s) => s.status !== "ok");
  const next = (markets.data?.next_events ?? []).filter((e) => new Date(e.datetime).getTime() > now.getTime() - 30 * 60000).slice(0, 5);
  const date = now.toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Prague" });

  return (
    <main className="page page-wide">
      {(goldLive?.banner || stale) && (
        <div className="lbanner rise" role="alert">
          XAUUSD: {goldLive?.banner ?? "TRH OTEVŘEN – DATA NEAKTUÁLNÍ"}
          <small> — cena {gq.state === "N/A" ? "chybí" : `je ${gq.state}`}, zdroj {gq.source}</small>
        </div>
      )}

      <section className={`dash-hero rise dec-${DEC_CLASS[decision.kind]}`} aria-label="Rozhodnutí FTI pro zlato">
        <div className="dh-main">
          <p className="label">
            {date} · {marketText}
          </p>
          <h1>Rozhodnutí FTI pro zlato</h1>
          <p className="dh-decision">
            <span className={`decision dec-${DEC_CLASS[decision.kind]}`}>{decision.kind}</span>
            {decision.kind === "NEUTRAL" && <span className="muted">vyčkat</span>}
          </p>
          <p className="dh-reason">{decision.reason}</p>
          {decision.engine && decision.engine !== decision.kind && (
            <p className="dh-engine">Samotný verdikt enginu: {decision.engine} — pravidlo výše má přednost.</p>
          )}
          <p className="dh-meta"
             title="Pravidlový verdikt FTI: fundament, technika, COT a další faktory s pevnými vahami. Bez živé ceny a při zavřeném trhu NO TRADE.">
            Pravidlový verdikt FTI, ne AI
            {an.data?.verdict && ` · jistota ${an.data.verdict.confidence}`}
            {an.data && ` · přepočteno ${relativeTime(an.data.computed_at)}`}
            {an.error && !an.data && ` · ${an.error.message}`} · <a href="#/trh/XAUUSD">detail zlata</a>
          </p>
        </div>
        {an.data?.verdict && (
          <ul className="dh-factors">
            {an.data.verdict.factors.map((f) => (
              <li key={f.key} title={`${f.sentence}\nváha ${Math.round(f.weight * 100)} % · ${f.detail}`}>
                <span className={`dh-arrow ${f.direction === "up" ? "pos" : f.direction === "down" ? "neg" : "zero"}`} aria-hidden="true">
                  {f.direction === "up" ? "↑" : f.direction === "down" ? "↓" : "→"}
                </span>
                <span>
                  <strong>{f.label}</strong>
                  <small>{f.sentence}</small>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="kpis">
        <Kpi i={1} label="XAUUSD" muted={gq.price === null}
             tip={`Zdroj: ${gq.source}${gq.time ? `\nČas: ${formatDateTime(gq.time)}` : ""}\nMetoda: ${gq.method}`}
             value={<span className={`num${gq.state === "DELAYED" ? " is-stale" : ""}`}>{gq.price === null ? NA : price(gq.price, 2)}</span>}
             sub={<><span className={`lbadge st-${gq.state === "N/A" ? "unavailable" : gq.state.toLowerCase()}`}>{gq.state}</span>{gq.change_pct !== null && <span className={gq.change_pct > 0 ? "pos" : gq.change_pct < 0 ? "neg" : ""}> {pct(gq.change_pct)}</span>}</>}
             chart={hist.length > 1 && <Sparkline values={hist.map((h) => h.close)} label="Denní závěry zlata za posledních 60 dní" />} />
        <Kpi i={2} label="Režim trhu" muted={!reg}
             tip={reg ? `${reg.summary}\nMetoda: ${reg.method}\nVýpočet ${formatDateTime(reg.computed_at)}` : "Režim trhu FTI teď nemá."}
             value={dim("trend")?.word ?? NA}
             sub={reg && [dim("volatilita")?.word && `volatilita ${dim("volatilita")!.word.toLowerCase()}`, dim("riziko")?.word?.toLowerCase()].filter(Boolean).join(" · ")}
             chart={reg?.atr && <><Meter value={reg.atr.percentile} label={`ATR percentil ${reg.atr.percentile}`} /><small className="kpi-note">ATR percentil {reg.atr.percentile} z {reg.atr.window} dní</small></>} />
        <Kpi i={3} label="Fundament zlata" muted={!gold}
             tip={gold ? `Skóre −10 … +10 z makro dat (pevná pravidla)\nPřepočteno ${formatDateTime(markets.data?.computed_at)}` : "Skóre FTI teď nemá."}
             value={gold ? <span className={`num ${gold.score10 > 0 ? "pos" : gold.score10 < 0 ? "neg" : ""}`}>{scoreText(gold.score10)}</span> : NA}
             sub={gold?.word}
             chart={gold && <CenterBar value={gold.score10} max={10} label={`Skóre ${scoreText(gold.score10)} z 10`} />} />
        <Kpi i={4} label="Technický bias" muted={!t}
             tip={t ? `Denní technika FTI k ${t.as_of}: průměry 50/200, struktura, momentum\nČára = závěry, šedá = SMA 50` : "Technika zlata je jen v aplikaci na PC."}
             value={t?.trend_label ?? NA}
             sub={t && `skóre ${t.tech_score == null ? "—" : Math.round(t.tech_score)} z ±100 · RSI ${t.rsi14 == null ? "—" : Math.round(t.rsi14)}`}
             chart={hist.length > 1 && <Sparkline values={hist.map((h) => h.close)} compare={hist.map((h) => h.sma50)} label="Závěry a SMA 50 za 60 dní" />} />
        <Kpi i={5} label="Stav dat"
             tip={quotes.map((q) => `${q.label}: ${q.state}`).join("\n") + (late.length ? `\n\nOpožděné zdroje:\n${late.map((s) => `${s.label} — ${s.note ?? s.status}`).join("\n")}` : "")}
             value={<span className="num">{count("LIVE")} LIVE</span>}
             sub={`${count("DELAYED")} DELAYED · ${count("CLOSED")} CLOSED · ${count("N/A")} N/A${late.length ? ` · ${late.length} zdroj${late.length === 1 ? "" : "e"} pozdě` : ""}`}
             chart={<Segments label="Stav šesti kurzů v horní liště" parts={[
               { n: count("LIVE"), cls: "live", title: "LIVE" },
               { n: count("DELAYED"), cls: "delayed", title: "DELAYED" },
               { n: count("CLOSED"), cls: "closed", title: "CLOSED" },
               { n: count("N/A"), cls: "na", title: "N/A" },
             ]} />} />
      </div>

      <div className="dash-grid">
        <Card title="Zlato — graf" icon={<Icon name="line" size={16} />} i={6} id="graf" className="dash-chart"
              extra={<a className="card-link" href="#/trh/XAUUSD">Detail <Icon name="chevronRight" size={14} /></a>}>
          <CandleChart code="XAUUSD" digits={2} initialTf="H1" levels={levels} />
        </Card>
        <ScoreModules an={an.data} error={an.error} i={7} />
        <Card title="Nejbližší události" icon={<Icon name="calendar" size={16} />} i={8} id="udalosti"
              extra={<a className="card-link" href="#/kalendar">Kalendář <Icon name="chevronRight" size={14} /></a>}>
          {!markets.data ? <Skeleton rows={3} /> : next.length ? <EventList items={next} now={now} /> : <Empty>V příštích dnech žádná důležitá zpráva v kalendáři.</Empty>}
        </Card>
        <LastSignals i={9} />
      </div>
      <p className="note">Rozhodnutí FTI není investiční doporučení. FTI nikdy neobchoduje — obchody zadáváš ty.</p>
    </main>
  );
}
