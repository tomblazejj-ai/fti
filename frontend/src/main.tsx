import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { STATIC } from "./lib/api";
import "./app.css";

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
