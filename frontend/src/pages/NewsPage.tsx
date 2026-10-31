import { useState } from "react";
import { Pills } from "../components/Panel";
import { ErrorState, Loading } from "../components/ui";
import { relativeTime } from "../lib/format";
import { useMarkets } from "./Markets";

/** The news that matter for each market, in one place. */
export function NewsPage() {
  const data = useMarkets();
  const [code, setCode] = useState("all");
  if (data.error && !data.data) return <main className="page mi-page"><ErrorState message={data.error.message} onRetry={data.reload} /></main>;
  if (!data.data) return <main className="page mi-page"><Loading label="Načítám zprávy…" /></main>;
  const markets = data.data.markets.filter((m) => code === "all" || m.code === code);
  return (
    <main className="page mi-page">
      <header className="cal-head">
        <div>
          <h1 className="mi-title">ZPRÁVY <span>/ podle trhu</span></h1>
          <p className="mi-sub">fxstreet.cz, FXStreet, Investing.com, CNBC, MarketWatch, centrální banky · anglické titulky přeložené</p>
        </div>
      </header>
      <div className="cal-filters">
        <Pills label="Trh" options={[{ value: "all", label: "Vše" }, ...data.data.markets.map((m) => ({ value: m.code, label: m.name.replace("/", "") }))]}
               value={code} onChange={setCode} />
      </div>
      {markets.map((m) => (
        <section key={m.code} className="md-card news-block">
          <h2 className="mi-h">
            <a href={`#/trh/${m.code}`}>{m.name.replace("/", "")}</a>
          </h2>
          {m.news.length ? (
            <ul className="md-news">
              {m.news.map((n) => (
                <li key={n.url}>
                  <a href={n.url} target="_blank" rel="noreferrer">{n.title}</a>
                  <span className="muted small">{n.source} · {relativeTime(n.published_at)}{n.translated ? " · strojový překlad" : ""}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted small">Za poslední dva dny nic konkrétního k tomuto trhu.</p>
          )}
        </section>
      ))}
    </main>
  );
}
