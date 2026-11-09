// Dark (default) / light theme: <html data-theme="dark|light">, remembered in localStorage when the browser allows it.
// Colours live only in styles/tokens.css; canvas drawings (Lightweight Charts) read them through tokenColor().
import { useEffect, useState } from "react";

export type Theme = "dark" | "light";
const KEY = "fti-theme";
const listeners = new Set<(t: Theme) => void>();

export function storedTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark"; // storage blocked (private window, policy) — the default theme
  }
}

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function syncMeta(): void {
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", getComputedStyle(document.documentElement).getPropertyValue("--bg").trim());
}

export function initTheme(): void {
  document.documentElement.dataset.theme = storedTheme();
  syncMeta();
}

export function setTheme(t: Theme): void {
  document.documentElement.dataset.theme = t;
  try {
    localStorage.setItem(KEY, t);
  } catch {
    /* storage blocked: the choice lasts until the page is reloaded */
  }
  syncMeta();
  listeners.forEach((l) => l(t));
}

export function onThemeChange(fn: (t: Theme) => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [t, setT] = useState<Theme>(currentTheme);
  useEffect(() => onThemeChange(setT), []);
  return [t, setTheme];
}

let probe: HTMLSpanElement | null = null;
let ctx: CanvasRenderingContext2D | null | undefined;

/** A colour token (e.g. "--chart-up") as rgba(), which canvas libraries understand — resolved in the current theme,
 * including color-mix() tokens. */
export function tokenColor(name: string): string {
  if (!probe) {
    probe = document.createElement("span");
    probe.style.display = "none";
    document.body.appendChild(probe);
  }
  probe.style.color = `var(${name})`;
  const css = getComputedStyle(probe).color;
  if (ctx === undefined) {
    ctx = /jsdom/i.test(navigator.userAgent) ? null : document.createElement("canvas").getContext("2d", { willReadFrequently: true });
    if (ctx) {
      ctx.canvas.width = 1;
      ctx.canvas.height = 1;
    }
  }
  if (!ctx || !css) return css;
  ctx.clearRect(0, 0, 1, 1);
  ctx.fillStyle = css;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
  return `rgba(${r}, ${g}, ${b}, ${Math.round((a / 255) * 1000) / 1000})`;
}
