import { useEffect, useRef, useState } from "react";
import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  LineStyle,
  TickMarkType,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type MouseEventParams,
  type SeriesType,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { sameBar, type FeedBar } from "../lib/chartFeed";
import { onThemeChange, tokenColor } from "../theme";

export type Bar = FeedBar;

/** A support / resistance level from FTI's engine, drawn as a dashed price line. */
export interface Level {
  price: number;
  kind: "support" | "resistance";
  title: string;
}

/** Bid / ask of the SAME source as the candles — two price lines (never another source's quote). */
export interface QuoteLines {
  bid: number | null;
  ask: number | null;
}

/** The bar under the crosshair (time as the chart has it; format with timeText). */
export interface Hover {
  time: Time;
  o: number;
  h: number;
  l: number;
  c: number;
}

const MONTHS = ["led", "úno", "bře", "dub", "kvě", "čvn", "čvc", "srp", "zář", "říj", "lis", "pro"];
const TZ = "Europe/Prague";
const formats = new Map<string, Intl.DateTimeFormat>();

function parts(t: number, tz = TZ): Record<string, number> {
  let f = formats.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat("en-GB", { timeZone: tz, year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric", hourCycle: "h23" });
    formats.set(tz, f);
  }
  const out: Record<string, number> = {};
  for (const p of f.formatToParts(new Date(t * 1000))) if (p.type !== "literal") out[p.type] = Number(p.value);
  return out;
}

const two = (n: number) => String(n).padStart(2, "0");

function dayOf(time: Time): { y: number; m: number; d: number } | null {
  if (typeof time === "string") {
    const [y, m, d] = time.split("-").map(Number);
    return { y, m, d };
  }
  if (typeof time === "object") return { y: time.year, m: time.month, d: time.day };
  return null;
}

/** Crosshair / legend time in Prague time (the chart's own axis would be UTC); daily candles by their trading day. */
export function timeText(time: Time, daily: boolean): string {
  const bd = dayOf(time);
  if (bd) return `${bd.d}. ${bd.m}. ${bd.y}`;
  const p = parts(time as number);
  return daily ? `${p.day}. ${p.month}. ${p.year}` : `${p.day}. ${p.month}. ${two(p.hour)}:${two(p.minute)}`;
}

function tickText(time: Time, type: TickMarkType): string {
  const bd = dayOf(time);
  if (bd) {
    if (type === TickMarkType.Year) return String(bd.y);
    if (type === TickMarkType.Month) return MONTHS[bd.m - 1];
    return `${bd.d}. ${MONTHS[bd.m - 1]}`;
  }
  const p = parts(time as number);
  if (type === TickMarkType.Year) return String(p.year);
  if (type === TickMarkType.Month) return MONTHS[p.month - 1];
  if (type === TickMarkType.DayOfMonth) return `${p.day}. ${p.month}.`;
  if (type === TickMarkType.TimeWithSeconds) return `${two(p.hour)}:${two(p.minute)}:${two(p.second)}`;
  return `${two(p.hour)}:${two(p.minute)}`;
}

/** London 8:00–16:59 London time, New York 8:00–16:59 New York time (DST handled by the time zones). */
function session(t: number): "ldn" | "ny" | "both" | null {
  const l = parts(t, "Europe/London").hour;
  const n = parts(t, "America/New_York").hour;
  const inL = l >= 8 && l < 17;
  const inN = n >= 8 && n < 17;
  return inL && inN ? "both" : inL ? "ldn" : inN ? "ny" : null;
}

interface Refs {
  main?: ISeriesApi<SeriesType>;
  kind?: "candles" | "line";
  e20?: ISeriesApi<"Line">;
  e50?: ISeriesApi<"Line">;
  sess?: ISeriesApi<"Histogram">;
  levelLines: { line: IPriceLine; kind: Level["kind"] }[];
  quoteLines: { bid?: IPriceLine; ask?: IPriceLine };
  bars: Bar[];
  useDays: boolean;
}

const fresh = (): Refs => ({ levelLines: [], quoteLines: {}, bars: [], useDays: false });

const timeOf = (b: Bar, useDays: boolean): Time => (useDays ? (b.day as string) : (b.t as UTCTimestamp));

function sessPoint(b: Bar, useDays: boolean) {
  const s = session(b.t);
  if (!s) return { time: timeOf(b, useDays) };
  const color = tokenColor(s === "ldn" ? "--chart-session-ldn" : s === "ny" ? "--chart-session-ny" : "--chart-session-both");
  return { time: timeOf(b, useDays), value: 1, color };
}

const mainPoint = (b: Bar, kind: "candles" | "line", useDays: boolean) =>
  kind === "candles" ? { time: timeOf(b, useDays), open: b.o, high: b.h, low: b.l, close: b.c } : { time: timeOf(b, useDays), value: b.c };

/** Colours come from the theme tokens every time — on creation and on every theme switch (no reload). */
function paint(c: IChartApi, r: Refs): void {
  const col = tokenColor;
  const grid = col("--chart-grid");
  const cross = { color: col("--chart-cross"), labelBackgroundColor: col("--chart-label") };
  c.applyOptions({
    layout: { background: { type: ColorType.Solid, color: col("--chart-bg") }, textColor: col("--chart-text") },
    grid: { vertLines: { color: grid }, horzLines: { color: grid } },
    crosshair: { vertLine: cross, horzLine: cross },
    rightPriceScale: { borderColor: grid },
    timeScale: { borderColor: grid },
  });
  const up = col("--chart-up");
  const down = col("--chart-down");
  if (r.main && r.kind === "candles") {
    r.main.applyOptions({ upColor: up, downColor: down, wickUpColor: up, wickDownColor: down, borderVisible: false });
  } else if (r.main) {
    r.main.applyOptions({ lineColor: col("--chart-line"), topColor: col("--chart-area-top"), bottomColor: col("--chart-area-bottom") });
  }
  r.e20?.applyOptions({ color: col("--chart-ema20") });
  r.e50?.applyOptions({ color: col("--chart-ema50") });
  for (const l of r.levelLines) l.line.applyOptions({ color: l.kind === "support" ? up : down });
  r.quoteLines.bid?.applyOptions({ color: col("--chart-bid") });
  r.quoteLines.ask?.applyOptions({ color: col("--chart-ask") });
  if (r.sess) r.sess.setData(r.bars.map((b) => sessPoint(b, r.useDays)));
}

/** TradingView Lightweight Charts™ over FTI's bars. It computes nothing and does not know the data source:
 * a new bar or a change of the forming one goes through series.update(); the whole series is set again only when the
 * series itself changes (another instrument, timeframe, source or chart type). Zoom: mouse wheel / pinch; move: drag
 * the chart (also up and down) or the price axis. */
export function LwChart({
  bars,
  kind,
  digits,
  daily,
  ema = false,
  levels = [],
  sessions = false,
  quote = null,
  label,
  onHover,
}: {
  bars: Bar[];
  kind: "candles" | "line";
  digits: number;
  daily: boolean;
  ema?: boolean;
  levels?: Level[];
  sessions?: boolean;
  quote?: QuoteLines | null;
  label: string;
  onHover?: (h: Hover | null) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const refs = useRef<Refs>(fresh());
  const hoverCb = useRef(onHover);
  hoverCb.current = onHover;
  const dec = Math.max(0, Math.min(digits, 5));
  const [built, setBuilt] = useState(0);

  // the chart itself: created once, recoloured on every theme switch
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const c = createChart(el, {
      autoSize: true,
      layout: { attributionLogo: true, fontFamily: getComputedStyle(el).fontFamily, fontSize: 11 },
      rightPriceScale: { borderVisible: true, scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderVisible: true, rightOffset: 4 },
      localization: { locale: "cs-CZ" },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: { time: true, price: true } },
    });
    chart.current = c;
    const onMove = (p: MouseEventParams) => {
      const r = refs.current;
      const d = r.main && p.time !== undefined ? (p.seriesData.get(r.main) as Record<string, number> | undefined) : undefined;
      if (!d || p.time === undefined) {
        hoverCb.current?.(null);
        return;
      }
      const v = (k: string) => ("open" in d ? d[k] : d.value);
      hoverCb.current?.({ time: p.time, o: v("open"), h: v("high"), l: v("low"), c: v("close") });
    };
    c.subscribeCrosshairMove(onMove);
    const off = onThemeChange(() => {
      if (chart.current) paint(chart.current, refs.current);
    });
    return () => {
      off();
      c.unsubscribeCrosshairMove(onMove);
      c.remove();
      chart.current = null;
      refs.current = fresh();
    };
  }, []);

  // the series: rebuilt when the chart type, the extra lines, the time axis or the decimals change
  useEffect(() => {
    const c = chart.current;
    if (!c) return;
    const old = refs.current;
    for (const s of [old.sess, old.main, old.e20, old.e50]) if (s) c.removeSeries(s);
    const r = fresh();
    refs.current = r;
    c.applyOptions({
      localization: {
        locale: "cs-CZ",
        priceFormatter: (p: number) => p.toLocaleString("cs-CZ", { minimumFractionDigits: dec, maximumFractionDigits: dec }),
        timeFormatter: (t: Time) => timeText(t, daily),
      },
      timeScale: { timeVisible: !daily, secondsVisible: false, tickMarkFormatter: (t: Time, type: TickMarkType) => tickText(t, type) },
    });
    if (sessions && !daily) {
      r.sess = c.addSeries(HistogramSeries, { priceScaleId: "sess", priceLineVisible: false, lastValueVisible: false, base: 0 });
      c.priceScale("sess").applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false });
    }
    const priceFormat = { type: "price" as const, precision: dec, minMove: 1 / 10 ** dec };
    r.main = kind === "candles" ? c.addSeries(CandlestickSeries, { priceFormat }) : c.addSeries(AreaSeries, { priceFormat, lineWidth: 2 });
    r.kind = kind;
    if (ema) {
      const opts = { lineWidth: 1 as const, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, priceFormat };
      r.e20 = c.addSeries(LineSeries, opts);
      r.e50 = c.addSeries(LineSeries, opts);
    }
    setBuilt((n) => n + 1);
  }, [kind, ema, sessions, daily, dec]);

  // the data: the whole series when it is new, otherwise only the bars that changed (series.update)
  useEffect(() => {
    const c = chart.current;
    const r = refs.current;
    if (!c || !r.main || !built) return;
    const useDays = daily && bars.length > 0 && bars.every((b, i) => b.day && (i === 0 || b.day > (bars[i - 1].day as string)));
    const prev = r.bars;
    const incremental =
      prev.length > 0 && bars.length >= prev.length && bars.length - prev.length <= 5 && r.useDays === useDays &&
      bars[0].t === prev[0].t && prev.slice(0, -1).every((b, i) => sameBar(b, bars[i]));
    const k = r.kind ?? kind;
    if (incremental) {
      for (let i = prev.length - 1; i < bars.length; i += 1) {
        const b = bars[i];
        if (i < prev.length && sameBar(b, prev[i])) continue;
        r.main.update(mainPoint(b, k, useDays));
        if (r.e20 && b.e20 != null) r.e20.update({ time: timeOf(b, useDays), value: b.e20 });
        if (r.e50 && b.e50 != null) r.e50.update({ time: timeOf(b, useDays), value: b.e50 });
        r.sess?.update(sessPoint(b, useDays));
      }
      r.bars = bars;
      return;
    }
    r.useDays = useDays;
    r.bars = bars;
    r.main.setData(bars.map((b) => mainPoint(b, k, useDays)));
    r.e20?.setData(bars.filter((b) => b.e20 != null).map((b) => ({ time: timeOf(b, useDays), value: b.e20 as number })));
    r.e50?.setData(bars.filter((b) => b.e50 != null).map((b) => ({ time: timeOf(b, useDays), value: b.e50 as number })));
    paint(c, r);
    const n = bars.length;
    if (n > 160) c.timeScale().setVisibleLogicalRange({ from: n - 160, to: n + 3 });
    else c.timeScale().fitContent();
    // `kind` is read through refs; a new kind rebuilds the series (built changes)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, built, daily]);

  // support / resistance lines
  useEffect(() => {
    const r = refs.current;
    if (!r.main || !built) return;
    for (const l of r.levelLines) r.main.removePriceLine(l.line);
    const main = r.main;
    r.levelLines = levels.map((l) => ({
      kind: l.kind,
      line: main.createPriceLine({ price: l.price, title: l.title, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true }),
    }));
    if (chart.current) paint(chart.current, r);
  }, [levels, built]);

  // bid / ask of the same source as the candles
  const bid = quote?.bid ?? null;
  const ask = quote?.ask ?? null;
  useEffect(() => {
    const r = refs.current;
    if (!r.main || !built) return;
    const want = { bid, ask };
    for (const side of ["bid", "ask"] as const) {
      const price = want[side];
      const line = r.quoteLines[side];
      if (price === null) {
        if (line) r.main.removePriceLine(line);
        r.quoteLines[side] = undefined;
      } else if (line) {
        line.applyOptions({ price });
      } else {
        r.quoteLines[side] = r.main.createPriceLine({
          price, title: side === "bid" ? "Bid" : "Ask", lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true,
          color: tokenColor(side === "bid" ? "--chart-bid" : "--chart-ask"),
        });
      }
    }
  }, [bid, ask, built]);

  return <div ref={box} className="lwc" role="img" aria-label={label} />;
}
