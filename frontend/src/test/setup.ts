import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

window.scrollTo = () => {}; // jsdom doesn't implement scrolling

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.location.hash = "";
});
