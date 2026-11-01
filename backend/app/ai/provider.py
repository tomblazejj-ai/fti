"""AI provider abstraction — FREE providers only (budget 0 Kč).

  none    no language model: FTI shows the report its deterministic engine assembled
  ollama  a local open-source model (Qwen, Llama, …) served by Ollama on this PC
          (http://127.0.0.1:11434). Free; costs only the PC's own power. Structured output is
          requested as a JSON schema and validated before use; tools are FTI's own calculations.

Paid APIs are deliberately not implemented. A provider is chosen in Settings ("ai.provider").
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx

from app.data import settings_store

OLLAMA_URL = "http://127.0.0.1:11434"


class AIUnavailable(RuntimeError):
    pass


@dataclass
class AIResult:
    provider: str
    model: str
    content: dict | str
    seconds: float
    tokens_in: int = 0
    tokens_out: int = 0


def status() -> dict:
    """Which free AI is available right now (for the Settings and Data pages)."""
    cfg = settings_store.get("ai", {}) or {}
    out = {"provider": cfg.get("provider", "none"), "model": cfg.get("local_model") or None, "ollama_running": False,
           "ollama_models": [], "cost": "0 Kč — lokální model běží na tomto PC"}
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2.0)
        r.raise_for_status()
        out["ollama_running"] = True
        out["ollama_models"] = [m.get("name") for m in r.json().get("models", [])]
    except (httpx.HTTPError, ValueError):
        pass
    return out


def complete(system: str, prompt: str, schema: dict | None = None, timeout: float = 240.0) -> AIResult:
    """One request to the configured free provider. Raises AIUnavailable when there is none."""
    cfg = settings_store.get("ai", {}) or {}
    provider = cfg.get("provider", "none")
    if provider != "ollama":
        raise AIUnavailable("AI model není zapnutý — zobrazuje se rozbor sestavený z výpočtů FTI.")
    model = cfg.get("local_model") or ""
    if not model:
        raise AIUnavailable("Není vybraný lokální model (Nastavení → AI).")
    body = {"model": model, "stream": False, "options": {"temperature": 0.2},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    if schema:
        body["format"] = schema  # Ollama structured outputs: the reply must match this JSON schema
    t0 = time.monotonic()
    try:
        r = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as exc:
        raise AIUnavailable(f"Lokální model neodpověděl: {exc}") from exc
    text = (data.get("message") or {}).get("content", "")
    content: dict | str = text
    if schema:
        try:
            content = json.loads(text)
        except ValueError as exc:
            raise AIUnavailable("Model nevrátil platný JSON podle schématu.") from exc
        missing = [k for k in schema.get("required", []) if k not in content]
        if missing:
            raise AIUnavailable(f"Odpovědi modelu chybí pole: {', '.join(missing)}.")
    return AIResult("ollama", model, content, time.monotonic() - t0, data.get("prompt_eval_count", 0), data.get("eval_count", 0))
