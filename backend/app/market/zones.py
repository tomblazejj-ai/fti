"""Supply & demand zones on the weekly and daily chart — the Funded Mind swing strategy.

How the strategy reads a chart (Funded Mind video on the swing strategy, 2026-10):
  * start on the WEEKLY chart — the nearest supply above the price and demand below it
  * refine on the DAILY chart — daily zones inside the weekly ones give the precise entry
  * a zone is the area a sharp move started from: big players could not fill their whole
    order at once, the rest waits there and the price reacts when it comes back. Found as
    a small "base" candle followed by an impulse away from it
  * places where the market turned repeatedly (pivots) make a zone stronger
  * a zone needs trading activity behind it (volume profile, POC). Exchange futures volume
    is not available for free, so the time the price spent at each level (a TPO profile
    built from the candles) stands in for it — and the UI says so

Every threshold is fixed and in ATR(14) of the timeframe, so it fits any market and any
price level.
"""

from __future__ import annotations

import statistics

from app.connectors.kraken import Candle

IMPULSE_ATR = 1.25  # the move away from the base within 1–3 candles
IMPULSE_BODY_ATR = 0.5  # the first impulse candle must have a real body
BASE_MAX_ATR = 1.2  # the base itself is not a big candle
MIN_ZONE_ATR = 0.15  # thinner zones are widened to this
MAX_ZONE_ATR = 1.2  # wider zones are trimmed on the side facing the price
DEPARTURE_BARS = 5  # how far the price ran from the zone is measured over this many candles
PIVOT_WINDOW = 2
TPO_BINS = 240
ACTIVE_RATIO = 1.0  # time spent in the zone vs. the profile average: ≥ 1 = clear activity
SOME_RATIO = 0.6
KEEP = 4  # zones per side and timeframe in the output


def atr_series(c: list[Candle], n: int = 14) -> list[float | None]:
    """Wilder ATR for every candle (None until there is enough history)."""
    out: list[float | None] = [None] * len(c)
    if len(c) <= n:
        return out
    trs = [c[0].high - c[0].low] + [
        max(c[i].high - c[i].low, abs(c[i].high - c[i - 1].close), abs(c[i].low - c[i - 1].close)) for i in range(1, len(c))
    ]
    a = sum(trs[1:n + 1]) / n
    out[n] = a
    for i in range(n + 1, len(c)):
        a = (a * (n - 1) + trs[i]) / n
        out[i] = a
    return out


def _pivots(c: list[Candle], w: int = PIVOT_WINDOW) -> list[float]:
    """Prices of swing highs and lows (a candle higher/lower than `w` candles on each side)."""
    out = []
    for i in range(w, len(c) - w):
        if all(c[i].high >= c[j].high for j in range(i - w, i + w + 1)):
            out.append(c[i].high)
        if all(c[i].low <= c[j].low for j in range(i - w, i + w + 1)):
            out.append(c[i].low)
    return out


def tpo_profile(c: list[Candle], bins: int = TPO_BINS) -> dict | None:
    """Time-at-price: every candle spreads one unit of time evenly over its high–low range."""
    if len(c) < 20:
        return None
    lo, hi = min(x.low for x in c), max(x.high for x in c)
    if hi <= lo:
        return None
    width = (hi - lo) / bins
    dens = [0.0] * bins
    for x in c:
        i0 = min(bins - 1, int((x.low - lo) / width))
        i1 = min(bins - 1, int((x.high - lo) / width))
        share = 1.0 / (i1 - i0 + 1)
        for i in range(i0, i1 + 1):
            dens[i] += share
    filled = [d for d in dens if d > 0]
    return {"lo": lo, "width": width, "dens": dens, "avg": statistics.mean(filled) if filled else 0.0}


def zone_activity(profile: dict | None, z_lo: float, z_hi: float) -> tuple[float | None, float | None]:
    """(time in the zone vs. the profile average, price of the busiest level inside the zone)."""
    if not profile or not profile["avg"]:
        return None, None
    lo, w, dens = profile["lo"], profile["width"], profile["dens"]
    i0 = max(0, int((z_lo - lo) / w))
    i1 = min(len(dens) - 1, int((z_hi - lo) / w))
    if i1 < i0:
        return None, None
    inside = dens[i0:i1 + 1]
    k = max(range(len(inside)), key=lambda j: inside[j])
    poc = min(max(lo + (i0 + k + 0.5) * w, z_lo), z_hi)  # the bin centre can spill over the zone edge
    return statistics.mean(inside) / profile["avg"], poc


