import { useMemo, type CSSProperties } from "react";
import { BiasChip, EventList, LivePrice, NewsList } from "../components/Bits";
import { CandleChart } from "../components/CandleChart";
import {
  AiSummary,
  CotCard,
  DxyCard,
  FtiSummary,
  HeadlineRisk,
  LevelsCard,
  NA,
  ScoreModules,
  SeasonCard,
  TechCard,
  VerdictFactors,
} from "../components/GoldCards";
import { Icon } from "../components/Icon";
import { IntermarketCard } from "../components/IntermarketCard";
import { RegimeCard } from "../components/RegimeCard";
import { Card, Empty, ErrorState, Skeleton } from "../components/ui";
import { MarketIcon, ScoreGauge, scoreText, tone } from "../components/Visual";
import { useLive } from "../hooks/useLive";
import { SHORT_NAME, useGoldAnalysis, useMarkets } from "../hooks/useMarkets";
import { useNow } from "../hooks/useNow";
import { formatDateTime, pct, price, shortDate } from "../lib/format";
import type { LiveQuote, MarketArgument, MarketCard } from "../lib/types";
import { goldLevels } from "./Dashboard";

const LINE_ONLY = new Set(["USOIL"]);

export const TABS: [string, string][] = [
  ["prehled", "Přehled"],
  ["technika", "Technika"],
  ["zony", "Zóny & likvidita"],
  ["intermarket", "Intermarket"],
  ["makro", "Makro & COT"],
  ["sezonnost", "Sezónnost"],
  ["zpravy", "Zprávy"],
  ["kalendar", "Kalendář"],
];

/** Live-engine price in the header (when the PC app streams this instrument) — with its state and source. */
function LiveHead({ q }: { q: LiveQuote }) {
  const st = q.market_status && q.market_status !== "OPEN" ? "CLOSED" : q.data_status ?? q.status;
  const ch = q.change_pct;
  return (
    <span className="ihead-price" title={`Zdroj: ${q.product ?? q.provider}\nČas: ${formatDateTime(q.quote_time)}\nMetoda: ${q.price_type ?? "cena"} ze živého streamu`}>
      <span className={`ihead-px num${st === "LIVE" ? "" : " is-stale"}`}>{price(q.mid ?? q.bid ?? null, q.digits)}</span>
      {ch != null && <span className={`num ${ch > 0 ? "pos" : ch < 0 ? "neg" : ""}`}>{pct(ch)}</span>}
      <span className={`lbadge st-${st.toLowerCase()}`}>{st}</span>
      <small className="muted">{q.product ?? q.provider}</small>
    </span>
  );
}

