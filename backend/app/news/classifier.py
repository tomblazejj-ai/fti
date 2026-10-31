"""Rule-based (lexicon) news classifier — zero cost, no LLM API call.

Deliberately simple for the MVP (see docs/DECISIONS.md 2026-09-27): keyword
matching per factor tag, sentiment is the average of matched keyword
polarities, with a lightweight negation check (a nearby "not"/"no"/"unlikely"
flips the polarity — "Fed does NOT plan rate hikes" must not score as
hawkish). This is a real limitation vs. an LLM classifier — it will miss
deeper nuance and sarcasm. It is explainable and free, which the project's
constraints require. Upgrade path is a local open-source model (FinBERT),
tracked as Fáze 2 in ARCHITECTURE.md — GDELT's own bulk GKG tone data was
investigated for Modul 3 as a free alternative, but could not be verified
live from this sandbox (see docs/DECISIONS.md) so is not wired in yet.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

# Bump whenever lexicons or matching rules change: stored news is then
# re-classified on the next ingestion cycle (run_ingest.reclassify_stale_news).
CLASSIFIER_VERSION = 5

NEGATION_WORDS = [
    "not", "no", "won't", "will not", "unlikely", "ruled out", "denies",
    "denied", "rejects", "rejected", "against", "without", "fails to", "failed to",
]
NEGATION_LOOKBEHIND_CHARS = 40  # how far before a keyword match to look for a negator

# (keyword, polarity for GOLD/XAUUSD) — polarity is from XAUUSD's perspective,
# i.e. "risk-off" news is bullish (+) for gold, "hawkish Fed" is bearish (-).
FED_TONE_LEXICON: list[tuple[str, float]] = [
    (r"\bhawkish\b", -1.0),
    (r"\brate hike[s]?\b", -1.0),
    (r"\braise[sd]? (interest )?rates\b", -1.0),
    (r"\bhigher for longer\b", -0.7),
    (r"\bquantitative tightening\b", -1.0),
    (r"\bbalance sheet (runoff|reduction)\b", -0.6),
    (r"\btaper(ing)?\b", -0.5),
    (r"\bhold(s|ing)? rates? steady\b", -0.1),
    (r"\bunchanged rates?\b", -0.1),
    (r"\bdovish\b", 1.0),
    (r"\brate cut[s]?\b", 1.0),
    (r"\blower[sed]* (interest )?rates\b", 1.0),
    (r"\bease[sd]? (monetary )?policy\b", 1.0),
    (r"\bpause[sd]? rate hikes\b", 0.5),
    (r"\bquantitative easing\b", 1.0),
    (r"\bend(s|ing)? quantitative tightening\b", 0.6),
    # Czech (fxstreet.cz)
    # "saz(?:eb|b)" covers sazby / sazbu / sazeb / sazbách
    (r"\bjestřáb", -1.0),
    (r"\bzvýš\w* (úrokov\w* )?saz(?:eb|b)", -1.0),
    (r"\bzvyšován\w* (úrokov\w* )?saz(?:eb|b)", -1.0),
    (r"\bnezvýš\w* (úrokov\w* )?saz(?:eb|b)", 0.5),
    (r"\bholubi", 1.0),
    (r"\bsníž\w* (úrokov\w* )?saz(?:eb|b)", 1.0),
    (r"\bsnižován\w* (úrokov\w* )?saz(?:eb|b)", 1.0),
]

FED_SUBJECT = re.compile(
    r"\b(fed|feds|fedu|fedem|fomc|federal reserve|powell\w*|u\.?s\.? central bank|americk\w* centráln\w* bank\w*)\b",
    re.IGNORECASE,
)

GEOPOLITICS_LEXICON: list[tuple[str, float]] = [
    # "Department of War" / "War Secretary" is the renamed US defence ministry, not a war
    # (no literal spaces: _match_lexicon turns spaces into [\s-]+, which a look-behind can't take)
    (r"(?<!department\sof\s)(?<!secretary\sof\s)\bwar\b(?![\s-]+(?:department|secretary|games?|chest)\b)", 1.0),
    (r"\binvasion\b", 1.0),
    (r"\bairstrike[s]?\b", 0.9),
    (r"\bnuclear (threat|test|strike)\b", 1.0),
    (r"\bcoup\b", 0.8),
    (r"\bannexation\b", 0.8),
    (r"\bconflict\b", 0.8),
    (r"\bsanctions?\b", 0.7),
    (r"\btariffs?\b", 0.5),
    (r"\btrade war\b", 0.7),
    (r"\bmilitary strike[s]?\b", 1.0),
    (r"\bsafe.haven demand\b", 0.8),
    (r"\brisk.off\b", 0.6),
    (r"\bceasefire\b", -0.6),
    (r"\bpeace (deal|talks|treaty)\b", -0.8),
    (r"\bdiplomatic breakthrough\b", -0.7),
    (r"\bsummit agreement\b", -0.5),
    (r"\bde-escalat", -0.7),
    (r"\bescalat", 0.8),
    (r"\brisk.on rally\b", -0.5),
    # Czech (fxstreet.cz)
    (r"\bválk", 1.0),
    (r"\bkonflikt", 0.8),
    (r"\bsankc", 0.7),
    (r"\b(cla|clo|clům|cly)\b", 0.5),
    (r"\bobchodní válk", 0.7),
    (r"\bútok", 0.8),
    (r"\beskal", 0.8),
    (r"\bdeeskal", -0.7),
    (r"\bpříměří", -0.6),
    (r"\bmírov\w* (dohod|jednání|rozhovor)", -0.8),
    (r"\bbezpečn\w* přístav", 0.8),
]

CB_GOLD_BUYING_LEXICON: list[tuple[str, float]] = [
    (r"\bcentral bank[s]? (gold )?(buying|purchases?)\b", 1.0),
    (r"\bgold reserves? (increase|rose|rising|added)\b", 1.0),
    (r"\bpbo[c]? (buys|added) gold\b", 1.0),
    (r"\bgold reserves? (decrease|fell|selling)\b", -1.0),
    (r"\bcentráln\w* bank\w* (nakup|nakoup|nákup)\w*", 1.0),
    (r"\b(nákup|nakup)\w* zlata centráln", 1.0),
    (r"\bzlat\w* rezerv\w* (rost|vzrost|navýš)", 1.0),
]

INSTRUMENT_KEYWORDS: dict[str, list[str]] = {
    # "Gold Coast" (city, sports clubs) and "gold medal" are not about the metal
    "XAUUSD": [r"\bgold\b(?![\s-]+(?:coast|medals?|medallist|cup)\b)", r"\bxau\b", r"\bbullion\b",
               r"\bzlat(o|a|u|em|ě)\b(?!\s+medail)", r"\bdrah\w* kov"],
    "EURUSD": [r"\beuro\b", r"\beurusd\b", r"\becb\b"],
    "GBPUSD": [r"\bpound\b", r"\bsterling\b", r"\bgbpusd\b", r"\bboe\b"],
    "USDJPY": [r"\byen\b", r"\busdjpy\b", r"\bboj\b"],
    "US100": [r"\bnasdaq\b", r"\bus100\b"],
    "US500": [r"\bs&p ?500\b", r"\bus500\b"],
    "WTI": [r"\bwti\b", r"\bcrude oil\b", r"\bopec\b"],
    "BTCUSD": [r"\bbitcoin\b", r"\bbtc\b"],
}


@dataclass
class ClassifiedNews:
    instrument_tags: list[str] = field(default_factory=list)
    factor_tags: list[str] = field(default_factory=list)
    sentiment_by_tag: dict[str, float] = field(default_factory=dict)
    matched_keywords: dict[str, list[str]] = field(default_factory=dict)
    relevance_score: float = 0.0  # 0-1


_NEGATION_RE = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in NEGATION_WORDS) + r")\b", re.IGNORECASE)


def _is_negated(text: str, match_start: int) -> bool:
    # Whole words only: a substring check made "announces", "economy" and
    # "notes" count as negations and flipped real headlines (caught on live
    # GDELT data, see docs/DECISIONS.md).
    window = text[max(0, match_start - NEGATION_LOOKBEHIND_CHARS):match_start]
    return _NEGATION_RE.search(window) is not None


def _match_lexicon(text: str, lexicon: list[tuple[str, float]]) -> tuple[float, list[str]]:
    hits: list[str] = []
    polarities: list[float] = []
    for pattern, polarity in lexicon:
        # a space in a phrase also matches a hyphen: "rate hike" == "rate-hike"
        m = re.search(pattern.replace(" ", r"[\s-]+"), text, re.IGNORECASE)
        if m:
            effective_polarity = -polarity if _is_negated(text, m.start()) else polarity
            hits.append(pattern if effective_polarity == polarity else f"{pattern} (negated)")
            polarities.append(effective_polarity)
    if not hits:
        return 0.0, []
    return sum(polarities) / len(polarities), hits


def classify(title: str, snippet: str) -> ClassifiedNews:
    text = f"{title}\n{snippet}"
    result = ClassifiedNews()

    for instrument, patterns in INSTRUMENT_KEYWORDS.items():
        if any(re.search(p, text, re.IGNORECASE) for p in patterns):
            result.instrument_tags.append(instrument)

    fed_sent, fed_hits = _match_lexicon(text, FED_TONE_LEXICON)
    # Rate words only count as *Fed* tone when the Fed is actually the subject —
    # a Chinese or ECB rate cut is not a dovish Fed (seen live 2026-09-30).
    if fed_hits and FED_SUBJECT.search(text):
        result.factor_tags.append("fed_tone")
        result.sentiment_by_tag["fed_tone"] = fed_sent
        result.matched_keywords["fed_tone"] = fed_hits

    geo_sent, geo_hits = _match_lexicon(text, GEOPOLITICS_LEXICON)
    if geo_hits:
        result.factor_tags.append("geopolitics")
        result.sentiment_by_tag["geopolitics"] = geo_sent
        result.matched_keywords["geopolitics"] = geo_hits

    cb_sent, cb_hits = _match_lexicon(text, CB_GOLD_BUYING_LEXICON)
    if cb_hits:
        result.factor_tags.append("cb_gold_buying")
        result.sentiment_by_tag["cb_gold_buying"] = cb_sent
        result.matched_keywords["cb_gold_buying"] = cb_hits

    total_hits = sum(len(v) for v in result.matched_keywords.values())
    result.relevance_score = min(1.0, 0.2 * total_hits + (0.3 if result.instrument_tags else 0.0))

    return result


def dedup_hash(source: str, title: str, url: str) -> str:
    raw = f"{source}|{title.strip().lower()}|{url.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