def find_zones(c: list[Candle], tf: str) -> list[dict]:
    """Every still valid (not closed through) supply and demand zone, oldest first."""
    atrs = atr_series(c)
    found: list[dict] = []
    for b in range(15, len(c) - 1):
        a = atrs[b]
        if not a:
            continue
        base = c[b]
        if base.high - base.low > BASE_MAX_ATR * a:
            continue
        for k in (1, 2, 3):
            if b + k >= len(c) - 1:  # the last candle is still forming
                break
            seg = c[b + 1:b + k + 1]
            first, last = seg[0], seg[-1]
            kind = None
            if (first.close - first.open >= IMPULSE_BODY_ATR * a and last.close > base.high
                    and max(x.high for x in seg) - base.high >= IMPULSE_ATR * a):
                kind = "demand"
            elif (first.open - first.close >= IMPULSE_BODY_ATR * a and last.close < base.low
                  and base.low - min(x.low for x in seg) >= IMPULSE_ATR * a):
                kind = "supply"
            if not kind:
                continue
            if kind == "demand":
                distal = min(base.low, first.low)
                proximal = max(base.open, base.close)
            else:
                distal = max(base.high, first.high)
                proximal = min(base.open, base.close)
            width = abs(proximal - distal)
            width = min(max(width, MIN_ZONE_ATR * a), MAX_ZONE_ATR * a)
            proximal = distal + width if kind == "demand" else distal - width
            after = c[b + 1:b + 1 + DEPARTURE_BARS]
            departure = ((max(x.high for x in after) - proximal) if kind == "demand" else (proximal - min(x.low for x in after))) / a
            found.append({"tf": tf, "kind": kind, "distal": distal, "proximal": proximal, "start": b, "ready": b + k + 1,
                          "formed": base.time.isoformat(), "atr": a, "departure": departure,
                          "base_atr": (base.high - base.low) / a})
            break

    pivots = _pivots(c)
    valid = []
    for z in found:
        lo, hi = sorted((z["distal"], z["proximal"]))
        broken, touches, inside_prev, last_touch = False, 0, False, None
        for idx in range(z["ready"], len(c)):
            x = c[idx]
            closed = idx < len(c) - 1  # only a finished candle can close through a zone
            if closed and ((z["kind"] == "demand" and x.close < z["distal"]) or (z["kind"] == "supply" and x.close > z["distal"])):
                broken = True
                break
            inside = x.low <= hi if z["kind"] == "demand" else x.high >= lo
            if inside and not inside_prev:
                touches += 1
                last_touch = x.time.isoformat()
            inside_prev = inside
        if broken:
            continue
        tol = 0.25 * z["atr"]
        piv = sum(1 for p in pivots if lo - tol <= p <= hi + tol)
        strength = (min(z["departure"] / 4, 1.0) * 40 + {0: 30, 1: 18, 2: 8}.get(touches, 0)
                    + max(0.0, 1 - z["base_atr"] / BASE_MAX_ATR) * 10 + min(piv, 3) / 3 * 20)
        valid.append({**z, "lo": lo, "hi": hi, "touches": touches, "fresh": touches == 0, "last_touch": last_touch,
                      "pivots": piv, "strength": round(strength)})

    # overlapping zones of the same kind: keep the stronger one
    valid.sort(key=lambda z: -z["strength"])
    kept: list[dict] = []
    for z in valid:
        if not any(k["kind"] == z["kind"] and z["lo"] <= k["hi"] and k["lo"] <= z["hi"] for k in kept):
            kept.append(z)
    kept.sort(key=lambda z: z["start"])
    return kept


def _public(z: dict, price: float, profile: dict | None, digits: int) -> dict:
    ratio, poc = zone_activity(profile, z["lo"], z["hi"])
    if z["kind"] == "demand":
        dist = 0.0 if z["lo"] <= price <= z["hi"] else (price - z["proximal"]) / price * 100
    else:
        dist = 0.0 if z["lo"] <= price <= z["hi"] else (z["proximal"] - price) / price * 100
    activity = None if ratio is None else "active" if ratio >= ACTIVE_RATIO else "some" if ratio >= SOME_RATIO else "none"
    return {
        "tf": z["tf"], "kind": z["kind"],
        "lo": round(z["lo"], digits), "hi": round(z["hi"], digits),
        "proximal": round(z["proximal"], digits), "distal": round(z["distal"], digits),
        "formed": z["formed"], "touches": z["touches"], "fresh": z["fresh"], "last_touch": z["last_touch"],
        "pivots": z["pivots"], "strength": z["strength"], "departure_atr": round(z["departure"], 1),
        "distance_pct": round(dist, 2), "inside": z["lo"] <= price <= z["hi"],
        "activity": activity, "activity_ratio": round(ratio, 2) if ratio is not None else None,
        "poc": round(poc, digits) if poc is not None else None,
    }


def analyze(weekly: list[Candle], daily: list[Candle], price: float | None, digits: int = 2) -> dict | None:
    """Nearest zones on W1 and D1 around `price`; daily zones are marked when they sit
    inside a weekly zone of the same kind (the strategy's "refine on the daily chart")."""
    if not daily or price is None:
        return None
    out: dict = {"price": round(price, digits), "atr_d1": None, "tf": {}}
    d_atr = atr_series(daily)
    out["atr_d1"] = round(d_atr[-1], digits) if d_atr and d_atr[-1] else None
    weekly_zones = find_zones(weekly, "W1") if len(weekly) >= 30 else []
    for tf, candles, zones in (("W1", weekly, weekly_zones), ("D1", daily, find_zones(daily, "D1"))):
        if len(candles) < 30:
            continue
        profile = tpo_profile(candles)
        demand = sorted((z for z in zones if z["kind"] == "demand" and z["lo"] <= price), key=lambda z: price - z["proximal"])
        supply = sorted((z for z in zones if z["kind"] == "supply" and z["hi"] >= price), key=lambda z: z["proximal"] - price)
        pub = {"demand": [_public(z, price, profile, digits) for z in demand[:KEEP]],
               "supply": [_public(z, price, profile, digits) for z in supply[:KEEP]]}
        if tf == "D1":
            for side in ("demand", "supply"):
                for z in pub[side]:
                    z["in_weekly"] = any(w["kind"] == z["kind"] and z["lo"] <= w["hi"] and w["lo"] <= z["hi"] for w in weekly_zones)
        out["tf"][tf] = pub
    out["method"] = ("Zóna = malá „základna“ před prudkým pohybem (aspoň 1,25× ATR během 1–3 svíček), dokud ji cena neprorazila "
                     "závěrem. Síla: jak daleko cena od zóny utekla, kolikrát se do ní vrátila (čerstvá = nejlepší), "
                     "kolikrát se tu trh otočil. Aktivita = kolik času cena na úrovni strávila (TPO profil) — objem z futures "
                     "není zdarma, proto náhrada.")
    return out
