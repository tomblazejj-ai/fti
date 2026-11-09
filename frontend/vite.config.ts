/// <reference types="vitest/config" />
import { execSync } from "node:child_process";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

function commit(): string {
  const env = process.env.FTI_VERSION || process.env.GITHUB_SHA;
  if (env) return env.slice(0, 7);
  try {
    return execSync("git rev-parse --short HEAD").toString().trim();
  } catch {
    return "dev";
  }
}

export default defineConfig({
  plugins: [react()],
  // the version shown in the footer — the same everywhere the same build runs (web, PWA on PC and phone)
  define: { __FTI_COMMIT__: JSON.stringify(commit()), __FTI_BUILT__: JSON.stringify(new Date().toISOString()) },
  build: {
    // the chart library in its own file: the app's code stays small and the charts are cached separately
    rollupOptions: { output: { manualChunks: { charts: ["lightweight-charts"] } } },
  },
  // relative asset paths: the same build works from FastAPI ("/") and from a sub-folder on static hosting
  base: "./",
  server: {
    port: 5173,
    // In dev, the FastAPI backend runs separately on :8000.
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
