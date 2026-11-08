"""English → Czech headline translation, fully local and free.

Uses Argos Translate (open-source, offline, MIT) with its en→cs model — no
API key, nothing leaves the computer. Raw machine translation of market
jargon is clumsy ("Dollar steadies" → "Dolarové parníky"), so headlines are
first rewritten into plainer English with a small finance glossary, and a
few systematic errors are fixed afterwards. The UI always labels the result
as a machine translation and links the original.

If the model is not installed or fails, translate() returns None and the
UI shows the original headline — never an invented one.

Numbers (finding D, 2026-11-07): "Gold at $3 , 800 – 4 , 000" (GDELT re-spaces punctuation even inside
numbers) came out as "Zlato za 3 dolary, 800 - 4 000". Every translation is now checked: all numbers with
their currency, percentage and scale (thousand / million / billion …) must be the same in the original and
in the Czech text, ranges included. When the check fails, translate() returns REJECTED (""), FTI stores that
as title_cs = "" and shows the original headline labelled "překlad nespolehlivý". The original is never changed.
"""

from __future__ import annotations

import html
import logging
import re
import threading

logger = logging.getLogger(__name__)

# GDELT returns titles re-spaced around punctuation, also inside numbers: "$3 , 800", "3 . 6 %".
_SPACING = [
    (r"(\d) , (\d{3})(?!\d)", r"\1,\2"),  # thousands separator
    (r"(\d) \. (\d)", r"\1.\2"),  # decimal point
    (r"(\d) %", r"\1%"),
]


def tidy(text: str) -> str:
    """Undo GDELT's re-spacing inside numbers. Changes no digit."""
    for pattern, repl in _SPACING:
        text = re.sub(pattern, repl, text)
    return text


_SCALE_WORD = {"m": "million", "mn": "million", "b": "billion", "bn": "billion", "tn": "trillion"}


def _thousands(m: re.Match) -> str:
    value = float(m.group(1)) * 1000
    return f"{value:.0f}" if value == int(value) else f"{value:g}"


