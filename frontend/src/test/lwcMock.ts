// Stand-in for lightweight-charts in tests: jsdom has no canvas. Records what the app asks the chart to do, so tests
// can check e.g. that a live candle goes through series.update() and that a theme switch recolours the chart.
import { vi } from "vitest";

export const calls = {
  setData: 0,
  update: 0,
  chartOptions: [] as Record<string, unknown>[],
  seriesOptions: [] as Record<string, unknown>[],
  priceLines: [] as Record<string, unknown>[],
  reset() {
    this.setData = 0;
    this.update = 0;
    this.chartOptions = [];
    this.seriesOptions = [];
    this.priceLines = [];
  },
};

function series() {
  return {
    setData: vi.fn(() => {
      calls.setData += 1;
    }),
    update: vi.fn(() => {
      calls.update += 1;
    }),
    applyOptions: vi.fn((o: Record<string, unknown>) => {
      calls.seriesOptions.push(o);
    }),
    createPriceLine: vi.fn((o: Record<string, unknown>) => {
      calls.priceLines.push(o);
      return { applyOptions: vi.fn(), options: () => o };
    }),
    removePriceLine: vi.fn(),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
  };
}

export const createChart = vi.fn(() => ({
  addSeries: vi.fn(() => series()),
  removeSeries: vi.fn(),
  applyOptions: vi.fn((o: Record<string, unknown>) => {
    calls.chartOptions.push(o);
  }),
  priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
  timeScale: vi.fn(() => ({ fitContent: vi.fn(), setVisibleLogicalRange: vi.fn(), scrollToRealTime: vi.fn() })),
  subscribeCrosshairMove: vi.fn(),
  unsubscribeCrosshairMove: vi.fn(),
  remove: vi.fn(),
}));

export const CandlestickSeries = { type: "Candlestick" };
export const AreaSeries = { type: "Area" };
export const LineSeries = { type: "Line" };
export const HistogramSeries = { type: "Histogram" };
export const ColorType = { Solid: "solid" };
export const LineStyle = { Solid: 0, Dotted: 1, Dashed: 2, LargeDashed: 3, SparseDotted: 4 };
export const TickMarkType = { Year: 0, Month: 1, DayOfMonth: 2, Time: 3, TimeWithSeconds: 4 };
export const CrosshairMode = { Normal: 0, Magnet: 1, Hidden: 2 };
