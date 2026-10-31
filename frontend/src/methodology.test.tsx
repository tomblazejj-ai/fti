import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ScoreOverview } from "./components/Tra";
import { countdown, newsLock } from "./lib/newsLock";
import type { CalendarEvent, EconCalendar, Metodika as MetodikaData, TraPack } from "./lib/types";
import { CalendarTable } from "./pages/detail/CalendarTable";
import { Metodika } from "./pages/Metodika";

afterEach(() => {
  vi.restoreAllMocks();
});

function ev(overrides: Partial<CalendarEvent>): CalendarEvent {
  return {
    key: "cpi", date: "2026-10-14", time: "14:30", datetime: "2026-10-14T12:30:00+00:00", name: "Inflace CPI (USA)",
    original: "Consumer Price Index", importance: 3, impact: "Vyšší inflace → zlato dolů.", previous: null, forecast: null,
    source: "FRED", past: false, up_if: "inflace zpomalí", down_if: "inflace bude vyšší", ...overrides,
  };
}

describe("2-hour news rule", () => {
  const cpi = ev({});
  it("locks new entries within 2 hours before a red release", () => {
    const l = newsLock([cpi], new Date("2026-10-14T11:00:00Z"));
    expect(l.state).toBe("lock");
    expect(l.minutes).toBe(90);
  });
  it("asks to wait for confirmation in the hour after it", () => {
    expect(newsLock([cpi], new Date("2026-10-14T12:50:00Z")).state).toBe("after");
  });
  it("is clear otherwise and ignores lower-impact releases", () => {
    const l = newsLock([cpi, ev({ importance: 2, datetime: "2026-10-14T09:30:00+00:00" })], new Date("2026-10-14T08:45:00Z"));
    expect(l.state).toBe("clear");
    expect(l.next?.name).toBe("Inflace CPI (USA)");
  });
  it("formats countdowns in Czech", () => {
    expect(countdown(25)).toBe("25 min");
    expect(countdown(85)).toBe("1 h 25 min");
    expect(countdown(3 * 1440)).toBe("3 dny");
  });
});

const PACK: TraPack = {
  total: -6, max: 25, missing: [], word: "Medvědí", strength: "", arrow: "down",
  components: [
    { key: "rates", label: "Úrokové sazby", score: -2, max: 2, reason: "2letý výnos 4,84 % vs. sazba Fedu 3,88 % → trh čeká ZVYŠOVÁNÍ sazeb.",
      inputs: [{ name: "2letý výnos USA", value: "4,84 %", as_of: "2026-10-05" }], usd_score: 2, proxy: "Očekávání z 2letého výnosu." },
    { key: "seasonality", label: "Sezónnost", score: 0, max: 2, reason: "Říjen bez sklonu.", inputs: [], usd_score: null, proxy: null },
  ],
};

describe("Score Overview (Trading Analyzer style)", () => {
  it("shows every category with its arrow chip and the final score; a click tells why", () => {
    render(<ScoreOverview pack={PACK} tag="XAU/USD" subject="zlato" />);
    const panel = screen.getByRole("heading", { name: /Score Overview/ }).closest("section")!;
    expect(within(panel).getByText("Final Score")).toBeInTheDocument();
    expect(within(panel).getByText("−6")).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: /Úrokové sazby/ }));
    expect(within(panel).getByText(/trh čeká ZVYŠOVÁNÍ sazeb/)).toBeInTheDocument();
    expect(within(panel).getByText(/Náhrada placených dat/)).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: "Jak skóre funguje" }));
    expect(within(panel).getByText(/U zlata mají opačné/)).toBeInTheDocument();
  });
});

describe("calendar event detail", () => {
  it("explains the release and lists its last values", () => {
    const calendar: EconCalendar = {
      events: [ev({
        detail: {
          freq: "Měsíčně, obvykle mezi 10. a 15. dnem.", why: "Inflace rozhoduje o sazbách.", usd: "Vyšší inflace → silnější dolar.",
          history_label: "Jádrová inflace CPI", history_unit: "% r/r",
          history: [{ period: "7/2026", value: 2.5, text: "2,5 % r/r" }, { period: "8/2026", value: 2.4, text: "2,4 % r/r" }],
          series: "CPILFESL", series_url: "https://fred.stlouisfed.org/series/CPILFESL", link: "https://www.bls.gov/cpi/",
        },
      })],
      next_high: null, timezone: "Europe/Prague", notes: ["pozn."], sources: [],
      rules: { lock_hours: 2, confirm_minutes: 60 },
    };
    render(<CalendarTable calendar={calendar} full />);
    expect(screen.getByRole("group", { name: "Filtr podle dopadu" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Inflace CPI (USA)" }));
    expect(screen.getByText("Proč to trh sleduje")).toBeInTheDocument();
    expect(screen.getByText("2,4 % r/r")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Data na FRED/ })).toHaveAttribute("href", "https://fred.stlouisfed.org/series/CPILFESL");
  });
});

describe("Metodika page", () => {
  it("lists the course materials and flags a new file as not worked in yet", async () => {
    const data: MetodikaData = {
      course: "Funded Mind", folder: "C:/Users/x/Desktop/Fundament Funded mind", folder_exists: true, checked_at: "2026-10-06T20:00:00+00:00",
      counts: { new: 1, changed: 0, done: 1 }, missing: [], principles: ["Skóre je makro kompas, momentum je jeho směr."],
      how_to: "Nové soubory stačí uložit do složky.",
      files: [
        { file: "nove.txt", status: "new", status_text: "nový — zatím nezapracováno", title: null, author: null, summary: null, used_in: [],
          size_kb: 1, modified: "2026-10-06T19:00:00+00:00", preview: "Moje poznámka k NFP" },
        { file: "News.pdf", status: "done", status_text: "zapracováno", title: "Fundamentální zprávy", author: "Daniel Valchář",
          summary: "Pravidlo 2 hodin.", used_in: ["Kalendář → Pravidlo 2 hodin"], size_kb: 814, modified: "2026-10-06T19:56:00+00:00", preview: null },
      ],
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => Response.json(data));
    render(<Metodika />);
    expect(await screen.findByText("Podle čeho aplikace hodnotí trh")).toBeInTheDocument();
    expect(screen.getByText("nový — zatím nezapracováno")).toBeInTheDocument();
    expect(screen.getByText("Moje poznámka k NFP")).toBeInTheDocument();
    expect(screen.getByText("Kalendář → Pravidlo 2 hodin")).toBeInTheDocument();
    expect(screen.getByText(/čeká na zapracování/)).toBeInTheDocument();
  });
});
