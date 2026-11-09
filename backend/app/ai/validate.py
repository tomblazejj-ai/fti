"""Checks every AI answer before FTI shows it:

  * the JSON matches the task's schema (types, required fields, allowed values);
  * every fact id the AI cites exists in the packet;
  * every number in the AI's text is one of the numbers in the facts — written any way
    ("3 886", "3,886", "3886.0", "3 886,50", "−4") and rounded no more than its own last digit allows.

An answer that fails is stored as "neověřeno" and the app shows the engine's own text instead;
no new request is sent because of it.
"""

from __future__ import annotations

import re

SMALL_INTS = set(range(0, 13))  # counts and horizons ("2 faktory", "3 dny") — not market data
_LETTER = "A-Za-zÀ-žĀ-ſ"
# an indicator's name with its periods ("EMA20/50", "EMA 20/50", "RSI14"), not a value. Found 8. 11. 2026 in the cloud:
# "/50" counted as an unknown number and threw away the whole technical role. "ATR 25" (a space, one number) stays a value.
INDICATOR = re.compile(r"(?i)\b(?:ema|sma|ma|rsi|adx|atr|macd)(?:\s?\d+(?:\s?/\s?\d+)+|\d+)")
_STRIP = [
    re.compile(r"\bF\d+\b"),  # fact ids
    re.compile(r"\b\d{1,2}:\d{2}\b"),  # times
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T[\d:.+\-Z]*)?"),  # ISO dates
    re.compile(r"\b\d{1,2}\.\s?\d{1,2}\.(?:\s?\d{4})?"),  # Czech dates 3. 11. 2026
    INDICATOR,
]
# a number glued to letters is part of a word ("2letý", "200denní", "H4") — except unit suffixes ("7.11M", "54.7K")
_SUFFIX = rf"(?:[KMBkmb](?![{_LETTER}]))?"
_NUMBER = re.compile(rf"(?<![{_LETTER}\d])-?\d{{1,3}}(?:[   ]\d{{3}})+(?:[.,]\d+)?{_SUFFIX}(?![{_LETTER}\d])"
                     rf"|(?<![{_LETTER}\d])-?\d+(?:[.,]\d+)*{_SUFFIX}(?![{_LETTER}\d])")


def _candidates(token: str) -> list[tuple[float, float]]:
    """(value, rounding tolerance) for every reasonable reading of a written number."""
    t = re.sub(r"[   ]", "", token.replace("−", "-")).rstrip("KMBkmb")
    neg = t.startswith("-")
    t = t.lstrip("-")
    out = []

    def add(s: str):
        try:
            v = float(s)
        except ValueError:
            return
        decimals = len(s.split(".")[1]) if "." in s else 0
        out.append((-v if neg else v, 0.5 * 10 ** -decimals + 1e-9))

    if "," in t and "." in t:
        dec = "," if t.rfind(",") > t.rfind(".") else "."
        add(t.replace("." if dec == "," else ",", "").replace(",", "."))
    elif t.count(",") == 1 or t.count(".") == 1:
        sep = "," if "," in t else "."
        add(t.replace(sep, "."))  # decimal separator
        if len(t.split(sep)[1]) == 3:
            add(t.replace(sep, ""))  # thousands separator
    elif t.count(",") > 1 or t.count(".") > 1:
        add(t.replace(",", "").replace(".", ""))
    else:
        add(t)
    return out


def numbers_in(text: str) -> list[str]:
    s = str(text).replace("−", "-")
    for rx in _STRIP:
        s = rx.sub(" ", s)
    return [m.group(0) for m in _NUMBER.finditer(s)]


def _walk_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _walk_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_strings(v)


def allowed_numbers(facts: list[dict]) -> list[float]:
    vals: list[float] = []
    for f in facts:
        for v in (f.get("hodnota"),):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals.append(float(v))
        for k in ("hodnota", "text", "co"):
            if isinstance(f.get(k), str):
                for tok in numbers_in(f[k]):
                    vals += [c[0] for c in _candidates(tok)]
    return vals


def unknown_numbers(output, facts: list[dict]) -> list[str]:
    allowed = [abs(v) for v in allowed_numbers(facts)]
    bad = []
    for s in _walk_strings(output):
        for tok in numbers_in(s):
            cands = _candidates(tok)
            if any(abs(v) in SMALL_INTS and float(abs(v)).is_integer() for v, _ in cands):
                continue
            if not any(abs(abs(v) - a) <= tol for v, tol in cands for a in allowed):
                bad.append(tok.strip())
    return bad


def schema_errors(value, schema: dict, path: str = "$") -> list[str]:
    t = schema.get("type")
    errs: list[str] = []
    if t == "object":
        if not isinstance(value, dict):
            return [f"{path}: má být objekt"]
        for k in schema.get("required", []):
            if k not in value:
                errs.append(f"{path}.{k}: chybí")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            errs += [f"{path}.{k}: navíc" for k in value if k not in props]
        for k, sub in props.items():
            if k in value:
                errs += schema_errors(value[k], sub, f"{path}.{k}")
    elif t == "array":
        if not isinstance(value, list):
            return [f"{path}: má být seznam"]
        for i, v in enumerate(value):
            errs += schema_errors(v, schema.get("items", {}), f"{path}[{i}]")
    elif t == "string":
        if not isinstance(value, str):
            errs.append(f"{path}: má být text")
    elif t in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errs.append(f"{path}: má být číslo")
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: nepovolená hodnota")
    return errs


def cited_ids(output) -> list[str]:
    out = []
    if isinstance(output, dict):
        for k, v in output.items():
            if k == "fakta" and isinstance(v, list):
                out += [x for x in v if isinstance(x, str)]
            else:
                out += cited_ids(v)
    elif isinstance(output, list):
        for v in output:
            out += cited_ids(v)
    return out


def validate(output, schema: dict, facts: list[dict]) -> dict:
    ids = {f["id"] for f in facts}
    schema_bad = schema_errors(output, schema)
    unknown_facts = sorted({i for i in cited_ids(output) if i not in ids})
    numbers = unknown_numbers(output, facts)
    return {"ok": not schema_bad and not unknown_facts and not numbers, "schema": schema_bad[:10],
            "unknown_facts": unknown_facts, "unknown_numbers": numbers[:10]}
