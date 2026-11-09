import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// fonts bundled with the app (no font CDN): Inter for the interface, JetBrains Mono for numbers; latin + latin-ext for Czech
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-ext-400.css";
import "@fontsource/inter/latin-500.css";
import "@fontsource/inter/latin-ext-500.css";
import "@fontsource/inter/latin-600.css";
import "@fontsource/inter/latin-ext-600.css";
import "@fontsource/inter/latin-700.css";
import "@fontsource/inter/latin-ext-700.css";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-ext-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";
import "@fontsource/jetbrains-mono/latin-ext-500.css";
import { App } from "./App";
import { STATIC } from "./lib/api";
import { initTheme } from "./theme";
import "./styles/tokens.css";
import "./app.css";
import "./styles/shell.css";

initTheme();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// The phone version (static build) installs as an app and keeps working offline.
if (STATIC && "serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./sw.js").catch(() => undefined);
  });
}
