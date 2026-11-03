"""Formatting helpers. Direction is always carried by an arrow and a sign as well
as colour, so the report reads correctly without colour."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from markupsafe import Markup, escape

from ..models import SESSION_TEXT, Instrument, Price

LONDON = ZoneInfo("Europe/London")
NY = ZoneInfo("America/New_York")

KIND_TEXT = {
    "index": "Index",
    "index_future": "Futures contract",
    "etf": "ETF",
    "stock": "Stock",
    "yield": "Yield",
    "fx": "Currency pair",
    "dollar_index": "Index (ICE futures-based)",
    "commodity_future": "Futures contract",
    "commodity_spot": "Spot price",
    "volatility_index": "Volatility index",
}

ACTION_TEXT = {
    "consider_buying": "Consider buying",
    "consider_adding": "Consider adding",
    "hold": "Hold",
    "consider_trimming": "Consider trimming",
    "consider_exiting": "Consider exiting",
    "wait": "Wait",
    "watch": "Watch",
}


def num(v: Optional[float], dp: Optional[int] = None) -> str:
    if v is None:
        return "—"
    if dp is None:
        a = abs(v)
        dp = 0 if a >= 10000 else 2 if a < 1000 else 1
        if a < 10:
            dp = 4 if a < 2 else 2
    s = f"{abs(v):,.{dp}f}"
    return ("−" if v < 0 else "") + s


def money(v: Optional[float], ccy: Optional[str] = None, dp: int = 0) -> str:
    if v is None:
        return "—"
    s = f"{abs(v):,.{dp}f}"
    sign = "−" if v < 0 else ""
    return f"{sign}{ccy + ' ' if ccy else ''}{s}"


def direction(v: Optional[float], eps: float = 1e-9) -> str:
    if v is None or abs(v) < eps:
        return "flat"
    return "up" if v > 0 else "down"


def change(v: Optional[float], unit: str = "%", dp: int = 2) -> Markup:
    """Signed change with arrow glyph and text equivalent."""
    if v is None:
        return Markup('<span class="flat">—</span>')
    d = direction(v, 0.5 * 10 ** (-dp))
    arrow = {"up": "▲", "down": "▼", "flat": "■"}[d]
    word = {"up": "up", "down": "down", "flat": "unchanged"}[d]
    sign = "+" if v > 0 else ("−" if v < 0 else "±")
    if unit == "bp":
        txt = f"{sign}{abs(v):.0f} bp"
    else:
        txt = f"{sign}{abs(v):.{dp}f}{unit}"
    return Markup(
        f'<span class="{d}"><span class="arrow" aria-hidden="true">{arrow}</span>'
        f'<span class="sr-only">{word} </span>{escape(txt)}</span>'
    )


def inst_change(i: Instrument) -> Markup:
    if i.kind == "yield":
        return change(i.change_bp, "bp")
    if i.kind == "fx":
        return change(i.change_pct, "%", 2)
    return change(i.change_pct, "%", 2)


def inst_level(i: Instrument) -> str:
    if not i.last:
        return "—"
    v = i.last.value
    if i.unit == "%":
        return f"{v:.2f}%"
    if i.kind == "fx":
        return f"{v:.4f}" if v < 20 else f"{v:.2f}"
    if i.unit in ("USD/bbl", "USD/oz", "USD/lb"):
        return f"${v:,.2f}"
    return num(v, 2 if v < 1000 else 0 if v >= 10000 else 1)


def when(p: Optional[Price], tz_hint: Optional[str] = None) -> str:
    """'Live 10:01 ET', 'Close Mon 2 Nov', 'End of day Mon 2 Nov'."""
    if p is None:
        return ""
    label = SESSION_TEXT.get(p.session, p.session)
    if p.session in ("regular_close", "end_of_day"):
        tz = ZoneInfo(tz_hint) if tz_hint else NY
        return f"{label} {p.as_of.astimezone(tz):%a %-d %b}"
    t_ny = p.as_of.astimezone(NY)
    t_ld = p.as_of.astimezone(LONDON)
    return f"{label} · {t_ld:%H:%M} London ({t_ny:%H:%M} NY)"


def london(ts: Optional[datetime], fmt: str = "%a %-d %b %Y, %H:%M") -> str:
    if ts is None:
        return "—"
    return ts.astimezone(LONDON).strftime(fmt) + " London"


def newyork(ts: Optional[datetime], fmt: str = "%H:%M") -> str:
    if ts is None:
        return "—"
    return ts.astimezone(NY).strftime(fmt) + " New York"


def day(d: Optional[date], fmt: str = "%a %-d %b %Y") -> str:
    return d.strftime(fmt) if d else "—"


def pct(v: Optional[float], dp: int = 1) -> str:
    if v is None:
        return "—"
    return f"{v:.{dp}f}%"


def big_money(v: Optional[float]) -> str:
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1e12:
        return f"${v / 1e12:.1f}tn"
    if a >= 1e9:
        return f"${v / 1e9:.1f}bn"
    if a >= 1e6:
        return f"${v / 1e6:.0f}m"
    return f"${v:,.0f}"


FILTERS = {
    "num": num,
    "money": money,
    "change": change,
    "inst_change": inst_change,
    "inst_level": inst_level,
    "when": when,
    "london": london,
    "newyork": newyork,
    "day": day,
    "pct": pct,
    "big_money": big_money,
    "kind_text": lambda k: KIND_TEXT.get(k, k),
    "action_text": lambda a: ACTION_TEXT.get(a, a),
    "direction": direction,
}
