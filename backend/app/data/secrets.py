"""API keys and other secrets — only in backend/.env on this PC (git-ignored), or in the
environment (GitHub Actions secrets for the phone build). Never sent to the frontend, never logged.

The frontend can only ask whether a key is set (`status()`) and replace it (`set_key()`).
"""

from __future__ import annotations

import os
import re
import threading

from app.config import BACKEND_DIR

ENV_FILE = BACKEND_DIR / ".env"
KEYS = {
    "FRED_API_KEY": "FRED (oficiální API, klíč zdarma po registraci na fred.stlouisfed.org)",
    "OANDA_API_TOKEN": "OANDA v20 (token zdarma k demo účtu, jen tržní data)",
    "GROQ_API_KEY": "Groq AI (jen bezplatný tarif Free, klíč z console.groq.com)",
    "FTI_SYNC_TOKEN": "Token synchronizace s vlastním cloudem FTI (Cloudflare Worker)",
    "TICKBASE_API_KEY": "TickBase (kontrola a záloha ceny zlata; klíč zdarma po registraci na thetickbase.com)",
    # Purple Trading cTrader Open API — live quotes of the user's broker (read-only scope "accounts": no trading possible)
    "CTRADER_CLIENT_ID": "cTrader Open API — Client ID aplikace (openapi.ctrader.com → Applications → Credentials)",
    "CTRADER_CLIENT_SECRET": "cTrader Open API — Secret aplikace (tamtéž)",
    "CTRADER_ACCESS_TOKEN": "cTrader Open API — Access token (Applications → Playground, rozsah „accounts“ = jen čtení)",
    "CTRADER_REFRESH_TOKEN": "cTrader Open API — Refresh token (Playground; FTI s ním token sám obnoví)",
    # Capital.com Open API (demo) — the brief's primary live source. The identifier is the account's login e-mail: it is
    # stored only here and sent only to Capital.com's API to open the session (the user's consent, 9. 11. 2026)
    "CAPITAL_API_KEY": "Capital.com — API klíč (demo účet → Nastavení → API integrace)",
    "CAPITAL_IDENTIFIER": "Capital.com — přihlašovací e-mail účtu (posílá se jen na API Capital.com)",
    "CAPITAL_API_PASSWORD": "Capital.com — vlastní heslo k API klíči (ne heslo účtu)",
}
_lock = threading.Lock()
_VALID = re.compile(r"^[A-Za-z0-9_\-\.]{8,200}$")
# keys whose shape is known: a wrong paste is caught before it is saved
_FORMATS = {"GROQ_API_KEY": (re.compile(r"^gsk_[A-Za-z0-9]{20,200}$"), "Klíč Groq začíná „gsk_“ a nemá mezery ani jiné znaky."),
            "FTI_SYNC_TOKEN": (re.compile(r"^[A-Za-z0-9_\-]{32,128}$"), "Token má 32–128 znaků (písmena, číslice, - a _)."),
            "TICKBASE_API_KEY": (re.compile(r"^tb_(live|test)_[A-Za-z0-9_\-]{8,200}$"),
                                 "Klíč TickBase začíná „tb_live_“ (nebo „tb_test_“) a nemá mezery.")}
# not even the last characters are shown for these
_NO_HINT = {"GROQ_API_KEY", "FTI_SYNC_TOKEN", "TICKBASE_API_KEY", "CTRADER_CLIENT_SECRET", "CTRADER_ACCESS_TOKEN",
            "CTRADER_REFRESH_TOKEN", "CAPITAL_API_KEY", "CAPITAL_IDENTIFIER", "CAPITAL_API_PASSWORD"}
# values that are not plain keys: their own format instead of the general one
_OWN_FORMAT = {"CAPITAL_IDENTIFIER": (re.compile(r"^[^\s@\"'#]+@[^\s@\"'#]+\.[^\s@\"'#]+$"),
                                      "Zadejte přihlašovací e-mail účtu Capital.com (bez mezer)."),
               "CAPITAL_API_PASSWORD": (re.compile(r"^[^\s\"'#]{6,128}$"),
                                        "Heslo k API klíči: 6–128 znaků bez mezer, uvozovek a znaku #.")}


def _read_file() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def get(name: str) -> str:
    """The key from the environment first (GitHub secrets), then backend/.env. Empty when unset."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    return _read_file().get(name, "")


def status() -> list[dict]:
    """Which keys are set — never the key itself, at most its last 4 characters (none for AI keys)."""
    out = []
    for name, label in KEYS.items():
        v = get(name)
        hint = f"…{v[-4:]}" if len(v) >= 8 and name not in _NO_HINT else None
        out.append({"name": name, "label": label, "set": bool(v), "hint": hint})
    return out


def set_key(name: str, value: str) -> None:
    """Write (or remove with an empty value) one key in backend/.env. Validates the format."""
    if name not in KEYS:
        raise ValueError("Neznámý klíč.")
    value = value.strip()
    if value and name in _OWN_FORMAT:
        if not _OWN_FORMAT[name][0].match(value):
            raise ValueError(_OWN_FORMAT[name][1])
    elif value and not _VALID.match(value):
        raise ValueError("Klíč má neplatný formát (jen písmena, číslice, -, _ a . bez mezer).")
    if value and name in _FORMATS and not _FORMATS[name][0].match(value):
        raise ValueError(_FORMATS[name][1])
    with _lock:
        lines = []
        try:
            lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        except OSError:
            pass
        lines = [ln for ln in lines if not ln.strip().startswith(f"{name}=")]
        if value:
            lines.append(f"{name}={value}")
        ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
