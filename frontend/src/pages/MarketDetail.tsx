import type { CSSProperties } from "react";
import { AiPanel, AiTradePanel } from "../components/AiPanel";
import { BiasChip, EventList, LivePrice, NewsList } from "../components/Bits";
import { CandleChart } from "../components/CandleChart";
import { Icon } from "../components/Icon";
import { Card, Empty, ErrorState, Skeleton } from "../components/ui";
import { MarketIcon, ScoreGauge, scoreText, tone } from "../components/Visual";
import { SHORT_NAME, useMarkets } from "../hooks/useMarkets";
import { useNow } from "../hooks/useNow";
import { formatDateTime, shortDate } from "../lib/format";
import type { MarketArgument, MarketCard } from "../lib/types";

const LINE_ONLY = new Set(["USOIL"]);

/** One market: score and its reasons first, then what can move it, public technical outlooks, chart, details. */
export function MarketDetail({ code }: { code: string }) {
  const data = useMarkets();
  const now = useNow(20000);
  if (data.error && !data.data) return <main className="page"><ErrorState message={data.error.message} onRetry={data.reload} /></main>;
  if (!data.data) return <main className="page"><div className="dhero"><Skeleton rows={3} /></div></main>;
  const m = data.data.markets.find((x) => x.code === code);
  if (!m) return <main className="page"><Empty>Trh „{code}“ v přehledu není.</Empty></main>;
  const upcoming = m.watch.filter((w) => new Date(w.datetime).getTime() > now.getTime() - 30 * 60000).slice(0, 4);
  return (
    <main className="page">
      <a className="back rise" href="#/"><Icon name="chevronLeft" size={16} /> Přehled</a>
      <section className={`dhero rise t-${tone(m.score10)}`}>
        <div className="dhero-id">
          <MarketIcon code={m.code} size={56} />
          <div>
            <h1>{SHORT_NAME[m.code] ?? m.name}</h1>
            <p>{m.subtitle}</p>
            <LivePrice m={m} big />
            {m.price && !m.price.live && <small className="muted">cena k {shortDate(m.price.as_of)}</small>}
          </div>
        </div>
        <div className="dhero-score">
          <ScoreGauge score={m.score10} size={180} />
          <BiasChip m={m} />
          <p>{m.word}</p>
        </div>
      </section>

      <div className="two">
        <Card title="Proč" icon={<Icon name="layers" size={16} />} i={1} id="proc">
          <Reasons items={m.for.slice(0, 3)} empty="Žádný faktor teď výrazně netlačí jedním směrem." />
          {m.against.length > 0 && (
            <>
              <h3 className="sub">Co jde proti</h3>
              <Reasons items={m.against.slice(0, 2)} />
            </>
          )}
        </Card>
        <Card title="Co může trh ovlivnit" icon={<Icon name="calendar" size={16} />} i={2} id="ovlivni">
          {upcoming.length ? <EventList items={upcoming} now={now} /> : <Empty>V příštích dnech v kalendáři nic důležitého.</Empty>}
          <p className="hint">{m.change_text}</p>
        </Card>
      </div>

      <Card title="Technický výhled z veřejných zdrojů" icon={<Icon name="globe" size={16} />} i={3} id="technika"
            extra={<span className="card-note">převzaté rozbory, ne náš signál</span>}>
        {m.technical.length ? (
          <NewsList items={m.technical} start={4} />
        ) : (
          <Empty>Veřejné weby (Investing.com, FXEmpire, FXStreet) k tomuto trhu za poslední dny nový technický rozbor nevydaly.</Empty>
        )}
      </Card>

      <Card title="Zprávy k trhu" icon={<Icon name="news" size={16} />} i={4} id="zpravy">
        {m.news.length ? <NewsList items={m.news} start={5} /> : <Empty>Za poslední dva dny nic konkrétního k tomuto trhu.</Empty>}
      </Card>

      <Card title="Graf" icon={<Icon name="line" size={16} />} i={5} id="graf">
        <CandleChart code={m.code} digits={m.digits > 3 ? 4 : m.digits} lineOnly={LINE_ONLY.has(m.code)} />
      </Card>

      {m.retail && <Retail m={m} />}
      <Breakdown m={m} />
      <AiTradePanel code={m.code} i={8} />
      <AiPanel code={m.code} i={9} />

      <p className="note">
        Přepočteno {formatDateTime(data.data.computed_at)}. {m.missing.length > 0 && `Bez dat: ${m.missing.join(", ")} — skóre je přepočtené z ostatních kategorií. `}
        Není to investiční doporučení.
      </p>
    </main>
  );
}

function Reasons({ items, empty }: { items: MarketArgument[]; empty?: string }) {
  if (!items.length) return empty ? <Empty>{empty}</Empty> : null;
  return (
    <ul className="reasons">
      {items.map((a, i) => (
        <li key={a.label} className={`rise r-${tone(a.score)}`} style={{ "--i": i + 2 } as CSSProperties}>
          <span className="r-badge">{scoreText(a.score)}</span>
          <span>
            <strong>{a.label}</strong>
            <span>{a.text}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function Retail({ m }: { m: MarketCard }) {
  const r = m.retail!;
  return (
    <Card title="Drobní obchodníci" icon={<Icon name="users" size={16} />} i={6} id="retail">
      <div className="rs-bar" role="img" aria-label={`${Math.round(r.long_pct)} % long, ${Math.round(r.short_pct)} % short`}>
        <i className="rs-long" style={{ width: `${r.long_pct}%` }} />
        <i className="rs-short" style={{ width: `${r.short_pct}%` }} />
      </div>
      <div className="rs-legend">
        <span className="pos">{Math.round(r.long_pct)} % long</span>
        <span className="neg">{Math.round(r.short_pct)} % short</span>
      </div>
      <p className="hint">
        <strong>{r.head}</strong> {r.text}
      </p>
      <p className="src">{r.source}{r.as_of ? ` Data k ${shortDate(r.as_of)}.` : ""}</p>
    </Card>
  );
}

function Breakdown({ m }: { m: MarketCard }) {
  return (
    <details className="card more rise" style={{ "--i": 7 } as CSSProperties}>
      <summary>
        <span><Icon name="chart" size={16} /> Rozpis skóre</span>
        <span className="muted">{m.raw > 0 ? "+" : ""}{m.raw} z ±{m.possible} <Icon name="chevronDown" size={16} className="more-chev" /></span>
      </summary>
      <ul className="comps">
        {m.components.map((c) => {
          const w = c.score === null ? 0 : (Math.abs(c.score) / c.max) * 50;
          return (
            <li key={c.key}>
              <span className="comp-label">{c.label}</span>
              <span className="comp-bar" aria-hidden="true">
                <i className={c.score === null ? "" : tone(c.score)} style={{ width: `${w}%`, [c.score !== null && c.score < 0 ? "right" : "left"]: "50%" }} />
              </span>
              <span className={`comp-score ${c.score === null ? "na" : tone(c.score)}`}>
                {c.score === null ? "—" : scoreText(c.score)}
                <small>/±{c.max}</small>
              </span>
              <p className="comp-text">
                {c.text}
                {c.details.length > 0 && <small className="comp-details">{c.details.join(" · ")}</small>}
              </p>
            </li>
          );
        })}
      </ul>
    </details>
  );
}
