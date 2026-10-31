import { Donut } from "../../components/Donut";
import { LongShortChart } from "../../components/LongShortChart";
import { Panel } from "../../components/Panel";
import { Unavailable } from "../../components/ui";
import { formatDate, signed } from "../../lib/format";
import type { Cot, CotFlag, CotUsd, LongShortView } from "../../lib/types";

function contracts(n: number, withSign = true): string {
  const s = Math.abs(Math.round(n)).toLocaleString("cs-CZ");
  return withSign ? `${n > 0 ? "+" : n < 0 ? "−" : ""}${s}` : `${n < 0 ? "−" : ""}${s}`;
}

function pragueTime(iso: string): string {
  return new Date(iso).toLocaleString("cs-CZ", { weekday: "short", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function CotFlags({ flags }: { flags: CotFlag[] }) {
  if (!flags.length) return <p className="cot-flag is-calm small">Žádný varovný signál: bez extrému, bez prudké změny a bez divergence s cenou.</p>;
  return (
    <ul className="cot-flags">
      {flags.map((f) => (
        <li key={f.kind} className={`cot-flag k-${f.kind}`}>
          {f.text}
        </li>
      ))}
    </ul>
  );
}

function LsFacts({ v }: { v: LongShortView }) {
  return (
    <p className="small ls-facts">
      Long <strong className="tone-bullish">{v.long_pct.toLocaleString("cs-CZ")} %</strong> · short{" "}
      <strong className="tone-bearish">{v.short_pct.toLocaleString("cs-CZ")} %</strong> · za týden {signed(v.change_1w, 1)} p.b. · za 4 týdny{" "}
      {signed(v.change_4w, 1)} p.b. · 3letý index {v.index_3y === null ? "—" : `${Math.round(v.index_3y)}/100`}
    </p>
  );
}

/** Methodology additions under the gold COT: long/short split of the funds, warning signals, retail (contrarian). */
export function CotMethodology({ cot, usd }: { cot: Cot; usd: CotUsd | null | undefined }) {
  const c = cot.commercials;
  const oi = cot.open_interest_view;
  return (
    <>
      {(c || oi) && (
        <Panel title="Commercials a open interest" tag="zlato podle strategie" icon="bank">
          <div className="comm">
            {c && (
              <div className="comm-box">
                <span className="as-eyebrow">Commercials — COT index 3 roky</span>
                <strong className={`comm-num ${c.extreme === "bullish" ? "tone-bullish" : c.extreme === "bearish" ? "tone-bearish" : ""}`}>
                  {c.index_3y === null ? "—" : Math.round(c.index_3y)}<small>/100</small>
                </strong>
                {c.index_3y !== null && (
                  <span className="cot-gauge2" role="img" aria-label={`Index commercials ${Math.round(c.index_3y)} ze 100`}>
                    <span className="z-low">nejvíc short</span>
                    <span className="z-high">nejméně short</span>
                    <span className="cot-marker2" style={{ left: `${Math.max(0, Math.min(100, c.index_3y))}%` }} />
                  </span>
                )}
                <p className="small">{c.text}</p>
              </div>
            )}
            {oi && (
              <div className="comm-box">
                <span className="as-eyebrow">Open interest — 4 týdny</span>
                <strong className={`comm-num ${oi.state === "rising" ? "tone-bullish" : oi.state === "falling" ? "tone-bearish" : ""}`}>
                  {signed(oi.change_4w_pct, 1)}<small> %</small>
                </strong>
                <p className="small">{oi.text}</p>
                <p className="muted small">Nové kontrakty = do trhu vstupují peníze a signál platí víc; zavírání pozic signál oslabuje.</p>
              </div>
            )}
          </div>
          <p className="muted small">
            Strategie: u měn sleduj velké spekulanty, u komodit jako zlato hlavně commercials — firmy, které kov používají a zajišťují se. Data jsou
            k úterý, zveřejněná v pátek; pro swing obchody to stačí.
          </p>
        </Panel>
      )}
      {cot.long_short && (
        <div className="grid g-2">
          <Panel title="Long vs. short — hedgeové fondy" tag="zlato" icon="chart" note={`k ${formatDate(cot.long_short.as_of)}`}>
            <LongShortChart history={cot.long_short.history} subject="zlato" />
            <LsFacts v={cot.long_short} />
            <CotFlags flags={cot.long_short.flags} />
          </Panel>
          <RetailPanel gold={cot.retail ?? null} usd={usd?.retail ?? null} />
        </div>
      )}
      <CotUsdSection cu={usd} />
    </>
  );
}

function RetailPanel({ gold, usd }: { gold: LongShortView | null; usd: LongShortView | null }) {
  return (
    <Panel title="Retail sentiment" tag="kontrariánsky" icon="users">
      {!gold && !usd ? (
        <Unavailable>Data o malých obchodnících teď nejsou k dispozici.</Unavailable>
      ) : (
        <>
          <div className="donuts">
            {gold && (
              <div className="donut-card">
                <Donut long={gold.long_pct} short={gold.short_pct} label="Zlato — malí obchodníci" size={130} />
                <p className="muted small">Za 4 týdny {signed(gold.change_4w, 1)} p.b.</p>
              </div>
            )}
            {usd && (
              <div className="donut-card">
                <Donut long={usd.long_pct} short={usd.short_pct} label="Dolar — malí obchodníci" size={130} />
                <p className="muted small">Za 4 týdny {signed(usd.change_4w, 1)} p.b.</p>
              </div>
            )}
          </div>
          <p className="small">
            Metodika čte retail obráceně: když je většina malých obchodníků long, trh má spíš sklon padat (většina retailu prodělává). Skóre dá ±1 jen
            v extrému — long podíl u 3letého maxima nebo minima.
          </p>
          <p className="muted small">
            Náhrada: brokerská data o klientech (DXM) nejsou zdarma bez registrace, proto pozice „malých obchodníků“ z oficiálního CFTC COT.
          </p>
        </>
      )}
    </Panel>
  );
}

/** "COT – USD": hedge funds in the US Dollar Index futures (CFTC TFF), like the Funded Mind dollar lessons. */
function CotUsdSection({ cu }: { cu: CotUsd | null | undefined }) {
  if (!cu) {
    return (
      <Panel title="COT — dolar" tag="USD Index" icon="users">
        <Unavailable>COT dolaru se teď nepodařilo stáhnout z CFTC.</Unavailable>
      </Panel>
    );
  }
  const lev = cu.leveraged;
  return (
    <>
      <section className="panel cot-hero">
        <div>
          <span className="muted small">COT — dolar (US Dollar Index, ICE)</span>
          <p className="cot-lead">{cu.texts[0]}</p>
          {cu.texts.slice(1).map((t) => (
            <p key={t} className="small">{t}</p>
          ))}
        </div>
        <div className="cot-dates">
          <div><span className="muted small">Data k (úterý)</span><strong>{formatDate(cu.as_of)}</strong></div>
          <div><span className="muted small">Zveřejněno</span><strong>{pragueTime(cu.schedule.published)}</strong></div>
          <div className={cu.schedule.late ? "is-late" : ""}>
            <span className="muted small">Další report (obvykle)</span>
            <strong>{pragueTime(cu.schedule.next_release)}</strong>
          </div>
        </div>
      </section>
      <div className="grid g-2">
        <Panel title="Long vs. short — hedgeové fondy" tag="USD" icon="chart">
          {lev ? (
            <>
              <LongShortChart history={lev.history} subject="dolar" />
              <LsFacts v={lev} />
              <CotFlags flags={lev.flags} />
            </>
          ) : (
            <Unavailable>Podíl long a short nelze spočítat.</Unavailable>
          )}
        </Panel>
        <Panel title="Kdo drží dolar" tag="USD Index" icon="users" note={<><i className="lg-long" /> Long <i className="lg-short" /> Short</>}>
          <div className="donuts">
            {cu.groups.map((g) => (
              <div key={g.key} className="donut-card">
                <Donut long={g.long ?? 0} short={g.short ?? 0} label={g.label} size={120} />
                <dl className="donut-kv small">
                  <dt>Čistě</dt><dd>{contracts(g.net, false)}</dd>
                  <dt>Za týden</dt><dd className={g.change_1w > 0 ? "tone-bullish" : g.change_1w < 0 ? "tone-bearish" : ""}>{contracts(g.change_1w)}</dd>
                </dl>
                <p className="muted small">{g.who}</p>
              </div>
            ))}
          </div>
          <p className="muted small">{cu.source_label}</p>
        </Panel>
      </div>
    </>
  );
}
