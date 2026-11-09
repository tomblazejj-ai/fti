import { useMemo, useState } from "react";
import { CandleChart } from "../components/CandleChart";
import { Pills } from "../components/ui";
import { useGoldAnalysis } from "../hooks/useMarkets";
import { STATIC } from "../lib/api";
import { HISTORY_CODES } from "../lib/chartFeed";
import type { Tf } from "../lib/types";
import { goldLevels } from "./Dashboard";

const ALL_CODES = ["XAUUSD", "EURUSD", "US500.CFD", "US100.CFD", "GBPUSD", "USDJPY", "USOIL"];
const CODES = STATIC ? ALL_CODES.filter((c) => HISTORY_CODES.has(c)) : ALL_CODES;
const DIGITS: Record<string, number> = { XAUUSD: 2, EURUSD: 5, GBPUSD: 5, USDJPY: 3, USOIL: 2, "US500.CFD": 1, "US100.CFD": 1 };
const LINE_ONLY = new Set(["USOIL"]);
const KEY = "fti-charts";

interface Panel {
  code: string;
  tf: Tf;
}
interface Layout {
  n: 1 | 2 | 4;
  panels: Panel[];
}

const DEFAULT: Layout = {
  n: 2,
  panels: [
    { code: "XAUUSD", tf: "H1" },
    { code: "XAUUSD", tf: "D1" },
    { code: "EURUSD", tf: "H1" },
    { code: STATIC ? "USDJPY" : "US500.CFD", tf: "H1" },
  ],
};

function stored(): Layout {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "null") as Layout | null;
    if (v && [1, 2, 4].includes(v.n) && Array.isArray(v.panels) && v.panels.length === 4 && v.panels.every((p) => CODES.includes(p.code))) return v;
  } catch {
    /* storage blocked or old format — the default layout */
  }
  return DEFAULT;
}

/** Several charts side by side: each with its own instrument and timeframe (remembered in this browser for now;
 * on the server once the app has a login). */
export function ChartsPage() {
  const [layout, setLayout] = useState<Layout>(stored);
  const an = useGoldAnalysis();
  const levels = useMemo(() => goldLevels(an.data), [an.data]);
  const save = (l: Layout) => {
    setLayout(l);
    try {
      localStorage.setItem(KEY, JSON.stringify(l));
    } catch {
      /* storage blocked — the layout lasts until reload */
    }
  };
  const update = (i: number, p: Partial<Panel>) => save({ ...layout, panels: layout.panels.map((x, k) => (k === i ? { ...x, ...p } : x)) });
  return (
    <main className="page page-wide">
      <header className="page-head charts-head">
        <div>
          <h1>Grafy</h1>
          <p>Každý graf má vlastní instrument a rámec M1–MN1. Zdroj svíček je vidět v grafu; dva zdroje se do jedné řady nemíchají.</p>
        </div>
        <Pills
          label="Počet grafů"
          options={[
            { value: "1", label: "1", title: "Jeden graf" },
            { value: "2", label: "2", title: "Dva grafy vedle sebe" },
            { value: "4", label: "4", title: "Čtyři grafy" },
          ]}
          value={String(layout.n) as "1" | "2" | "4"}
          onChange={(v) => save({ ...layout, n: Number(v) as Layout["n"] })}
        />
      </header>
      <div className={`chart-grid n-${layout.n}`}>
        {layout.panels.slice(0, layout.n).map((p, i) => (
          <section key={`${i}-${p.code}`} className="card chart-panel" aria-label={`Graf ${i + 1}`}>
            <CandleChart code={p.code} digits={DIGITS[p.code] ?? 2} initialTf={p.tf} lineOnly={LINE_ONLY.has(p.code)}
                         levels={p.code === "XAUUSD" ? levels : undefined} codes={CODES} onCode={(code) => update(i, { code })}
                         onTf={(tf) => update(i, { tf })} />
          </section>
        ))}
      </div>
    </main>
  );
}
