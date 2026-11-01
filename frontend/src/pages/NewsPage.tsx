import { useState, type CSSProperties } from "react";
import { NewsList } from "../components/Bits";
import { Icon } from "../components/Icon";
import { Card, Empty, ErrorState, Pills, Skeleton } from "../components/ui";
import { MarketIcon } from "../components/Visual";
import { SHORT_NAME, useMarkets } from "../hooks/useMarkets";

type Kind = "news" | "tech";

/** News for each market, or the technical outlooks public portals wrote about it. */
export function NewsPage() {
  const data = useMarkets();
  const [code, setCode] = useState("all");
  const [kind, setKind] = useState<Kind>("news");
  if (data.error && !data.data) return <main className="page"><ErrorState message={data.error.message} onRetry={data.reload} /></main>;
  if (!data.data) return <main className="page"><div className="card"><Skeleton rows={6} /></div></main>;
  const markets = data.data.markets.filter((m) => code === "all" || m.code === code);
  return (
    <main className="page">
      <header className="page-head rise">
        <h1>Zprávy</h1>
        <p>
          {kind === "news"
            ? "fxstreet.cz, FXStreet, Investing.com, CNBC, MarketWatch, centrální banky · anglické titulky přeložené"
            : "Technické rozbory z veřejných webů Investing.com, FXEmpire a FXStreet — převzaté s odkazem, nejsou to naše signály"}
        </p>
      </header>
      <div className="filters rise" style={{ "--i": 1 } as CSSProperties}>
        <Pills label="Druh" options={[{ value: "news", label: "Zprávy" }, { value: "tech", label: "Technický výhled" }]} value={kind} onChange={setKind} />
        <Pills label="Trh" options={[{ value: "all", label: "Vše" }, ...data.data.markets.map((m) => ({ value: m.code, label: SHORT_NAME[m.code] ?? m.name }))]}
               value={code} onChange={setCode} />
      </div>
      {markets.map((m, i) => {
        const items = kind === "news" ? m.news : m.technical;
        return (
          <Card key={`${m.code}-${kind}`} i={i + 2} id={`n-${m.code}`}
                title={<a href={`#/trh/${m.code}`} className="card-title-link"><MarketIcon code={m.code} size={24} /> {SHORT_NAME[m.code] ?? m.name}</a>}
                extra={<a className="card-link" href={`#/trh/${m.code}`}>Detail <Icon name="chevronRight" size={14} /></a>}>
            {items.length ? (
              <NewsList items={items} start={i + 3} />
            ) : (
              <Empty>{kind === "news" ? "Za poslední dva dny nic konkrétního k tomuto trhu." : "Teď žádný nový technický rozbor z veřejných webů."}</Empty>
            )}
          </Card>
        );
      })}
    </main>
  );
}
