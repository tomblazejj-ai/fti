"""The trading assistant: the Funded Mind swing checklist applied to today's data.

From the strategy video (2026-10) — one system, every piece confirms or does not:
  1. supply/demand zone on the WEEKLY chart
  2. the zone refined on the DAILY chart (daily zone inside the weekly one)
  3. trading activity in the zone (volume profile; here time-at-price, see zones.py)
  4. the Trading Analyzer score in the direction of the trade
  5. COT in the direction of the trade
  6. seasonality in the direction of the trade
  then: entry at the zone edge, stop-loss behind the zone, target at least the opposite zone.
  "Když by proti mně šlo makro, COT i seasonality, tak ten obchod prostě nechám být.
   Stejně tak, když ta zóna nemá za sebou žádný objem."
Timing rules from the course on top: no entry 2 h before red news, no position over the weekend.

Plain rules, no prediction: this says which zone fits the strategy and what is missing,
never "buy now".
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

PRAGUE = ZoneInfo("Europe/Prague")
REACH_PCT = 8.0  # zones further away than this are not this week's business
SL_BUFFER_ATR = 0.25  # stop-loss this far behind the zone's far edge (D1 ATR)
NEAR_ATR = 0.5  # price within half a daily ATR of the entry = "blíží se"

CHECKS = [
    ("weekly", "Týdenní zóna"),
    ("daily", "Denní zóna pro přesný vstup"),
    ("activity", "Aktivita v zóně"),
    ("score", "Fundament (skóre)"),
    ("cot", "COT"),
    ("season", "Sezónnost"),
]


def _usd(v: float | None, digits: int = 0) -> str:
    if v is None:
        return "—"
    return f"{v:,.{digits}f}".replace(",", " ").replace(".", ",") + " $"


def _pct(v: float, signed: bool = False) -> str:
    s = f"{v:+.1f}" if signed else f"{v:.1f}"
    return s.replace(".", ",").replace("-", "−")


def _rng(z: dict) -> str:
    return f"{_usd(z['lo'])[:-2]}–{_usd(z['hi'])}"


def _pick(zt: dict, kind: str) -> tuple[dict | None, dict | None]:
    """(entry zone, its weekly zone). The nearest daily zone inside a weekly zone wins,
    then the nearest daily zone, then the nearest weekly zone — all within reach."""
    d1 = [z for z in (zt.get("D1") or {}).get(kind, []) if z["distance_pct"] <= REACH_PCT]
    w1 = [z for z in (zt.get("W1") or {}).get(kind, []) if z["distance_pct"] <= REACH_PCT]
    nested = [z for z in d1 if z.get("in_weekly")]
    pick = d1[0] if d1 else (w1[0] if w1 else None)
    if nested and (not d1 or nested[0] is d1[0] or nested[0]["distance_pct"] - d1[0]["distance_pct"] < 1.0):
        pick = nested[0]
    if pick is None:
        return None, None
    weekly = pick if pick["tf"] == "W1" else next(
        (w for w in (zt.get("W1") or {}).get(kind, []) if w["lo"] <= pick["hi"] and pick["lo"] <= w["hi"]), None)
    return pick, weekly


def _target(zt: dict, side: str, entry: float) -> dict | None:
    kind = "supply" if side == "long" else "demand"
    cands = []
    for tf in ("D1", "W1"):
        for z in (zt.get(tf) or {}).get(kind, []):
            if (side == "long" and z["proximal"] > entry) or (side == "short" and z["proximal"] < entry):
                cands.append(z)
    if not cands:
        return None
    return min(cands, key=lambda z: abs(z["proximal"] - entry))


def _dir_check(value: int | None, side: str) -> str:
    if value is None or value == 0:
        return "na"
    return "ok" if (value > 0) == (side == "long") else "bad"


def build_setup(side: str, zones: dict, tra_xau: dict | None, season_lean: int | None, season_text: str,
                cot_text: str) -> dict | None:
    zt = zones.get("tf") or {}
    kind = "demand" if side == "long" else "supply"
    zone, weekly = _pick(zt, kind)
    if zone is None:
        return None
    price, atr = zones["price"], zones.get("atr_d1") or 0.0
    comps = {c["key"]: c for c in (tra_xau or {}).get("components", [])}
    total = (tra_xau or {}).get("total")
    cot_score = (comps.get("cot") or {}).get("score")

    checks = []
    w_ok = weekly is not None
    checks.append({"key": "weekly", "label": "Týdenní zóna", "state": "ok" if w_ok else "bad",
                   "text": (f"Týdenní {('demand' if side == 'long' else 'supply')} zóna {_rng(weekly)}." if w_ok else
                            "Zóna je jen na denním grafu — metodika začíná na týdenním, setup je proto slabší.")})
    d_ok = zone["tf"] == "D1"
    checks.append({"key": "daily", "label": "Denní zóna pro přesný vstup", "state": "ok" if d_ok else "na",
                   "text": (f"Denní zóna {_rng(zone)}" + (" leží uvnitř týdenní." if zone.get("in_weekly") else ".") if d_ok
                            else "Na denním grafu uvnitř týdenní zóny žádná zóna není — vstup upřesni sám.")})
    act = zone.get("activity")
    checks.append({"key": "activity", "label": "Aktivita v zóně",
                   "state": {"active": "ok", "some": "na", "none": "bad"}.get(act or "", "na"),
                   "text": {"active": "Cena tu v minulosti strávila hodně času — zóna má za sebou obchodní aktivitu.",
                            "some": "Aktivita je průměrná.",
                            "none": "Cena tu skoro nebyla — zóna bez aktivity má podle metodiky malou váhu."}.get(
                       act or "", "Aktivitu nelze spočítat.") + " (Čas na ceně místo objemu z futures, ten zdarma není.)"})
    checks.append({"key": "score", "label": "Fundament (skóre)", "state": _dir_check(total, side),
                   "text": ("Skóre zatím není." if total is None else
                            f"Skóre {'+' if total > 0 else ''}{total} — " + (
                                "fundament směr potvrzuje." if _dir_check(total, side) == "ok" else
                                "fundament jde proti." if _dir_check(total, side) == "bad" else "fundament je neutrální."))
                   .replace("-", "−")})
    checks.append({"key": "cot", "label": "COT", "state": _dir_check(cot_score, side),
                   "text": (f"COT {'+' if (cot_score or 0) > 0 else ''}{cot_score if cot_score is not None else '—'} z ±3. ".replace("-", "−")
                            + cot_text)})
    checks.append({"key": "season", "label": "Sezónnost", "state": _dir_check(season_lean, side), "text": season_text})

    ok = sum(1 for c in checks if c["state"] == "ok")
    against = [c["key"] for c in checks if c["state"] == "bad" and c["key"] in ("score", "cot", "season")]
    if len(against) == 3:
        grade, verdict = "skip", "Nech být — fundament, COT i sezónnost jdou proti."
    elif any(c["key"] == "activity" and c["state"] == "bad" for c in checks):
        grade, verdict = "C", "Slabá zóna — bez obchodní aktivity."
    elif ok == 6:
        grade, verdict = "A+", "Ideální setup — všechno sedí."
    elif ok == 5 and "score" not in against:
        grade, verdict = "A", "Silný setup."
    elif ok >= 4 and "score" not in against:
        grade, verdict = "B", "Použitelný setup, ale něco chybí."
    else:
        grade, verdict = "C", "Slabý setup — víc proti než pro."

    # the plan: entry at the zone edge, SL behind it, target at the opposite zone
    entry = zone["proximal"]
    buffer = SL_BUFFER_ATR * atr
    stop = zone["distal"] - buffer if side == "long" else zone["distal"] + buffer
    tgt = _target(zt, side, entry)
    target = tgt["proximal"] if tgt else None
    risk = abs(entry - stop)
    rr = round(abs(target - entry) / risk, 1) if target and risk else None
    if zone["inside"]:
        state, where = "in_zone", "Cena je teď v zóně."
    else:
        gap = abs(price - entry)
        state = "near" if atr and gap <= NEAR_ATR * atr else "waiting"
        where = f"Cena je {_pct(zone['distance_pct'])} % od vstupu" + (" — blíží se." if state == "near" else " — čekej, až k zóně dojde.")
    return {
        "side": side,
        "zone": zone,
        "weekly": weekly,
        "checks": checks,
        "ok": ok,
        "total_checks": len(checks),
        "grade": grade,
        "verdict": verdict,
        "plan": {"entry": round(entry, 2), "poc": zone.get("poc"), "stop": round(stop, 2), "target": round(target, 2) if target else None,
                 "target_zone": tgt, "rr": rr, "risk_usd": round(risk, 2)},
        "state": state,
        "where": where,
    }


def _season(daily: dict | None, monthly_score: int | None) -> tuple[int | None, str]:
    if daily and daily.get("next30"):
        n = daily["next30"]
        lean = daily.get("lean", 0)
        txt = (f"Příštích 30 dní: zlato rostlo v {n['up']} z {n['n']} let, průměr {_pct(n['avg'], True)} %."
               + ("" if lean else " Bez jasného sklonu."))
        if daily.get("texts"):
            txt += " " + daily["texts"][0]
        return lean, txt
    if monthly_score is not None:
        return (1 if monthly_score > 0 else -1 if monthly_score < 0 else 0), "Podle měsíční sezónnosti (10 let)."
    return None, "Sezónnost teď není k dispozici."


def build(zones: dict | None, tra: dict | None, season_daily: dict | None, season_monthly_score: int | None,
          cot: dict | None, lock: dict | None, weekend: dict | None, now: dt.datetime) -> dict | None:
    if not zones or not zones.get("tf"):
        return None
    xau = (tra or {}).get("xau")
    lean, season_text = _season(season_daily, season_monthly_score)
    cot_bits = []
    if cot:
        if cot.get("commercials"):
            cot_bits.append(cot["commercials"]["text"])
        if cot.get("open_interest_view"):
            cot_bits.append(cot["open_interest_view"]["text"])
    cot_text = " ".join(cot_bits) or "Podrobnosti v záložce COT."
    setups = {s: build_setup(s, zones, xau, lean, season_text, cot_text) for s in ("long", "short")}
    total = (xau or {}).get("total")
    bias = None if total is None else "long" if total > 0 else "short" if total < 0 else None
    order = [bias, "short" if bias == "long" else "long"] if bias else sorted(
        ("long", "short"), key=lambda s: -(setups[s]["ok"] if setups[s] else -1))
    primary = next((s for s in order if s and setups.get(s)), None)
    p = setups.get(primary) if primary else None

    timing = []
    if lock and lock.get("state") == "lock":
        timing.append({"key": "news", "state": "bad", "text": lock["text"]})
    elif lock and lock.get("state") == "after":
        timing.append({"key": "news", "state": "na", "text": lock["text"]})
    if weekend:
        timing.append({"key": "weekend", "state": "bad", "text": weekend["text"]})

    side_word = {"long": "LONG", "short": "SHORT"}
    if p is None:
        action, headline = "wait", "Teď není v dosahu žádná zóna — čekej, až cena dojde k týdenní zóně."
    elif p["grade"] in ("A+", "A", "B"):
        z = p["zone"]
        where = "je TEĎ v" if p["state"] == "in_zone" else "u"
        kind = "demand" if p["side"] == "long" else "supply"
        lead = (f"Hledej {side_word[p['side']]} — cena {where} {kind} zóně {_rng(z)}" if p["state"] == "in_zone"
                else f"Čekej na {side_word[p['side']]} u {kind} zóny {_rng(z)} ({_pct(z['distance_pct'])} % od ceny)")
        headline = f"{lead}. Potvrzení {p['ok']} z {p['total_checks']}, setup {p['grade']}."
        action = p["side"] if p["state"] in ("in_zone", "near") else "wait"
    else:
        z = p["zone"]
        headline = (f"Teď žádný dobrý setup. Nejbližší kandidát: {side_word[p['side']]} u zóny {_rng(z)} "
                    f"— jen {p['ok']} z {p['total_checks']} potvrzení.")
        action = "wait"
    if any(t["key"] == "news" and t["state"] == "bad" for t in timing):
        headline += " Pozor: blíží se červená zpráva — teď nevstupuj."
        action = "wait"
    other = setups.get("long" if primary == "short" else "short") if primary else None
    other_text = None
    if other:
        oz = other["zone"]
        other_text = (f"Opačný směr: {side_word[other['side']]} u zóny {_rng(oz)} — {other['ok']} z {other['total_checks']} "
                      f"potvrzení ({other['verdict'].lower().rstrip('.')})")
    return {
        "action": action,
        "headline": headline,
        "primary": primary,
        "setups": setups,
        "other_text": other_text,
        "timing": timing,
        "bias": bias,
        "note": "Plán skládají pevná pravidla strategie z dat, která teď známe. Není to investiční doporučení — rozhodnutí je vždy tvoje.",
        "computed_at": now.isoformat(),
    }


def week_range(now: dt.datetime) -> tuple[dt.date, dt.date, bool]:
    """(Monday, Friday, is_next_week) — after the Friday close and over the weekend the coming week."""
    local = now.astimezone(PRAGUE)
    d = local.date()
    nxt = d.weekday() >= 5 or (d.weekday() == 4 and local.hour >= 22)
    monday = d - dt.timedelta(days=d.weekday()) + (dt.timedelta(days=7) if nxt else dt.timedelta(0))
    return monday, monday + dt.timedelta(days=4), nxt


def weekly_plan(setup: dict | None, calendar: dict | None, tra: dict | None, cot: dict | None, season_daily: dict | None,
                now: dt.datetime) -> dict:
    """The weekend preparation ("1–2 hodiny o víkendu připravuju nadcházející týden")."""
    monday, friday, nxt = week_range(now)
    events = [e for e in (calendar or {}).get("events", []) if monday.isoformat() <= e["date"] <= friday.isoformat()]
    days = []
    for i in range(5):
        day = monday + dt.timedelta(days=i)
        evs = [e for e in events if e["date"] == day.isoformat()]
        days.append({"date": day.isoformat(),
                     "events": [{"name": e["name"], "time": e["time"], "importance": e["importance"], "past": e["past"]} for e in evs]})
    xau = (tra or {}).get("xau") or {}
    mom = ((tra or {}).get("momentum") or {}).get("xau") or {}
    lines = []
    if xau:
        d7 = (mom.get("changes") or {}).get("7d")
        lines.append(f"Fundament: skóre {'+' if xau['total'] > 0 else ''}{xau['total']} ({(xau.get('strength') or '') + xau['word'].lower()})"
                     .replace("-", "−") + (f", za týden {'+' if d7 > 0 else ''}{d7}".replace("-", "−") if d7 is not None else "") + ".")
    if setup and setup.get("primary") and setup["setups"].get(setup["primary"]):
        p = setup["setups"][setup["primary"]]
        z = p["zone"]
        plan = p["plan"]
        lines.append(f"Plán: {('long' if p['side'] == 'long' else 'short')} od zóny {_rng(z)}, SL {_usd(plan['stop'])}"
                     + (f", cíl {_usd(plan['target'])} (R:R {str(plan['rr']).replace('.', ',')})" if plan["target"] else "")
                     + f" — setup {p['grade']}.")
    reds = [e for e in events if e["importance"] == 3 and not e["past"]]
    if reds:
        lines.append("Červené zprávy: " + ", ".join(
            f"{['po', 'út', 'st', 'čt', 'pá'][dt.date.fromisoformat(e['date']).weekday()]} {e['time'] or ''} {e['name']}".replace("  ", " ")
            for e in reds) + " — 2 h před nimi nic nového neotevírej.")
    if season_daily and season_daily.get("texts"):
        lines.append("Sezónnost: " + season_daily["texts"][0])
    if cot and cot.get("schedule"):
        rel = dt.datetime.fromisoformat(cot["schedule"]["next_release"]).astimezone(PRAGUE)
        lines.append(f"COT: další report {rel.day}. {rel.month}. ve {rel:%H:%M}.")
    lines.append("Pátek večer: pozice přes víkend nedrž.")
    return {"monday": monday.isoformat(), "friday": friday.isoformat(), "next_week": nxt, "days": days, "lines": lines,
            "title": "Plán na příští týden" if nxt else "Plán na tento týden"}
