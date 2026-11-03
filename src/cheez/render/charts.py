"""Server-side SVG line charts: one series per chart, labelled axes, explicit
time range, optional entry zone and invalidation line. A small script adds a
crosshair tooltip; the chart is complete without it."""

from __future__ import annotations

import html
import json
import math
from datetime import date
from typing import Callable, Optional, Sequence


def nice_step(span: float, target: int = 4) -> float:
    if span <= 0:
        return 1.0
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def ticks(lo: float, hi: float, target: int = 4) -> list[float]:
    step = nice_step(hi - lo, target)
    start = math.floor(lo / step) * step
    out = []
    v = start
    while v <= hi + step * 0.001:
        if v >= lo - step * 0.001:
            out.append(round(v, 10))
        v += step
    return out


def default_fmt(v: float) -> str:
    a = abs(v)
    if a >= 10000:
        return f"{v:,.0f}"
    if a >= 100:
        return f"{v:,.0f}"
    if a >= 10:
        return f"{v:,.1f}"
    return f"{v:,.2f}"


def line_chart(
    points: Sequence[tuple[date, float]],
    *,
    width: int = 640,
    height: int = 220,
    fmt: Callable[[float], str] = default_fmt,
    zone: Optional[tuple[float, float]] = None,
    inval: Optional[float] = None,
    label: str = "",
    compact: bool = False,
) -> str:
    pts = [(d, float(v)) for d, v in points if v is not None]
    if len(pts) < 2:
        return '<p class="small muted">Not enough history to chart.</p>'
    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    extra = [x for x in ([zone[0], zone[1]] if zone else []) + ([inval] if inval is not None else [])]
    if extra:
        lo, hi = min(lo, *extra), max(hi, *extra)
    pad = (hi - lo) * 0.08 or abs(hi) * 0.02 or 1
    lo, hi = lo - pad, hi + pad
    yt = ticks(lo, hi, 3 if compact else 4)
    lo, hi = min(lo, yt[0]), max(hi, yt[-1])
    if fmt is default_fmt:
        step = yt[1] - yt[0] if len(yt) > 1 else 1.0
        dp = 0 if step >= 1 else 1 if step >= 0.1 else 2 if step >= 0.01 else 3
        fmt = lambda v, _dp=dp: f"{v:,.{_dp}f}"  # noqa: E731 - one decimal style per axis

    left = 8
    right_label = 56 if not compact else 8
    # y labels sit on the left; measure the widest roughly (6.2px per char at 11px)
    ylab_w = max(len(fmt(t)) for t in yt) * 6.4 + 8
    x0, x1 = left + ylab_w, width - right_label
    y0, y1 = 10, height - 24
    n = len(pts)

    def X(i: int) -> float:
        return x0 + (x1 - x0) * i / (n - 1)

    def Y(v: float) -> float:
        return y1 - (y1 - y0) * (v - lo) / (hi - lo)

    parts: list[str] = []
    parts.append(f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(label)}" '
                 f'preserveAspectRatio="xMidYMid meet">')
    # grid + y axis labels
    parts.append('<g class="grid">')
    for t in yt:
        y = Y(t)
        parts.append(f'<line x1="{x0:.1f}" x2="{x1:.1f}" y1="{y:.1f}" y2="{y:.1f}"/>')
    parts.append("</g><g class=\"axis\">")
    for t in yt:
        parts.append(f'<text x="{x0 - 6:.1f}" y="{Y(t) + 4:.1f}" text-anchor="end">{html.escape(fmt(t))}</text>')
    # x labels: first, month starts, last
    seen_months: set[tuple[int, int]] = set()
    xlabels: list[tuple[float, str, str]] = []
    for i, (d, _) in enumerate(pts):
        key = (d.year, d.month)
        if i == 0:
            seen_months.add(key)
            continue
        if key not in seen_months:
            seen_months.add(key)
            xlabels.append((X(i), d.strftime("%b"), "middle"))
    first_d, last_d = pts[0][0], pts[-1][0]
    xlabels.insert(0, (x0, first_d.strftime("%-d %b"), "start"))
    xlabels.append((x1, last_d.strftime("%-d %b"), "end"))
    # drop month labels that would collide with the end labels
    keep: list[tuple[float, str, str]] = []
    for x, t, a in xlabels:
        if a == "middle" and (x - x0 < 46 or x1 - x < 46):
            continue
        keep.append((x, t, a))
    for x, t, a in keep:
        parts.append(f'<text x="{x:.1f}" y="{height - 6}" text-anchor="{a}">{html.escape(t)}</text>')
    parts.append("</g>")

    if zone:
        za, zb = Y(zone[1]), Y(zone[0])
        parts.append(f'<rect class="zone" x="{x0:.1f}" y="{za:.1f}" width="{x1 - x0:.1f}" height="{max(zb - za, 1.5):.1f}"/>')
        parts.append(f'<line class="zone-edge" x1="{x0:.1f}" x2="{x1:.1f}" y1="{za:.1f}" y2="{za:.1f}"/>')
        parts.append(f'<line class="zone-edge" x1="{x0:.1f}" x2="{x1:.1f}" y1="{zb:.1f}" y2="{zb:.1f}"/>')
        parts.append(f'<text class="zone-lbl" x="{x0 + 6:.1f}" y="{za - 4:.1f}">Entry zone</text>')
    if inval is not None:
        yi = Y(inval)
        parts.append(f'<line class="inval" x1="{x0:.1f}" x2="{x1:.1f}" y1="{yi:.1f}" y2="{yi:.1f}"/>')
        parts.append(f'<text class="inval-lbl" x="{x0 + 6:.1f}" y="{yi + 14:.1f}">Invalidation {html.escape(fmt(inval))}</text>')

    path = " ".join(f"{'M' if i == 0 else 'L'}{X(i):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(pts))
    area = path + f" L{X(n - 1):.1f},{y1:.1f} L{X(0):.1f},{y1:.1f} Z"
    parts.append(f'<path class="area" d="{area}"/>')
    parts.append(f'<path class="line" d="{path}"/>')
    lx, ly = X(n - 1), Y(pts[-1][1])
    parts.append(f'<circle class="dot" cx="{lx:.1f}" cy="{ly:.1f}" r="4"/>')
    if not compact:
        parts.append(f'<text class="end" x="{lx + 8:.1f}" y="{ly + 4:.1f}">{html.escape(fmt(pts[-1][1]))}</text>')
    parts.append("</svg>")
    data = json.dumps({
        "x0": round(x0, 1), "x1": round(x1, 1), "y0": y0, "y1": y1, "lo": lo, "hi": hi, "w": width, "h": height,
        "p": [[d.isoformat(), round(v, 4)] for d, v in pts],
    }, separators=(",", ":"))
    return f'<div class="svgbox" data-chart=\'{html.escape(data, quote=True)}\'>' + "".join(parts) + "</div>"
