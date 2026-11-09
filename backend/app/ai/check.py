"""FTI's independent check of an AI answer — rules, no AI. It runs after the number check (validate.py), which
only proves that every number exists somewhere in the facts. This one proves the number belongs where the AI
put it (found on 8. 11. 2026: the model wrote "rising 10-year yields" while FTI's data showed them falling, and
gave the S&P 500 the correlation that belongs to the 10-year yield):

  attribution  every number of a point must be in the facts that point cites
  direction    a point saying a series rises / falls must match its direction in FTI's data (5 and 20 days agree)
  correlation  a correlation value must stand next to the series it belongs to, not next to another one

Each problem names the point, so a specialist's wrong point can be dropped and the synthesis can be asked once
to fix its answer. A conditional ("pokud výnosy porostou") is never taken for a statement about the data.
"""

from __future__ import annotations

import re

from app.ai import validate

# series aliases in Czech and English (lower case); the more specific series first
ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("DFII10", ("reáln", "tips")),
    ("DGS10", ("10-let", "10let", "10 let", "10y", "treasury", "nominální výnos")),
    ("DGS2", ("2-let", "2let", "2 let", "2y", "dvoulet")),
    ("VIXCLS", ("vix",)),
    ("DCOILBRENTEU", ("brent",)),
    ("DCOILWTICO", ("ropa", "ropy", "ropě", "ropu", "wti")),
    ("SP500", ("s&p", "akci", "akcie")),
    ("DXY", ("dxy", "dolar")),
    ("EURUSD", ("eur/usd", "eurusd")),
    ("USDJPY", ("usd/jpy", "usdjpy")),
]
RISE = re.compile(r"\b(roste|rostou|rostl\w*|rostouc\w*|stoup\w*|zvyšuj\w*|zvýšil\w*|posiluj\w*|posílil\w*|vzrost\w*|nárůst\w*)")
FALL = re.compile(r"\b(klesá|klesaj\w*|klesl\w*|klesajíc\w*|pokles\w*|snižuj\w*|snížil\w*|oslabuj\w*|oslabil\w*)")
CONDITIONAL = re.compile(r"\b(pokud|když|kdyby|jestli|jestliže|případn\w*|mohl\w*|může|mohou)\b")
_CLAUSE = re.compile(r"[.;,:]\s|\s(?:ale|zatímco|avšak|kdežto|a)\s")
_HYPHENS = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "−": "-", " ": " "})


_POSITIVE = re.compile(r"\b(kladn\w*|pozitivn\w*|souběžn\w*)")
_NEGATIVE = re.compile(r"\b(záporn\w*|negativn\w*|opačn\w*|inverzn\w*)")
_RELATION = re.compile(r"korel|\bvztah")
_INDICATOR = validate.INDICATOR  # "EMA20/50" names, not values — one rule for both checks


def _norm(text: str) -> str:
    return str(text).translate(_HYPHENS).lower()


def _series_in(clause: str) -> list[str]:
    found, rest = [], clause
    for sid, words in ALIASES:
        hit = next((w for w in words if w in rest), None)
        if hit:
            found.append(sid)
            rest = rest.replace(hit, " ")  # "reálný výnos 10 let" is the real yield, not also the nominal one
    return found


