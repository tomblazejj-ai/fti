"""English → Czech headline translation, fully local and free.

Uses Argos Translate (open-source, offline, MIT) with its en→cs model — no
API key, nothing leaves the computer. Raw machine translation of market
jargon is clumsy ("Dollar steadies" → "Dolarové parníky"), so headlines are
first rewritten into plainer English with a small finance glossary, and a
few systematic errors are fixed afterwards. The UI always labels the result
as a machine translation and links the original.

If the model is not installed or fails, translate() returns None and the
UI shows the original headline — never an invented one.
"""

from __future__ import annotations

import html
import logging
import re
import threading

logger = logging.getLogger(__name__)

# Plainer English first: idioms and headline-ese the model mistranslates.
PRE = [
    (r"\bXAU/USD\b", "gold"),
    (r"\bXAUUSD\b", "gold"),
    (r"\bXAG/USD\b", "silver"),
    (r"\bGold Price Forecast:\s*", "Outlook for the price of gold: "),
    (r"\$(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?", lambda m: m.group(1).replace(",", "") + (f".{m.group(2)}" if m.group(2) else "") + " dollars"),
    (r"\bbears eye\b", "sellers target"),
    (r"\bbulls eye\b", "buyers target"),
    (r"\bbears\b", "sellers"),
    (r"\bbulls\b", "buyers"),
    (r"\bsteadies\b", "is stable"),
    (r"\bsteady\b", "stable"),
    (r"\bbets build\b", "expectations grow"),
    (r"\bbets\b", "expectations"),
    (r"\brate[- ]hikes?\b", "interest rate increase"),
    (r"\bhikes?\b", "interest rate increase"),
    (r"\brate[- ]cut\b", "interest rate cut"),
    (r"\bhawkish\b", "in favour of higher interest rates"),
    (r"\bdovish\b", "in favour of lower interest rates"),
    (r"\btumbles?\b", "falls sharply"),
    (r"\bslides?\b", "falls"),
    (r"\bslumps?\b", "falls sharply"),
    (r"\bsoars?\b", "rises sharply"),
    (r"\bjumps?\b", "rises sharply"),
    (r"\brall(y|ies)\b", "rises"),
    (r"\bedges? (higher|up)\b", "rises slightly"),
    (r"\bedges? (lower|down)\b", "falls slightly"),
    (r"\beyes?\b", "watches"),
    (r"\bhits\b", "reaches"),
    (r"\bclimbs?\b", "rises"),
    (r"\bFed\b", "Federal Reserve"),
    (r"\bUS\b", "American"),
    (r"\bpayrolls\b", "new jobs"),
    (r"\bNFP\b", "new jobs report"),
    (r"\bCPI\b", "consumer prices"),
    (r"\bPCE\b", "PCE inflation"),
    (r"\bETFs?\b", "funds"),
    (r"\bstalemate\b", "deadlock"),
]

# Systematic fixes of the Czech output.
POST = [
    (r"\b[Aa]merického Federálního rezervního systému\b", "Fedu"),
    (r"\bFederálního rezervního systému\b", "Fedu"),
    (r"\bFederálním rezervním systémem\b", "Fedem"),
    (r"\bFederální rezervní systém\b", "Fed"),
    (r"\bFederální rezervní\b", "Fed"),
    (r"\bFederální rezervy\b", "Fedu"),
    (r"\bFederální rezerva\b", "Fed"),
    (r"\bAmerický Fed\b", "Fed"),
    (r"\bskutečné výnosy\b", "reálné výnosy"),
    (r"\bskutečných výnosů\b", "reálných výnosů"),
    (r"\bZlatá předpověď\b", "Výhled ceny zlata"),
    (r"\bVyhledávání ceny zlata\b", "Výhled ceny zlata"),
    (r"\bZlatá cena výhled\b", "Výhled ceny zlata"),
    (r"(\d)\.(\d{2}) dolarů", r"\1,\2 dolarů"),
    (r"(\d)\s*%", r"\1 %"),
    (r"\s+([.,;:!?])", r"\1"),
    (r"\s{2,}", " "),
]

_lock = threading.Lock()
_translator = None
_unavailable_reason: str | None = None


def _load():
    global _translator, _unavailable_reason
    if _translator is not None or _unavailable_reason is not None:
        return _translator
    try:
        import argostranslate.translate as at

        langs = {lang.code: lang for lang in at.get_installed_languages()}
        if "en" not in langs or "cs" not in langs:
            _unavailable_reason = "Model pro překlad angličtina → čeština není nainstalovaný."
            return None
        _translator = langs["en"].get_translation(langs["cs"])
        if _translator is None:
            _unavailable_reason = "Překlad angličtina → čeština není k dispozici."
    except Exception as exc:  # noqa: BLE001 — optional component
        _unavailable_reason = f"Překladač se nepodařilo načíst: {exc}"
    if _unavailable_reason:
        logger.warning(_unavailable_reason)
    return _translator


def prepare(text: str) -> str:
    text = html.unescape(text).replace(" | ", " – ").replace("|", " – ")
    for pattern, repl in PRE:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return text


def polish(text: str) -> str:
    for pattern, repl in POST:
        text = re.sub(pattern, repl, text)
    return text.strip()


def translate(text: str) -> str | None:
    with _lock:  # the model is not thread-safe; ingestion is single-threaded anyway
        tr = _load()
        if tr is None:
            return None
        try:
            return polish(tr.translate(prepare(text)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Překlad selhal: %s", exc)
            return None


def unavailable_reason() -> str | None:
    _load()
    return _unavailable_reason
