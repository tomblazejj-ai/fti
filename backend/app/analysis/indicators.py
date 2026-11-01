"""Technical indicators — pure functions over lists, oldest value first.

Every function returns a list as long as its input; positions without enough history are None.
Definitions (the same as TradingView's built-ins unless noted):

  SMA(n)        arithmetic mean of the last n closes
  EMA(n)        alpha = 2/(n+1), seeded with the SMA of the first n values
  RMA(n)        Wilder's smoothing, alpha = 1/n, seeded with the SMA of the first n values
  RSI(n)        100 − 100/(1 + RMA(gains)/RMA(losses))                     (Wilder, n=14)
  MACD          EMA(12) − EMA(26); signal = EMA(9) of MACD; histogram = MACD − signal
  Stochastic    %K = SMA(k_smooth) of 100·(C − LL(n))/(HH(n) − LL(n)); %D = SMA(d) of %K  (14, 3, 3)
  ROC(n)        100·(C/C[n] − 1);  Momentum(n) = C − C[n]
  CCI(n)        (TP − SMA(TP))/(0.015 · mean absolute deviation of TP), TP = (H+L+C)/3   (n=20)
  TR            max(H − L, |H − C[1]|, |L − C[1]|);  ATR(n) = RMA(TR)            (n=14)
  ADX(n)        +DM/−DM (Wilder), +DI = 100·RMA(+DM)/ATR, DX = 100·|+DI − −DI|/(+DI + −DI), ADX = RMA(DX)
  Bollinger     SMA(n) ± k·σ (population σ of the last n closes)             (20, 2)
  Keltner       EMA(n) ± mult·ATR(atr_n)                                     (20, 2, 10)
  Supertrend    hl2 ± mult·ATR(n) bands with the usual ratchet rule          (10, 3)
  HV(n)         annualised σ of log returns, %                               (20, periods/year)
  VWAP          Σ(TP·V)/Σ(V) anchored to each UTC day — only with real traded volume
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Num = float | None


def sma(values: Sequence[float], n: int) -> list[Num]:
    out: list[Num] = [None] * len(values)
    if n <= 0:
        return out
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(values: Sequence[float], n: int) -> list[Num]:
    out: list[Num] = [None] * len(values)
    if n <= 0 or len(values) < n:
        return out
    alpha = 2 / (n + 1)
    prev = sum(values[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def rma(values: Sequence[Num], n: int) -> list[Num]:
    """Wilder's smoothing over a series that may start with None values."""
    out: list[Num] = [None] * len(values)
    start = next((i for i, v in enumerate(values) if v is not None), None)
    if start is None or len(values) - start < n:
        return out
    prev = sum(values[start:start + n]) / n  # type: ignore[arg-type]
    out[start + n - 1] = prev
    for i in range(start + n, len(values)):
        prev = (prev * (n - 1) + values[i]) / n  # type: ignore[operator]
        out[i] = prev
    return out


def _ema_opt(values: Sequence[Num], n: int) -> list[Num]:
    start = next((i for i, v in enumerate(values) if v is not None), None)
    out: list[Num] = [None] * len(values)
    if start is None:
        return out
    tail = ema([v for v in values[start:]], n)  # type: ignore[misc]
    out[start:] = tail
    return out


def rsi(closes: Sequence[float], n: int = 14) -> list[Num]:
    out: list[Num] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains: list[Num] = [None]
    losses: list[Num] = [None]
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    ag, al = rma(gains, n), rma(losses, n)
    for i in range(len(closes)):
        if ag[i] is None or al[i] is None:
            continue
        if al[i] == 0:
            out[i] = 100.0 if ag[i] > 0 else 50.0
        else:
            out[i] = 100 - 100 / (1 + ag[i] / al[i])
    return out


def macd(closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list[Num], list[Num], list[Num]]:
    ef, es = ema(closes, fast), ema(closes, slow)
    line: list[Num] = [a - b if a is not None and b is not None else None for a, b in zip(ef, es)]
    sig = _ema_opt(line, signal)
    hist: list[Num] = [a - b if a is not None and b is not None else None for a, b in zip(line, sig)]
    return line, sig, hist


def stochastic(highs, lows, closes, n: int = 14, k_smooth: int = 3, d: int = 3) -> tuple[list[Num], list[Num]]:
    raw: list[Num] = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        hh, ll = max(highs[i - n + 1:i + 1]), min(lows[i - n + 1:i + 1])
        raw[i] = 50.0 if hh == ll else 100 * (closes[i] - ll) / (hh - ll)
    k = _sma_opt(raw, k_smooth)
    return k, _sma_opt(k, d)


def _sma_opt(values: Sequence[Num], n: int) -> list[Num]:
    out: list[Num] = [None] * len(values)
    for i in range(n - 1, len(values)):
        window = values[i - n + 1:i + 1]
        if all(v is not None for v in window):
            out[i] = sum(window) / n  # type: ignore[arg-type]
    return out


def roc(closes: Sequence[float], n: int = 10) -> list[Num]:
    return [None if i < n or closes[i - n] == 0 else 100 * (closes[i] / closes[i - n] - 1) for i in range(len(closes))]


def momentum(closes: Sequence[float], n: int = 10) -> list[Num]:
    return [None if i < n else closes[i] - closes[i - n] for i in range(len(closes))]


def cci(highs, lows, closes, n: int = 20) -> list[Num]:
    tp = [(h + lo + c) / 3 for h, lo, c in zip(highs, lows, closes)]
    out: list[Num] = [None] * len(tp)
    for i in range(n - 1, len(tp)):
        w = tp[i - n + 1:i + 1]
        m = sum(w) / n
        md = sum(abs(x - m) for x in w) / n
        out[i] = 0.0 if md == 0 else (tp[i] - m) / (0.015 * md)
    return out


