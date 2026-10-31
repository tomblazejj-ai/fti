/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
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
