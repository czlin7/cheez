"""Deterministic price statistics used to ground (never replace) judgement.

These numbers give the model reference levels it must cite when proposing an
entry zone or an invalidation level. They describe past prices only; none of
them predicts anything.
"""

from __future__ import annotations

from datetime import date
from statistics import mean
from typing import Optional, Sequence

from ..models import Bar, Technicals


def sma(values: Sequence[float], n: int) -> Optional[float]:
    if len(values) < n:
        return None
    return mean(values[-n:])


def atr(bars: Sequence[Bar], n: int = 14) -> Optional[float]:
    if len(bars) < n + 1:
        return None
    trs: list[float] = []
    for prev, cur in zip(bars[:-1], bars[1:]):
        if cur.h is None or cur.l is None:
            return None
        trs.append(max(cur.h - cur.l, abs(cur.h - prev.c), abs(cur.l - prev.c)))
    return mean(trs[-n:])


def pivots(bars: Sequence[Bar], window: int = 5, kind: str = "low", lookback: int = 130) -> list[tuple[date, float]]:
    """Local extremes: a bar whose low (high) is the lowest (highest) within
    ``window`` bars on either side. Uses closes when intraday ranges are missing."""
    recent = list(bars[-lookback:])
    out: list[tuple[date, float]] = []
    for i in range(window, len(recent) - window):
        if kind == "low":
            v = recent[i].l if recent[i].l is not None else recent[i].c
            neigh = [(b.l if b.l is not None else b.c) for b in recent[i - window : i + window + 1]]
            if v == min(neigh):
                out.append((recent[i].d, round(v, 4)))
        else:
            v = recent[i].h if recent[i].h is not None else recent[i].c
            neigh = [(b.h if b.h is not None else b.c) for b in recent[i - window : i + window + 1]]
            if v == max(neigh):
                out.append((recent[i].d, round(v, 4)))
    return out[-6:]


def pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return (a / b - 1.0) * 100.0


def compute(bars: Sequence[Bar]) -> Technicals:
    bars = [b for b in bars if b.c is not None]
    if not bars:
        return Technicals()
    closes = [b.c for b in bars]
    last = bars[-1]
    year = bars[-252:]
    highs = [b.h if b.h is not None else b.c for b in year]
    lows = [b.l if b.l is not None else b.c for b in year]
    hi52 = max(highs)
    lo52 = min(lows)
    dv = [b.c * b.v for b in bars[-20:] if b.v]
    return Technicals(
        last_close=last.c,
        last_close_date=last.d,
        sma20=sma(closes, 20),
        sma50=sma(closes, 50),
        sma200=sma(closes, 200),
        high_52w=hi52,
        low_52w=lo52,
        high_20d=max(b.h if b.h is not None else b.c for b in bars[-20:]),
        low_20d=min(b.l if b.l is not None else b.c for b in bars[-20:]),
        atr14=atr(bars, 14),
        drawdown_from_52w_high_pct=pct(last.c, hi52),
        return_1m_pct=pct(last.c, closes[-22]) if len(closes) >= 22 else None,
        return_3m_pct=pct(last.c, closes[-64]) if len(closes) >= 64 else None,
        avg_dollar_volume_20d=mean(dv) if len(dv) >= 10 else None,
        swing_lows=pivots(bars, kind="low"),
        swing_highs=pivots(bars, kind="high"),
        history_days=len(bars),
    )


def fact_keys(t: Technicals) -> dict[str, float]:
    """Named reference levels the editorial may cite in ``PriceZone.basis``."""
    keys: dict[str, float] = {}
    for name in ("last_close", "sma20", "sma50", "sma200", "high_52w", "low_52w", "high_20d", "low_20d"):
        v = getattr(t, name)
        if v is not None:
            keys[name] = float(v)
    for d, v in t.swing_lows:
        keys[f"swing_low:{d.isoformat()}"] = float(v)
    for d, v in t.swing_highs:
        keys[f"swing_high:{d.isoformat()}"] = float(v)
    if t.atr14 is not None:
        keys["atr14"] = float(t.atr14)
    return keys
