import type { CSSProperties } from "react";
import { BiasChip, EventList, LivePrice, NewsList } from "../components/Bits";
import { Icon } from "../components/Icon";
import { Card, Empty, ErrorState, Skeleton } from "../components/ui";
import { MarketIcon, ScoreGauge } from "../components/Visual";
import { SHORT_NAME, useMarkets } from "../hooks/useMarkets";
import { useNow } from "../hooks/useNow";
import { ApiError } from "../lib/api";
import { countdown, relativeTime } from "../lib/format";
import type { Highlight, MarketCard, MarketsResponse } from "../lib/types";

function greeting(now: Date): string {
  const h = now.getHours();
  return h < 5 ? "Dobrou noc" : h < 10 ? "Dobré ráno" : h < 18 ? "Dobrý den" : "Dobrý večer";
}

/** Home: the next big release, every market's fundament, then what moves and what can move the markets. */
export function Home() {
  const data = useMarkets();
  const now = useNow(20000);
  if (data.error && !data.data) {
    const missing = data.error instanceof ApiError && data.error.status === 404;
    return (
      <main className="page">
        {missing ? <Empty>Přehled se počítá při první aktualizaci dat — chvíli počkej (asi 2–3 minuty).</Empty> : <ErrorState message={data.error.message} onRetry={data.reload} />}
      </main>
    );
  }
  if (!data.data) {
    return (
      <main className="page">
        <div className="hero"><Skeleton rows={2} /></div>
        <div className="tiles">{[0, 1, 2].map((i) => <div key={i} className="tile"><Skeleton rows={3} /></div>)}</div>
      </main>
    );
  }
  const d: MarketsResponse = data.data;
  const next = (d.next_events ?? []).find((e) => new Date(e.datetime).getTime() > now.getTime());
  const nextMin = next ? (new Date(next.datetime).getTime() - now.getTime()) / 60000 : null;
  return (
    <main className="page">
      <section className="hero rise">
        <div>
          <p className="hero-hi">{greeting(now)} 👋</p>
          <h1>Kam míří trhy</h1>
          <p className="hero-sub">Fundament, zprávy a události, které můžou trhem pohnout.</p>
        </div>
        <span className="hero-meta">
          <span className="live-dot" aria-hidden="true" /> přepočteno {relativeTime(d.computed_at)}
        </span>
      </section>

      {next && nextMin !== null && (
        <a href="#/kalendar" className={`nextup rise${nextMin <= 120 ? " is-soon" : ""}`} style={{ "--i": 1 } as CSSProperties}>
          <span className="nextup-ico"><Icon name="clock" size={20} /></span>
          <span className="nextup-body">
            <small>Další důležitá zpráva · {next.when}</small>
            <strong>{next.title} ({next.currency})</strong>
          </span>
          <span className="nextup-count">za {countdown(nextMin)}</span>
        </a>
      )}

      <h2 className="sec-title rise" style={{ "--i": 2 } as CSSProperties}>
        <Icon name="layers" size={18} /> Fundament trhů <small>skóre −10 až +10</small>
      </h2>
      <div className="tiles">
        {d.markets.map((m, i) => (
          <MarketTile key={m.code} m={m} i={i + 3} />
        ))}
      </div>

      <div className="two">
        <Card title="Co hýbe trhy" icon={<Icon name="bolt" size={16} />} i={8} id="hybe"
              extra={<a className="card-link" href="#/zpravy">Všechny zprávy <Icon name="chevronRight" size={14} /></a>}>
          {d.highlights?.length ? (
            <NewsList items={d.highlights} start={9} tags={(n) => <HighlightTags n={n as Highlight} markets={d.markets} />} />
          ) : (
            <Empty>Za poslední dny žádná zpráva, která by trhy výrazně posunula.</Empty>
          )}
        </Card>
        <Card title="Co může trh ovlivnit" icon={<Icon name="calendar" size={16} />} i={9} id="ovlivni"
              extra={<a className="card-link" href="#/kalendar">Kalendář <Icon name="chevronRight" size={14} /></a>}>
          {d.next_events?.length ? <EventList items={d.next_events} now={now} /> : <Empty>V příštích dnech žádná důležitá zpráva v kalendáři.</Empty>}
        </Card>
      </div>
      <p className="note">{d.method}</p>
    </main>
  );
}

function MarketTile({ m, i }: { m: MarketCard; i: number }) {
  const why = m.for[0]?.text ?? m.change_text;
  return (
    <a className={`tile rise t-${m.score10 > 0 ? "pos" : m.score10 < 0 ? "neg" : "zero"}`} href={`#/trh/${m.code}`} style={{ "--i": i } as CSSProperties}
       aria-label={`${SHORT_NAME[m.code] ?? m.name}: skóre ${m.score10}, ${m.word}`}>
      <span className="tile-top">
        <MarketIcon code={m.code} size={38} />
        <span className="tile-name">
          <strong>{SHORT_NAME[m.code] ?? m.name}</strong>
          <small>{m.subtitle}</small>
        </span>
        <LivePrice m={m} />
      </span>
      <span className="tile-mid">
        <ScoreGauge score={m.score10} size={104} />
        <span className="tile-verdict">
          <BiasChip m={m} />
          <small>{m.word}</small>
        </span>
      </span>
      {why && <span className="tile-why">{why}</span>}
      <span className="tile-go" aria-hidden="true"><Icon name="chevronRight" size={18} /></span>
    </a>
  );
}

function HighlightTags({ n, markets }: { n: Highlight; markets: MarketCard[] }) {
  const m = markets.find((x) => x.code === n.market);
  return (
    <>
      <span className="mtag">{SHORT_NAME[n.market] ?? m?.name ?? n.market}</span>
      {n.market === "XAUUSD" && n.impact === "bullish" && <span className="itag pos">pro zlato ↑</span>}
      {n.market === "XAUUSD" && n.impact === "bearish" && <span className="itag neg">pro zlato ↓</span>}
    </>
  );
}