def _points(node, path: str = "$"):
    """(path, text, cited ids or None) of every text in the answer."""
    if isinstance(node, dict):
        if isinstance(node.get("text"), str) and isinstance(node.get("fakta"), list):
            yield path, node["text"], [x for x in node["fakta"] if isinstance(x, str)]
        for k, v in node.items():
            if k in ("text", "fakta"):
                continue
            if isinstance(v, str):
                yield f"{path}.{k}", v, None
            else:
                yield from _points(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _points(v, f"{path}[{i}]")


def _fact_numbers(facts: list[dict]) -> list[float]:
    return [abs(v) for v in validate.allowed_numbers(facts)]


def _matches(token: str, allowed: list[float]) -> bool:
    cands = validate._candidates(token)
    if any(abs(v) in validate.SMALL_INTS and float(abs(v)).is_integer() for v, _ in cands):
        return True
    return any(abs(abs(v) - a) <= tol for v, tol in cands for a in allowed)


def drop(output: dict, problems: list[dict]) -> tuple[dict, list[dict], list[dict]]:
    """(answer without the wrong points, removed points, problems in texts that cannot be removed). A point is
    removed only from a list of points; a wrong summary or description stays and makes the answer unverified."""
    import copy

    out = copy.deepcopy(output)
    removed, fixed_in_place = [], []
    targets = []
    for pr in problems:
        m = re.fullmatch(r"(.*)\[(\d+)\]", pr["path"])
        if m:
            targets.append((m.group(1), int(m.group(2)), pr))
        else:
            fixed_in_place.append(pr)
    for parent, idx, pr in sorted(targets, key=lambda t: (t[0], -t[1])):
        node = out
        for part in re.findall(r"\.(\w+)|\[(\d+)\]", parent):
            node = node[part[0]] if part[0] else node[int(part[1])]
        if isinstance(node, list) and idx < len(node) and node[idx] is not None:
            removed.append({**pr})
            node[idx] = None
    def compact(n):
        if isinstance(n, dict):
            return {k: compact(v) for k, v in n.items()}
        if isinstance(n, list):
            return [compact(v) for v in n if v is not None]
        return n
    return compact(out), removed, fixed_in_place


# a value written next to an indicator's name must be that indicator's value in the cited facts ("EMA20 4049.16")
LABELS = {"EMA20": r"ema\s?20", "EMA50": r"ema\s?50", "ADX": r"adx", "ATR": r"atr", "swing high": r"swing\s?high",
          "swing low": r"swing\s?low", "SMA50": r"sma\s?50(?!\d)", "SMA200": r"sma\s?200(?!\d)", "RSI14": r"rsi\s?14(?!\d)"}
_VALUE = r"\s*(?:\(|na|je|=|:|kolem|u|okolo)?\s*[≈~]?\s*(-?\d+(?:[.,]\d+)?)"


def _label_values(low_text: str, cited_facts: list[dict]) -> list[str]:
    out = []
    for name, pat in LABELS.items():
        known = []
        for f in cited_facts:
            for m in re.finditer(pat + _VALUE, _norm(f.get("text") or "")):
                known.append(float(m.group(1).replace(",", ".")))
        if not known:
            continue
        for m in re.finditer(pat + _VALUE, low_text):
            raw = m.group(1)
            value = float(raw.replace(",", ".").replace(" ", ""))
            decimals = len(re.split(r"[.,]", raw)[1]) if re.search(r"[.,]", raw) else 0
            tol = max(0.5 * 10 ** -decimals, 0.005) + 1e-9
            if not any(abs(value - k) <= tol or abs(round(k) - value) < 1e-9 for k in known):
                shown = ", ".join(f"{k:g}" for k in sorted(set(known)))
                out.append(f"{name} je v citovaných údajích {shown}, ne {raw}")
    return out


def attribution(output, facts: list[dict]) -> list[dict]:
    """[{path, text, problem}] — empty when every point holds."""
    by_id = {f["id"]: f for f in facts}
    series: dict[str, dict] = {}
    for f in facts:  # a fact with the series' direction wins over one that only carries its correlation (Intermarket)
        if f.get("rada") and (f.get("smer") or f["rada"] not in series):
            series[f["rada"]] = f
    corr_owner: dict[float, set[str]] = {}
    corr_sign: dict[str, list[float]] = {}
    for f in facts:
        for r in f.get("korelace") or []:
            corr_owner.setdefault(round(abs(r), 2), set()).add(f["rada"])
            if abs(r) >= 0.2:  # the sign of a negligible correlation says nothing
                corr_sign.setdefault(f["rada"], []).append(r)
    problems = []
    for path, text, cited in _points(output):
        low = _norm(text)
        if cited is not None and not cited and path.endswith("]"):  # a listed point can go; the rest is judged on its text
            problems.append({"path": path, "text": text, "problem": "bod se neopírá o žádný údaj FTI"})
        if cited:
            cited_facts = [by_id[i] for i in cited if i in by_id]
            allowed = _fact_numbers(cited_facts)
            wrong = [t.strip() for t in validate.numbers_in(_INDICATOR.sub(" ", text.translate(_HYPHENS))) if not _matches(t, allowed)]
            if wrong:
                problems.append({"path": path, "text": text,
                                 "problem": f"čísla {', '.join(wrong)} nejsou v citovaných údajích {', '.join(cited)}"})
            problems += [{"path": path, "text": text, "problem": p} for p in _label_values(low, cited_facts)]
        for clause in _CLAUSE.split(low):
            if CONDITIONAL.search(clause):
                continue
            rise, fall = bool(RISE.search(clause)), bool(FALL.search(clause))
            if rise == fall:
                continue
            for sid in _series_in(clause):
                s = (series.get(sid) or {}).get("smer") or {}
                if len(set(s.values())) == 1 and s:
                    real = next(iter(s.values()))
                    if (rise and real == "klesá") or (fall and real == "roste"):
                        problems.append({"path": path, "text": text, "problem": (
                            f"{series[sid]['co']}: text říká „{'roste' if rise else 'klesá'}“, data FTI ukazují "
                            f"„{real}“ za 5 i 20 dní")})
        for clause in re.split(r"[.;]\s", low):  # the SIGN of a correlation, per sentence (8. 11.: "vztahy s EUR/USD
            # … stabilní, ale s negativní korelací" while r = +0.48; later "Vztahy s DXY, S&P 500 a VIX jsou stabilní a
            # negativní" while S&P's r = +0.39 — a relationship called negative is a correlation sign, too)
            if not _RELATION.search(clause) or CONDITIONAL.search(clause):
                continue
            pos, neg = bool(_POSITIVE.search(clause)), bool(_NEGATIVE.search(clause))
            if pos == neg:
                continue
            for sid in _series_in(clause):
                vals = corr_sign.get(sid) or []
                if vals and all(v > 0 for v in vals) and neg or vals and all(v < 0 for v in vals) and pos:
                    problems.append({"path": path, "text": text, "problem": (
                        f"korelace zlata s řadou {sid} je v datech FTI {'kladná' if vals[0] > 0 else 'záporná'}, "
                        f"text ji označuje za {'zápornou' if neg else 'kladnou'}")})
        for m in re.finditer(r"-?\d+[.,]\d+", low):
            owners = corr_owner.get(round(abs(float(m.group(0).replace(",", "."))), 2))
            if not owners or len(owners) > 1 or "korel" not in low:
                continue
            owner = next(iter(owners))
            before = low[max(0, m.start() - 80):m.start()]
            near = [(before.rfind(w), sid) for sid, words in ALIASES for w in words if w in before]
            if near:
                nearest = max(near)[1]
                if nearest != owner and nearest in series:
                    problems.append({"path": path, "text": text, "problem": (
                        f"korelace {m.group(0)} patří k řadě „{series[owner]['co']}“, ne k „{series[nearest]['co']}“")})
    return problems
