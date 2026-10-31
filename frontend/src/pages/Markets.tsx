import { useCallback, useState } from "react";
import { Icon } from "../components/Icon";
import { ErrorState, Loading } from "../components/ui";
import { useAsync, useInterval } from "../hooks/useAsync";
import { useTickers } from "../hooks/useTickers";
import { ApiError, api } from "../lib/api";
import { formatDateTime } from "../lib/format";
import type { MarketCard, MarketsResponse } from "../lib/types";

export function scoreText(n: number): string {
  return n > 0 ? `+${n}` : n < 0 ? `−${Math.abs(n)}` : "0";
}

export function tone(n: number): "pos" | "neg" | "zero" {
  return n > 0 ? "pos" : n < 0 ? "neg" : "zero";
}

export function priceText(m: MarketCard, live?: number | null): string {
  const v = live ?? m.price?.value;
  if (v === undefined || v === null) return "—";
  const digits = m.digits > 3 ? 4 : m.digits;
  return v.toLocaleString("cs-CZ", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

const LIVE_SYMBOL: Record<string, string> = { XAUUSD: "PAXGUSD", EURUSD: "EURUSD", GBPUSD: "GBPUSD" };

export function useMarkets() {
  const data = useAsync(() => api.markets(), []);
  const reload = useCallback(() => data.reload(), [data.reload]);
  useInterval(reload, 120000);
  return data;
}

/** Home: every market with its fundamental score; the selected one explained on the right. */
export function Markets() {
  const data = useMarkets();
  const [selected, setSelected] = useState<string | null>(null);
  if (data.error && !data.data) {
    const missing = data.error instanceof ApiError && data.error.status === 404;
    return (
      <main className="page mi-page">
        {missing ? (
          <p className="state state-unavailable">Přehled trhů se počítá při první aktualizaci dat — chvíli počkej (asi 2–3 minuty).</p>
        ) : (
          <ErrorState message={data.error.message} onRetry={data.reload} />
        )}
      </main>
    );
  }
  if (!data.data) {
    return (
      <main className="page mi-page">
        <Loading label="Načítám přehled trhů…" />
      </main>
    );
  }
  const d: MarketsResponse = data.data;
  const sel = d.markets.find((m) => m.code === selected) ?? d.markets[0];
  return (
    <main className="page mi-page">
      <section className="mi-board" aria-labelledby="mi-title">
        <header className="mi-head">
          <div>
            <h1 id="mi-title" className="mi-title">
              MARKET INTELLIGENCE <span>/ Přehled trhů</span>
            </h1>
            <p className="mi-sub">Fundamentální směrové hodnocení trhů · skóre −10 až +10</p>
          </div>
          <span className="mi-updated">přepočteno {formatDateTime(d.computed_at)}</span>
        </header>
        <div className="mi-body">
          <ul className="mi-list" aria-label="Trhy">
            {d.markets.map((m) => (
              <li key={m.code}>
                <MarketRow m={m} active={m.code === sel?.code} onSelect={() => setSelected(m.code)} />
              </li>
            ))}
          </ul>
          {sel && <Selected m={sel} />}
        </div>
      </section>
      <p className="mi-note muted small">{d.method}</p>
    </main>
  );
}

function MarketRow({ m, active, onSelect }: { m: MarketCard; active: boolean; onSelect: () => void }) {
  const t = useTickers();
  const live = LIVE_SYMBOL[m.code] ? t?.live.find((q) => q.symbol === LIVE_SYMBOL[m.code]) : undefined;
  const ch = live?.change_pct ?? m.price?.change_pct ?? null;
  const pct = Math.min(100, (Math.abs(m.score10) / 10) * 100);
  return (
    <>
      {/* desktop: select in place; phone: open the detail page */}
      <button type="button" className={`mi-row${active ? " is-active" : ""}`} onClick={onSelect} aria-pressed={active}>
        <RowBody m={m} live={live?.price} ch={ch} pct={pct} />
      </button>
      <a className="mi-row mi-row-link" href={`#/trh/${m.code}`} aria-label={`${m.name} — otevřít detail`}>
        <RowBody m={m} live={live?.price} ch={ch} pct={pct} />
      </a>
    </>
  );
}

function RowBody({ m, live, ch, pct }: { m: MarketCard; live?: number; ch: number | null; pct: number }) {
  return (
    <>
      <span className="mi-name">
        <strong>{m.name.replace("/", "")}</strong>
        <small>{m.subtitle}</small>
      </span>
      <span className="mi-price">
        <span>{priceText(m, live)}</span>
        {ch !== null && <small className={tone(ch)}>{ch > 0 ? "+" : ch < 0 ? "−" : ""}{Math.abs(ch).toLocaleString("cs-CZ")} %</small>}
      </span>
      <span className="mi-bar" aria-hidden="true">
        <i className={tone(m.score10)} style={{ width: `${pct}%` }} />
      </span>
      <strong className={`mi-score ${tone(m.score10)}`}>{scoreText(m.score10)}</strong>
    </>
  );
}

function Selected({ m }: { m: MarketCard }) {
  const support = m.for.slice(0, 3).map((a) => a.text);
  return (
    <aside className="mi-detail" aria-label={`Detail ${m.name}`}>
      <span className="mi-eyebrow">DETAIL VYBRANÉHO TRHU</span>
      <h2 className="mi-detail-title">
        {m.name.replace("/", "")} <span className={tone(m.score10)}>{scoreText(m.score10)} / 10</span>
      </h2>
      <p className="mi-bias">
        Modelový fundamentální bias: <strong className={m.bias === "LONG" ? "pos" : m.bias === "SHORT" ? "neg" : ""}>{m.bias}</strong>
      </p>
      <h3 className="mi-h">CO PODPORUJE TENTO SMĚR</h3>
      <p className="mi-text">{support.length ? support.join(" ") : "Žádný faktor teď výrazně netlačí jedním směrem — trh je fundamentálně vyrovnaný."}</p>
      <h3 className="mi-h">CO MŮŽE VÝHLED ZMĚNIT</h3>
      <p className="mi-text">{m.change_text}</p>
      <a className="mi-open" href={`#/trh/${m.code}`}>
        Otevřít detail <Icon name="chevronRight" size={16} />
      </a>
    </aside>
  );
}
