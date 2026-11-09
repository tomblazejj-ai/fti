import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

window.scrollTo = () => {}; // jsdom doesn't implement scrolling

// jsdom has no canvas: the chart library is replaced by a recorder (src/test/lwcMock.ts)
vi.mock("lightweight-charts", () => import("./lwcMock"));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.location.hash = "";
  try {
    localStorage.clear();
  } catch {
    /* storage unavailable */
  }
  document.documentElement.removeAttribute("data-theme");
});
