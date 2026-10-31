"""Score momentum — "Skóre = makro kompas, momentum = jeho směr" (Funded Mind, TrA Score Momentum).

From the stored score history and the daily price:
  * changes over 24 h / 7 days / 30 days ("sleduju rychlost, ne hodnotu")
  * TRADE IDEA when the score moved by ≥ 2 points within 24 h (Score overview, step 2)
  * MODEL SITUATION 1 — consolidation + score change: price stuck in a range while the score
    shifts → possible range → trend transition; enter only once price reacts
  * MODEL SITUATION 2 — divergence: price keeps going, the score turns → weakening fundamental
    support; look for a strong supply/demand level for a counter-trend entry
All thresholds are fixed and written in the texts.
"""

from __future__ import annotations

import datetime as dt

IDEA_POINTS = 2
RANGE_DAYS = 10
RANGE_MAX_PCT = {"XAUUSD": 3.0, "USD": 1.2}  # 10-day high–low band that counts as "stagnating"
DIVERGENCE_MIN_PCT = {"XAUUSD": 1.5, "USD": 0.6}


def _num(v: float, digits: int = 0, signed: bool = True) -> str:
    s = f"{v:+.{digits}f}" if signed else f"{v:.{digits}f}"
    return s.replace(".", ",").replace("-", "−")


def _value_at(points: list[tuple[dt.datetime, int]], t: dt.datetime) -> int | None:
    best = None
    for pt, v in points:
        if pt <= t:
            best = v
        else:
            break
    return best


def analyze(points: list[tuple[dt.datetime, int]], prices: list[tuple[dt.datetime, float]], now: dt.datetime,
            instrument: str = "XAUUSD") -> dict | None:
    """`points` and `prices` oldest first."""
    if not points:
        return None
    cur = points[-1][1]
    ch = {}
    for key, delta in (("24h", dt.timedelta(hours=24)), ("7d", dt.timedelta(days=7)), ("30d", dt.timedelta(days=30))):
        past = _value_at(points, now - delta)
        ch[key] = None if past is None else cur - past

    idea = None
    if ch["24h"] is not None and abs(ch["24h"]) >= IDEA_POINTS:
        frm = cur - ch["24h"]
        up = ch["24h"] > 0
        idea = {
            "direction": "up" if up else "down",
            "from": frm, "to": cur,
            "text": (f"Skóre se za 24 h změnilo z {_num(frm)} na {_num(cur)} ({_num(ch['24h'])}) — sentiment se posouvá "
                     f"{'nahoru' if up else 'dolů'}. Najdi zóny ve směru nového biasu, urči cíl a čekej na pullback."),
        }

    situations = []
    closes = [p for _, p in prices]
    if len(closes) >= RANGE_DAYS + 1:
        window = closes[-RANGE_DAYS:]
        band = (max(window) - min(window)) / closes[-1] * 100
        price_chg = (closes[-1] / closes[-RANGE_DAYS - 1] - 1) * 100
        s7 = ch["7d"]
        if s7 is not None and abs(s7) >= IDEA_POINTS and band <= RANGE_MAX_PCT.get(instrument, 3.0):
            situations.append({
                "key": "consolidation",
                "title": "Konsolidace a změna skóre",
                "text": (f"Cena stagnuje (rozpětí za {RANGE_DAYS} dní {_num(band, 1, False)} %), ale skóre se za týden posunulo o {_num(s7)}. "
                         f"Typický přechod z range do trendu {'nahoru' if s7 > 0 else 'dolů'} — vstupuj až s reakcí ceny."),
            })
        s10 = None
        past10 = _value_at(points, now - dt.timedelta(days=14))
        if past10 is not None:
            s10 = cur - past10
        lim = DIVERGENCE_MIN_PCT.get(instrument, 1.5)
        if s10 is not None and ((price_chg >= lim and s10 <= -IDEA_POINTS) or (price_chg <= -lim and s10 >= IDEA_POINTS)):
            situations.append({
                "key": "divergence",
                "title": "Divergence ceny a skóre",
                "text": (f"Cena za {RANGE_DAYS} dní {_num(price_chg, 1)} %, ale skóre za 2 týdny {_num(s10)} — slábne fundamentální podpora "
                         f"pohybu. Hledej silnou supply/demand zónu pro protitrendový vstup; cílem je korekce nebo obrat."),
            })

    speed = ch["7d"]
    return {
        "current": cur,
        "changes": ch,
        "speed_text": ("skóre roste" if speed and speed > 0 else "skóre klesá" if speed and speed < 0 else "skóre se nemění"),
        "idea": idea,
        "situations": situations,
    }