def true_range(highs, lows, closes) -> list[float]:
    out = []
    for i in range(len(closes)):
        if i == 0:
            out.append(highs[0] - lows[0])
        else:
            pc = closes[i - 1]
            out.append(max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc)))
    return out


def atr(highs, lows, closes, n: int = 14) -> list[Num]:
    return rma(true_range(highs, lows, closes), n)


def adx(highs, lows, closes, n: int = 14) -> tuple[list[Num], list[Num], list[Num]]:
    size = len(closes)
    plus_dm: list[Num] = [None]
    minus_dm: list[Num] = [None]
    tr: list[Num] = [None]
    for i in range(1, size):
        up, down = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        pc = closes[i - 1]
        tr.append(max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc)))
    atr_, pdm, mdm = rma(tr, n), rma(plus_dm, n), rma(minus_dm, n)
    pdi: list[Num] = [None] * size
    mdi: list[Num] = [None] * size
    dx: list[Num] = [None] * size
    for i in range(size):
        if atr_[i] in (None, 0) or pdm[i] is None or mdm[i] is None:
            continue
        pdi[i] = 100 * pdm[i] / atr_[i]
        mdi[i] = 100 * mdm[i] / atr_[i]
        s = pdi[i] + mdi[i]
        dx[i] = 0.0 if s == 0 else 100 * abs(pdi[i] - mdi[i]) / s
    return rma(dx, n), pdi, mdi


def bollinger(closes: Sequence[float], n: int = 20, k: float = 2.0) -> tuple[list[Num], list[Num], list[Num], list[Num]]:
    mid = sma(closes, n)
    up: list[Num] = [None] * len(closes)
    lo: list[Num] = [None] * len(closes)
    width: list[Num] = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        w = closes[i - n + 1:i + 1]
        m = mid[i]
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)  # type: ignore[operator]
        up[i], lo[i] = m + k * sd, m - k * sd  # type: ignore[operator]
        width[i] = (up[i] - lo[i]) / m if m else None  # type: ignore[operator]
    return mid, up, lo, width


def keltner(highs, lows, closes, n: int = 20, mult: float = 2.0, atr_n: int = 10) -> tuple[list[Num], list[Num], list[Num]]:
    mid = ema(closes, n)
    a = atr(highs, lows, closes, atr_n)
    up = [m + mult * x if m is not None and x is not None else None for m, x in zip(mid, a)]
    lo = [m - mult * x if m is not None and x is not None else None for m, x in zip(mid, a)]
    return mid, up, lo


def supertrend(highs, lows, closes, n: int = 10, mult: float = 3.0) -> tuple[list[Num], list[int | None]]:
    a = atr(highs, lows, closes, n)
    line: list[Num] = [None] * len(closes)
    direction: list[int | None] = [None] * len(closes)
    fu = fl = None
    for i in range(len(closes)):
        if a[i] is None:
            continue
        hl2 = (highs[i] + lows[i]) / 2
        bu, bl = hl2 + mult * a[i], hl2 - mult * a[i]
        if fu is None:
            fu, fl, d = bu, bl, 1
        else:
            fu = bu if bu < fu or closes[i - 1] > fu else fu
            fl = bl if bl > fl or closes[i - 1] < fl else fl
            d = direction[i - 1] or 1
            if d == 1 and closes[i] < fl:
                d = -1
            elif d == -1 and closes[i] > fu:
                d = 1
        direction[i] = d
        line[i] = fl if d == 1 else fu
    return line, direction


def hist_vol(closes: Sequence[float], n: int = 20, periods_per_year: float = 252) -> list[Num]:
    rets: list[Num] = [None] + [math.log(closes[i] / closes[i - 1]) if closes[i - 1] > 0 and closes[i] > 0 else None
                                for i in range(1, len(closes))]
    out: list[Num] = [None] * len(closes)
    for i in range(n, len(closes)):
        w = [r for r in rets[i - n + 1:i + 1] if r is not None]
        if len(w) < n:
            continue
        m = sum(w) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / (n - 1))
        out[i] = sd * math.sqrt(periods_per_year) * 100
    return out


def vwap_daily(times: Sequence[int], highs, lows, closes, volumes: Sequence[float | None]) -> list[Num]:
    """Session VWAP reset at 00:00 UTC. Only meaningful with real traded volume (exchange data)."""
    out: list[Num] = [None] * len(closes)
    day = None
    pv = vol = 0.0
    for i, t in enumerate(times):
        d = t // 86400
        if d != day:
            day, pv, vol = d, 0.0, 0.0
        v = volumes[i]
        if v is None or v <= 0:
            out[i] = pv / vol if vol else None
            continue
        tp = (highs[i] + lows[i] + closes[i]) / 3
        pv += tp * v
        vol += v
        out[i] = pv / vol
    return out


def last(values: Sequence[Num]) -> Num:
    for v in reversed(values):
        if v is not None:
            return v
    return None


def percentile_rank(values: Sequence[Num], x: float) -> float | None:
    """Share (0–100) of the non-empty values that are below x."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return 100 * sum(1 for v in vals if v < x) / len(vals)


def periods_per_year(tf: str) -> float:
    return {"M1": 252 * 1440, "M5": 252 * 288, "M15": 252 * 96, "M30": 252 * 48, "H1": 252 * 24, "H4": 252 * 6,
            "D1": 252, "W1": 52, "MN1": 12}.get(tf, 252)
