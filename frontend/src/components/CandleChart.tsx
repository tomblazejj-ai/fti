import { useEffect, useMemo, useRef, useState } from "react";
import { useLive } from "../hooks/useLive";
import { ALL_TFS, DAILY_TFS, FEEDS, historyFeed, liveFeed, mergeBars, type FeedId, type FeedResult } from "../lib/chartFeed";
import { formatDateTime, relativeTime } from "../lib/format";
import type { Tf } from "../lib/types";
import { MarketChip, QualityBadge } from "./Bits";
import { LwChart, timeText, type Hover, type Level } from "./LwChart";
import { Pills } from "./ui";

const NO_LEVELS: Level[] = [];
/** the live engine is preferred in "Auto" when it already has this many candles of the timeframe */
const LIVE_MIN_BARS = 60;

export const INSTRUMENT_NAMES: Record<string, string> = {
  XAUUSD: "XAUUSD", EURUSD: "EURUSD", GBPUSD: "GBPUSD", USDJPY: "USDJPY", USOIL: "Ropa WTI", "US500.CFD": "US500", "US100.CFD": "NAS100",
};

type Mode = "auto" | FeedId;

function fmt(v: number, digits: number): string {
  return v.toLocaleString("cs-CZ", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** The price chart of FTI (TradingView Lightweight Charts™): M1–MN1, live candles through series.update(), crosshair
 * with OHLC, bid / ask / spread, zoom and moving, S/R lines and sessions. The data come from a feed (lib/chartFeed) —
 * the chart shows which source the candles are from and never mixes two sources in one series. */
export function CandleChart({
  code,
  digits = 2,
  initialTf = "D1",
  lineOnly = false,
  levels = NO_LEVELS,
  codes,
  onCode,
  fixedFeed,
  onTf,
}: {
  code: string;
  digits?: number;
  initialTf?: Tf;
  /** daily closing prices only (USD/JPY from ECB, WTI from FRED): a line on D1/W1/MN1 */
  lineOnly?: boolean;
  /** supports / resistances from FTI's engine (gold) */
  levels?: Level[];
  /** instruments to pick from (the charts page) */
  codes?: string[];
  onCode?: (code: string) => void;
  /** only this feed (the live terminal) */
  fixedFeed?: FeedId;
  onTf?: (tf: Tf) => void;
}) {
  const live = useLive();
  const liveTfs = fixedFeed === "history" ? [] : liveFeed.tfs(code);
  const histTfs = fixedFeed === "live" ? [] : historyFeed.tfs(code);
  const tfs: Tf[] = lineOnly ? ["D1", "W1", "MN1"] : ALL_TFS.filter((t) => liveTfs.includes(t) || histTfs.includes(t));
  const [tfState, setTf] = useState<Tf>(initialTf);
  const tf = tfs.includes(tfState) ? tfState : tfs.includes("D1") ? "D1" : tfs[0] ?? "D1";
  const [mode, setMode] = useState<Mode>(fixedFeed ?? "auto");
  const [kindState, setKind] = useState<"candles" | "line">("candles");
  const [showEma, setShowEma] = useState(false);
  const [showLevels, setShowLevels] = useState(true);
  const [showSess, setShowSess] = useState(false);
  const [showQuote, setShowQuote] = useState(true);
  const [data, setData] = useState<FeedResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [hover, setHover] = useState<Hover | null>(null);
  const loadedFor = useRef("");

  const liveOk = liveTfs.includes(tf);
  const histOk = histTfs.includes(tf);
  const key = `${code}|${tf}|${mode}`;

  // the whole series when the instrument, timeframe or source changes
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setHover(null);
    const pick = async (): Promise<FeedResult> => {
      if (mode === "live" && liveOk) return liveFeed.load(code, tf);
      if (mode === "history" && histOk) return historyFeed.load(code, tf);
      if (liveOk) {
        try {
          const r = await liveFeed.load(code, tf);
          if (r.bars.length >= LIVE_MIN_BARS || !histOk) return r;
        } catch (e) {
          if (!histOk) throw e;
        }
      }
      if (histOk) return historyFeed.load(code, tf);
      throw new Error("Pro tento rámec zatím žádný zdroj svíček nemá.");
    };
    pick()
      .then((r) => {
        if (cancelled) return;
        loadedFor.current = key;
        setData(r);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        loadedFor.current = key;
        setData(null);
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, liveOk, histOk]);

  // live candles: the stream says a price changed → only the newest bars, merged (series.update in the chart)
  const version = live.snap?.version ?? 0;
  const lastTail = useRef(0);
  useEffect(() => {
    if (!data || data.feed !== "live" || loadedFor.current !== key) return;
    const now = Date.now();
    if (now - lastTail.current < 1000) return;
    lastTail.current = now;
    let cancelled = false;
    liveFeed.tail?.(code, tf)
      .then((t) => {
        if (cancelled || loadedFor.current !== key) return;
        setData((d) => (d && d.feed === "live" ? { ...d, bars: mergeBars(d.bars, t.bars), status: t.status } : d));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  // history candles: re-read on a timer, merged the same way
  const feedId = data?.feed;
  useEffect(() => {
    if (feedId !== "history") return;
    const ms = DAILY_TFS.has(tf) ? 300000 : 60000;
    const id = window.setInterval(() => {
      FEEDS.history.load(code, tf)
        .then((r) => {
          if (loadedFor.current !== key) return;
          setData((d) => (d && d.feed === "history" ? { ...r, bars: mergeBars(d.bars, r.bars) } : d));
        })
        .catch(() => undefined);
    }, ms);
    return () => window.clearInterval(id);
  }, [feedId, key, code, tf]);

  const bars = data?.bars ?? [];
  const lineData = lineOnly || !!data?.lineOnly;
  const kind = lineData ? "line" : kindState;
  const daily = DAILY_TFS.has(tf);
  const shownLevels = useMemo(() => (showLevels ? levels : NO_LEVELS), [showLevels, levels]);
  const q = live.snap?.instruments.find((i) => i.code === code);
  // bid / ask lines only over candles of the same source (the live engine's own provider)
  const sameSource = !!q && data?.feed === "live" && !!data.provider && q.provider === data.provider;
  const quoteLines = useMemo(() => (sameSource && showQuote && q ? { bid: q.bid ?? null, ask: q.ask ?? null } : null), [sameSource, showQuote, q]);
  const last = bars[bars.length - 1];
  const legend = hover ?? (last ? { time: (daily && last.day ? last.day : last.t) as Hover["time"], o: last.o, h: last.h, l: last.l, c: last.c } : null);
  const d = digits;
  const status = data?.status ?? null;
  const feedLabel = data ? (data.feed === "live" ? "živý engine" : "historie FTI") : "";

  const pickTf = (t: Tf) => {
    setTf(t);
    onTf?.(t);
  };

  return (
    <div className="cchart">
      <div className="cchart-bar">
        {codes && onCode && (
          <select className="cchart-code" value={code} onChange={(e) => onCode(e.target.value)} aria-label="Instrument">
            {codes.map((c) => (
              <option key={c} value={c}>{INSTRUMENT_NAMES[c] ?? c}</option>
            ))}
          </select>
        )}
        <div className="tf-chips" role="group" aria-label="Časový rámec">
          {tfs.map((t) => (
            <button key={t} type="button" className={`tf-chip${t === tf ? " is-active" : ""}`} aria-pressed={t === tf} onClick={() => pickTf(t)}
                    title={`${liveTfs.includes(t) ? "živý engine" : ""}${liveTfs.includes(t) && histTfs.includes(t) ? " · " : ""}${histTfs.includes(t) ? "historie FTI" : ""}`}>
              {t}
            </button>
          ))}
        </div>
        <div className="cchart-bar-right">
          {!fixedFeed && liveOk && histOk && (
            <Pills
              label="Zdroj svíček"
              options={[
                { value: "auto", label: "Auto", title: "Živý engine, když už má dost svíček; jinak historie FTI" },
                { value: "live", label: "Živě", title: "Svíčky živého enginu (z ticků)" },
                { value: "history", label: "Historie", title: "Svíčky z historie FTI" },
              ]}
              value={mode}
              onChange={setMode}
            />
          )}
          {data?.feed === "history" && (
            <button type="button" className={`legend-toggle${showEma ? " is-on" : ""}`} onClick={() => setShowEma((s) => !s)} aria-pressed={showEma}>
              <i className="lg-ema20" /> EMA20 <i className="lg-ema50" /> EMA50
            </button>
          )}
          {levels.length > 0 && (
            <button type="button" className={`legend-toggle${showLevels ? " is-on" : ""}`} onClick={() => setShowLevels((s) => !s)} aria-pressed={showLevels}
                    title="Podpory a rezistence z výpočtu FTI (denní data)">
              <i className="lg-sr" /> S/R
            </button>
          )}
          {!daily && (
            <button type="button" className={`legend-toggle${showSess ? " is-on" : ""}`} onClick={() => setShowSess((s) => !s)} aria-pressed={showSess}
                    title="Londýn 8–17 h londýnského času, New York 8–17 h newyorského času">
              <i className="lg-sess" /> Seance
            </button>
          )}
          {sameSource && (
            <button type="button" className={`legend-toggle${showQuote ? " is-on" : ""}`} onClick={() => setShowQuote((s) => !s)} aria-pressed={showQuote}
                    title="Čáry bid a ask ze stejného zdroje jako svíčky">
              <i className="lg-ba" /> Bid/Ask
            </button>
          )}
          {!lineData && (
            <Pills
              label="Typ grafu"
              options={[
                { value: "candles", label: "Svíčky", title: "Svíčkový graf" },
                { value: "line", label: "Čára", title: "Čárový graf" },
              ]}
              value={kind}
              onChange={setKind}
            />
          )}
        </div>
      </div>
      <div className="cchart-box">
        <LwChart bars={bars} kind={kind} digits={d} daily={daily} ema={showEma && data?.feed === "history"} levels={shownLevels}
                 sessions={showSess && !daily} quote={quoteLines} onHover={setHover}
                 label={`Graf ${INSTRUMENT_NAMES[code] ?? code}, časový rámec ${tf}, ${bars.length} svíček, zdroj ${data?.source ?? "—"}`} />
        {data && (
          <div className="cchart-legend" aria-live="off">
            <span className="cl-sym">{INSTRUMENT_NAMES[code] ?? code} · {tf}</span>
            {legend && (
              <span className="cl-ohlc num" title="Svíčka pod kurzorem (bez kurzoru poslední)">
                {timeText(legend.time, daily)} · O {fmt(legend.o, d)} · H {fmt(legend.h, d)} · L {fmt(legend.l, d)} · C {fmt(legend.c, d)}
              </span>
            )}
            <span className="cl-src" title={`Zdroj svíček: ${data.source}${data.priceType ? ` · cena ${data.priceType}` : ""} · ${feedLabel}`}>
              Zdroj: {data.source}{data.priceType ? ` (${data.priceType})` : ""}
              {status && <span className={`lbadge st-${status.toLowerCase()}`}>{status}</span>}
            </span>
          </div>
        )}
        {!bars.length && (
          <p className="cchart-msg">{error ? `Graf se nepodařilo načíst: ${error}` : loading ? "Načítám graf…" : "Pro tento rámec zatím nejsou svíčky."}</p>
        )}
      </div>
      {q && (q.bid != null || q.ask != null) && (
        <p className="cchart-quote" title={`Živá kotace ${q.product ?? q.provider} · ${formatDateTime(q.quote_time)}`}>
          <span>Bid <strong className="num">{q.bid != null ? fmt(q.bid, q.digits) : "—"}</strong></span>
          <span>Ask <strong className="num">{q.ask != null ? fmt(q.ask, q.digits) : "—"}</strong></span>
          <span>Spread <strong className="num">{q.spread != null ? fmt(q.spread, q.digits) : "—"}</strong></span>
          <span className={`lbadge st-${(q.data_status ?? q.status).toLowerCase()}`}>{q.data_status ?? q.status}</span>
          <small className="muted">
            {q.product ?? q.provider}
            {!sameSource && data ? " — jiný zdroj než svíčky v grafu" : ""}
          </small>
        </p>
      )}
      <p className="cchart-foot">
        {data?.feed === "history" && (
          <>
            <MarketChip m={data.market} /> <QualityBadge q={data.quality} source={data.source} /> {data.source}
            {data.lastQuoteText && ` · ${data.lastQuoteText}`}
            {data.kindCs && ` · ${data.kindCs}`}
            {data.fetchedAt && ` · staženo ${relativeTime(data.fetchedAt)}`}
          </>
        )}
        {data?.feed === "live" && <>živý engine · {data.source} · svíčky z ticků · nové svíčky se dokreslují bez obnovení grafu</>}
        {" · "}Graf: <a href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a>
      </p>
      {data?.notes && data.notes.length > 0 && (
        <ul className="cchart-notes">
          {[...new Set(data.notes)].map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