# Plainer English first: idioms and headline-ese the model mistranslates.
PRE = [
    # a dollar range keeps one unit for both ends: "$3,800–4,000" → "3800–4000 dollars"
    (r"\$(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?) ?([-–—]) ?\$?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\d,.]*\d)(?! ?(?:k|m|mn|bn|b|tn)\b)",
     lambda m: f"{m.group(1).replace(',', '')}{m.group(2)}{m.group(3).replace(',', '')} dollars"),
    (r"\$(\d+(?:\.\d+)?)k\b", lambda m: _thousands(m) + " dollars"),
    (r"\$(\d+(?:\.\d+)?) ?(m|mn|bn|b|tn)\b", lambda m: f"{m.group(1)} {_SCALE_WORD[m.group(2).lower()]} dollars"),  # "$4k" — the model dropped the k ("4 dollarsk")
    (r"\bXAU/USD\b", "gold"),
    (r"\bXAUUSD\b", "gold"),
    (r"\bXAG/USD\b", "silver"),
    (r"\bGold Price Forecast:\s*", "Outlook for the price of gold: "),
    (r"\$(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?", lambda m: m.group(1).replace(",", "") + (f".{m.group(2)}" if m.group(2) else "") + " dollars"),
    # English thousands separators would read as decimals in Czech ("165,000" → 165,0): plain digits instead
    (r"(?<![\d.,])(\d{1,3}(?:,\d{3})+)(?![\d,])", lambda m: m.group(1).replace(",", "")),
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
    (r"(\d)- (\d)", r"\1–\2"),  # "3800- 4000" → "3800–4000"
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
    text = tidy(html.unescape(text)).replace(" | ", " – ").replace("|", " – ")
    for pattern, repl in PRE:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return text


def polish(text: str) -> str:
    for pattern, repl in POST:
        text = re.sub(pattern, repl, text)
    return text.strip()


# --- number check (finding D)
REJECTED = ""  # translate() result when the translation changed a number: stored as title_cs = ""

_NUM = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")  # English: 3,800.50
_NUM_CS = re.compile(r"(?<![\d.,])(\d{1,3}(?:[ \u00a0\u202f]\d{3}(?!\d))+|\d+)(?:[.,](\d+))?")  # Czech: 3 800,50 (or 3800.50)
_BEFORE = re.compile(r"(US\$|\$|USD ?|€|EUR ?|£|GBP ?|¥|JPY ?|₹|INR ?|\bRs\.? ?)$", re.IGNORECASE)
_PERCENT = {"en": re.compile(r"^ ?(%|percent\b|per cent\b|pct\b)", re.IGNORECASE),
            "cs": re.compile(r"^ ?(%|procent\w*)", re.IGNORECASE)}
_BP = {"en": re.compile(r"^ ?(bps?\b|basis points?\b)", re.IGNORECASE),
       "cs": re.compile(r"^ ?(bps?\b|bazick\w+ bod\w*|b\. ?b\.)", re.IGNORECASE)}
_SCALE = {
    "en": [(r"k\b|thousand\b", 1e3), (r"mn\b|mln\b|m\b|million\b", 1e6), (r"bn\b|b\b|billion\b", 1e9),
           (r"tn\b|trillion\b", 1e12)],  # no bare "t": "20t" of gold are tonnes
    "cs": [(r"tis\.|tisíc\w*|k\b|thousand\b", 1e3), (r"miliard\w*|mld\.?|bn\b|billion\b", 1e9),
           (r"milion\w*|mil\.|mln\.?|mn\b|m\b|million\b", 1e6), (r"bilion\w*|bil\.|tn\b|trillion\b", 1e12)],
}
_CURRENCY = {
    "en": [(r"dollars?\b|usd\b", "USD"), (r"euros?\b(?! area)|eur\b", "EUR"), (r"pounds?\b|sterling\b|gbp\b", "GBP"),
           (r"yen\b|jpy\b", "JPY"), (r"rupees?\b|inr\b", "INR")],
    "cs": [(r"(?:americk\w+ )?(?:dolar\w*|dollar\w*|usd\b)", "USD"), (r"eur(?:o|a|u|em|ech)?\b", "EUR"),
           (r"(?:britsk\w+ )?(?:lib(?:er|ra|ry|rou|rách)\b|gbp\b)", "GBP"), (r"jen(?:y|ů|u|em|ech)?\b|jpy\b", "JPY"),
           (r"rupi\w*|inr\b", "INR")],
}
_SYMBOL = {"$": "USD", "us$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP", "¥": "JPY", "jpy": "JPY",
           "₹": "INR", "inr": "INR", "rs": "INR", "rs.": "INR"}
_RANGE = re.compile(r"^\s*(?:-|–|—|to|až|do|and|a|or|nebo)\s*$", re.IGNORECASE)


def _amounts(text: str, lang: str) -> list[tuple[float, str | None]]:
    """Every number of a headline as (value × scale, unit), unit = %, bp or a currency."""
    rx = _NUM if lang == "en" else _NUM_CS
    found = []
    for m in rx.finditer(text):
        whole = re.sub(r"[ ,\u00a0\u202f]", "", m.group(1))
        value = float(f"{whole}.{m.group(2)}" if m.group(2) else whole)
        rest = text[m.end():m.end() + 40]
        rest = rest[:next((i for i, ch in enumerate(rest) if ch.isdigit()), len(rest))]
        unit, scale = None, 1.0
        before = _BEFORE.search(text[max(0, m.start() - 5):m.start()])
        if before:
            unit = _SYMBOL.get(before.group(1).strip().lower())
        if _PERCENT[lang].match(rest):
            unit = "%"
        elif _BP[lang].match(rest):
            unit = "bp"
        else:
            for pattern, factor in _SCALE[lang]:
                sm = re.match(r" ?(?:" + pattern + ")", rest, re.IGNORECASE)
                if sm:
                    scale, rest = factor, rest[sm.end():]
                    break
            if unit is None:
                for pattern, cur in _CURRENCY[lang]:
                    if re.match(r" ?(?:" + pattern + ")", rest, re.IGNORECASE):
                        unit = cur
                        break
        found.append([value, scale, unit, m.start(), m.end()])
    for a, b in zip(found, found[1:]):  # a range shares its unit and scale: "$3,800–4,000", "3800–4000 dolarů"
        if _RANGE.match(text[a[4]:b[3]]):
            a[2] = b[2] = a[2] or b[2]
            a[1] = b[1] = max(a[1], b[1])
    return sorted((round(v * sc, 6), u) for v, sc, u, _, _ in found)


def numbers_consistent(original: str, translation: str) -> bool:
    """True when the translation keeps every number of the original with its currency, percentage and scale."""
    return _amounts(tidy(html.unescape(original)), "en") == _amounts(translation, "cs")


def shown_title(title: str, title_cs: str | None, language: str) -> tuple[str, bool, bool]:
    """(headline to show, is it a machine translation, was the translation rejected). A stored translation is
    shown only when its numbers match the original — also one stored before the check existed."""
    if language != "en":
        return title_cs or title, False, False  # Czech original, or a language FTI does not translate
    if title_cs and numbers_consistent(title, title_cs):
        return title_cs, True, False
    return title, False, title_cs is not None


def translate(text: str) -> str | None:
    """Czech headline; REJECTED ("") when the translation changed a number; None when no translator."""
    with _lock:  # the model is not thread-safe; ingestion is single-threaded anyway
        tr = _load()
        if tr is None:
            return None
        try:
            result = polish(tr.translate(prepare(text)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Překlad selhal: %s", exc)
            return None
    if not numbers_consistent(text, result):
        logger.info("Překlad odmítnut, nesedí čísla: %r → %r", text, result)
        return REJECTED
    return result


def unavailable_reason() -> str | None:
    _load()
    return _unavailable_reason