/** One market: header (price, data state, source), pill tabs, and each tab's cards. */
export function MarketDetail({ code, tab = "prehled" }: { code: string; tab?: string }) {
  const data = useMarkets();
  const an = useGoldAnalysis();
  const live = useLive();
  const now = useNow(20000);
  const gold = code === "XAUUSD";
  const levels = useMemo(() => (gold ? goldLevels(an.data) : []), [gold, an.data]);
  if (data.error && !data.data) return <main className="page"><ErrorState message={data.error.message} onRetry={data.reload} /></main>;
  if (!data.data) return <main className="page"><div className="ihead"><Skeleton rows={3} /></div></main>;
  const m = data.data.markets.find((x) => x.code === code);
  if (!m) return <main className="page"><Empty>Trh „{code}“ v přehledu není.</Empty></main>;
  const lq = live.snap?.instruments.find((q) => q.code === code && (q.mid ?? q.bid) != null);
  const upcoming = m.watch.filter((w) => new Date(w.datetime).getTime() > now.getTime() - 30 * 60000);
  const active = TABS.some(([k]) => k === tab) ? tab : "prehled";
  const g = gold ? an.data : undefined;
  const gErr = gold ? an.error : undefined;
  const banner = lq?.banner;

  return (
    <main className="page page-wide">
      <section className={`ihead rise t-${tone(m.score10)}`}>
        <div className="ihead-id">
          <MarketIcon code={m.code} size={48} />
          <div>
            <h1>{SHORT_NAME[m.code] ?? m.name}</h1>
            <p className="ihead-sym">{m.code} · {m.subtitle}</p>
          </div>
        </div>
        <div className="ihead-quote">
          {lq ? <LiveHead q={lq} /> : <LivePrice m={m} big />}
          {!lq && m.price && !m.price.live && <small className="muted">cena k {shortDate(m.price.as_of)} · {m.price.source}</small>}
        </div>
        <div className="ihead-score" title={`Fundamentální skóre −10 … +10 (pevná pravidla), přepočteno ${formatDateTime(data.data.computed_at)}`}>
          <ScoreGauge score={m.score10} size={110} />
          <span>
            <BiasChip m={m} />
            <small>{m.word}</small>
          </span>
        </div>
      </section>
      {banner && <div className="lbanner" role="alert">{m.code}: {banner}</div>}

      <nav className="itabs" aria-label="Části detailu">
        {TABS.map(([k, label]) => (
          <a key={k} href={`#/trh/${code}${k === "prehled" ? "" : `/${k}`}`} className={k === active ? "is-active" : ""} aria-current={k === active ? "page" : undefined}>
            {label}
          </a>
        ))}
      </nav>

      {active === "prehled" && (
        <>
          <div className="ov-grid">
            <Card title="Graf" icon={<Icon name="line" size={16} />} i={1} id="graf" className="ov-chart">
              <CandleChart code={m.code} digits={m.digits > 3 ? 4 : m.digits} lineOnly={LINE_ONLY.has(m.code)} levels={levels} />
            </Card>
            <div className="ov-side">
              <AiSummary code={m.code} i={2} />
              {gold && <FtiSummary an={g} i={3} />}
            </div>
          </div>
          {gold ? <ScoreModules an={g} error={gErr} i={4} /> : <Breakdown m={m} open />}
          <div className="two">
            <Card title="Proč" icon={<Icon name="layers" size={16} />} i={5} id="proc">
              <Reasons items={m.for.slice(0, 3)} empty="Žádný faktor teď výrazně netlačí jedním směrem." />
              {m.against.length > 0 && (
                <>
                  <h3 className="sub">Co jde proti</h3>
                  <Reasons items={m.against.slice(0, 2)} />
                </>
              )}
            </Card>
            <Card title="Co může trh ovlivnit" icon={<Icon name="calendar" size={16} />} i={6} id="ovlivni">
              {upcoming.length ? <EventList items={upcoming.slice(0, 4)} now={now} /> : <Empty>V příštích dnech v kalendáři nic důležitého.</Empty>}
              <p className="hint">{m.change_text}</p>
            </Card>
          </div>
          {gold && <CotCard an={g} error={gErr} i={7} />}
        </>
      )}

      {active === "technika" && (
        <>
          {gold && <TechCard an={g} error={gErr} i={1} />}
          {gold && <RegimeCard i={2} />}
          <Card title="Technický výhled z veřejných zdrojů" icon={<Icon name="globe" size={16} />} i={3} id="technika"
                extra={<span className="card-note">převzaté rozbory, ne náš signál</span>}>
            {m.technical.length ? (
              <NewsList items={m.technical} start={4} />
            ) : (
              <Empty>Veřejné weby (Investing.com, FXEmpire, FXStreet) k tomuto trhu za poslední dny nový technický rozbor nevydaly.</Empty>
            )}
          </Card>
        </>
      )}

      {active === "zony" && (
        <>
          {gold ? (
            <>
              <Card title="Graf se zónami" icon={<Icon name="line" size={16} />} i={1} id="graf-zony">
                <CandleChart code={m.code} digits={2} levels={levels} />
              </Card>
              <LevelsCard an={g} error={gErr} i={2} />
            </>
          ) : (
            <Card title="Zóny" icon={<Icon name="layers" size={16} />} i={1} id="zony">
              <Empty>Zóny počítá FTI zatím jen pro zlato — pro {SHORT_NAME[m.code] ?? m.name} {NA}.</Empty>
            </Card>
          )}
          <Card title="Likvidita" icon={<Icon name="target" size={16} />} i={3} id="likvidita">
            <Empty>Likviditu (shluky stop-lossů, sweepy úrovní) FTI zatím nepočítá — {NA}.</Empty>
          </Card>
        </>
      )}

      {active === "intermarket" &&
        (gold ? (
          <>
            <DxyCard an={g} error={gErr} i={1} />
            <IntermarketCard i={2} />
          </>
        ) : (
          <Card title="Intermarket" icon={<Icon name="globe" size={16} />} i={1} id="intermarket">
            <Empty>Vztahy s ostatními trhy počítá FTI zatím jen pro zlato — {NA}.</Empty>
          </Card>
        ))}

      {active === "makro" && (
        <>
          <Breakdown m={m} open />
          {gold && <VerdictFactors an={g} i={2} />}
          {gold && <CotCard an={g} error={gErr} i={3} />}
          {m.retail && <Retail m={m} />}
        </>
      )}

      {active === "sezonnost" &&
        (gold ? (
          <SeasonCard an={g} error={gErr} i={1} />
        ) : (
          <Card title="Sezónnost" icon={<Icon name="calendar" size={16} />} i={1} id="sezonnost">
            <Empty>Sezónnost počítá FTI zatím jen pro zlato — {NA}.</Empty>
          </Card>
        ))}

      {active === "zpravy" && (
        <>
          <Card title="Zprávy k trhu" icon={<Icon name="news" size={16} />} i={1} id="zpravy">
            {m.news.length ? <NewsList items={m.news} start={2} /> : <Empty>Za poslední dva dny nic konkrétního k tomuto trhu.</Empty>}
          </Card>
          {gold && <HeadlineRisk an={g} i={3} />}
        </>
      )}

      {active === "kalendar" && (
        <Card title="Co může trh ovlivnit" icon={<Icon name="calendar" size={16} />} i={1} id="ovlivni"
              extra={<a className="card-link" href="#/kalendar">Celý kalendář <Icon name="chevronRight" size={14} /></a>}>
          {upcoming.length ? <EventList items={upcoming} now={now} /> : <Empty>V příštích dnech v kalendáři nic důležitého.</Empty>}
          <p className="hint">{m.change_text}</p>
        </Card>
      )}

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

/** Score Overview of a market's fundament: every component with its own range (FTI's model). */
function Breakdown({ m, open = false }: { m: MarketCard; open?: boolean }) {
  return (
    <details className="card more rise" style={{ "--i": 4 } as CSSProperties} open={open}>
      <summary>
        <span><Icon name="chart" size={16} /> Rozpis skóre</span>
        <span className="muted">{m.raw > 0 ? "+" : ""}{m.raw} z ±{m.possible} <Icon name="chevronDown" size={16} className="more-chev" /></span>
      </summary>
      <ul className="comps">
        {m.components.map((c) => {
          const w = c.score === null ? 0 : (Math.abs(c.score) / c.max) * 50;
          return (
            <li key={c.key} title={`${c.label}: ${c.score === null ? NA : `${scoreText(c.score)} z ±${c.max}`}\n${c.details.join(" · ")}`}>
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
