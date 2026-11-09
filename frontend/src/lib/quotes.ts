// The top bar's six quotes, put together from what FTI already has — nothing is computed or invented here.
import type { GoldAnalysis, LiveQuote, LiveSnapshot, MarketRegime, Quote, TickersResponse } from "./types";

/** LIVE = live engine, fresh tick (≤ 15 s); DELAYED = older or polled data; CLOSED = market closed by its schedule;
 * N/A = FTI has no price for this instrument right now. */
export type FeedState = "LIVE" | "DELAYED" | "CLOSED" | "N/A";

export interface TopQuote {
  key: string;
  label: string;
  price: number | null;
  digits: number;
  change_pct: number | null;
  state: FeedState;
  /** where the number comes from, when, and how — shown as the tooltip */
  source: string;
  time: string | null;
  method: string;
}

function fromLive(key: string, q: LiveQuote): TopQuote {
  const open = !q.market_status || q.market_status === "OPEN";
  const ds = q.data_status ?? q.status;
  const state: FeedState = !open ? "CLOSED" : ds === "LIVE" ? "LIVE" : ds === "UNAVAILABLE" ? "N/A" : "DELAYED";
  return {
    key,
    label: key,
    digits: q.digits,
    state,
    price: state === "N/A" ? null : q.mid ?? q.bid ?? null,
    change_pct: q.change_pct ?? null,
    source: q.product ?? q.provider ?? "živý engine FTI",
    time: q.quote_time ?? q.received_at ?? null,
    method:
      `${q.price_type === "mid" ? "střed bid/ask" : q.price_type ?? "cena"} ze živého streamu; změna proti závěru ${q.prev_close_day ?? "předchozího dne"}` +
      (q.status_cs ? ` · ${q.status_cs}` : ""),
  };
}

function fromTicker(key: string, q: Quote): TopQuote {
  const closed = q.market && q.market.state !== "OPEN";
  return {
    key,
    label: key,
    digits: q.digits,
    price: q.price,
    change_pct: q.change_pct,
    state: closed ? "CLOSED" : "DELAYED",
    source: q.source + (q.kind_cs ? ` · ${q.kind_cs}` : ""),
    time: q.as_of ?? null,
    method: q.live ? "kotace načítaná každých 60 s (ne tick po ticku)" : `denní hodnota${q.quote_time_cs ? ` · ${q.quote_time_cs}` : ""}`,
  };
}

function missing(key: string, label: string, digits: number, why: string): TopQuote {
  return { key, label, digits, price: null, change_pct: null, state: "N/A", source: why, time: null, method: "—" };
}

export function topQuotes(
  snap: LiveSnapshot | null,
  tickers: TickersResponse | undefined,
  gold: GoldAnalysis | undefined,
  regime: MarketRegime | undefined,
): TopQuote[] {
  const live = (code: string) => snap?.instruments.find((q) => q.code === code);
  const tick = (sym: string) => [...(tickers?.live ?? []), ...(tickers?.daily ?? [])].find((q) => q.symbol === sym);
  const out: TopQuote[] = [];

  const pairs: [string, number][] = [["XAUUSD", 2], ["EURUSD", 5]];
  for (const [code, digits] of pairs) {
    const lq = live(code);
    const tq = tick(code);
    if (lq && (lq.mid ?? lq.bid) != null) out.push(fromLive(code, lq));
    else if (tq) out.push(fromTicker(code, tq));
    else out.push(missing(code, code, digits, "FTI pro tento instrument teď nemá cenu."));
  }
  // broker CFDs: only the live engine has them — the cash index (FRED, daily) is a different number and is not put in their place
  const cfds: [string, string][] = [["US500", "US500.CFD"], ["NAS100", "US100.CFD"]];
  for (const [label, code] of cfds) {
    const lq = live(code);
    if (lq && (lq.mid ?? lq.bid) != null) out.push(fromLive(label, lq));
    else {
      out.push(missing(label, label, 1,
        `Cenu CFD ${label} má jen živý engine v aplikaci na PC. Hodnota indexu (FRED, denní) je jiné číslo, proto se sem nedosazuje.`));
    }
  }

  const dxy = gold?.dxy;
  const dxyTime = gold?.sources_status?.find((s) => s.key === "dxy")?.as_of ?? null;
  if (dxy && dxy.price != null) {
    out.push({
      key: "DXY",
      label: "DXY (syn.)",
      price: dxy.price,
      digits: 2,
      change_pct: null,
      state: tickers?.market && !tickers.market.open ? "CLOSED" : "DELAYED",
      source: dxy.source,
      time: dxyTime,
      method: `syntetický přepočet podle vzorce ICE, ne oficiální kotace${dxy.verified ? ` · ${dxy.verified}` : ""}`,
    });
  } else {
    out.push(missing("DXY", "DXY (syn.)", 2, "Přepočet DXY je jen v aplikaci na PC (analýza zlata)."));
  }

  const vix = regime?.dimensions.find((d) => d.key === "riziko")?.inputs.find((i) => i.name === "VIX");
  if (vix && typeof vix.value === "number") {
    out.push({
      key: "VIX",
      label: "VIX",
      price: vix.value,
      digits: 2,
      change_pct: null,
      state: "DELAYED",
      source: vix.source ?? "FRED VIXCLS",
      time: vix.as_of ?? null,
      method: "denní závěr indexu VIX (CBOE přes FRED), ne průběžná hodnota",
    });
  } else {
    out.push(missing("VIX", "VIX", 2, "VIX FTI teď nemá."));
  }
  return out;
}
