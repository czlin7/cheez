"""Formatting helpers. Direction is always carried by an arrow and a sign as well
as colour, so the report reads correctly without colour."""

from __future__ import annotations

import contextvars
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from markupsafe import Markup, escape

from ..models import SESSION_TEXT, Instrument, Price
from ..settings import CURRENCY_SYMBOL, ZERO_DECIMAL

NY = ZoneInfo("America/New_York")


@dataclass
class RenderOptions:
    """Per-render choices that filters need: the reader's timezone, the edition
    language, and how (or whether) to annotate prices in a second currency."""

    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo("Europe/London"))
    lang: str = "en"
    langs: tuple[str, ...] = ("en",)
    convert_to: str = ""  # "" = no server-side annotation (the page can still add it)
    per_usd: dict[str, float] = field(default_factory=dict)
    fx_mode: str = "ruby"  # ruby (web page) | inline (email: "(≈ £1.20)")
    translations: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def city(self) -> str:
        return str(self.tz).split("/")[-1].replace("_", " ")


_OPTS: contextvars.ContextVar[RenderOptions] = contextvars.ContextVar("cheez_render", default=RenderOptions())


def options() -> RenderOptions:
    return _OPTS.get()


def use(opts: RenderOptions):
    return _OPTS.set(opts)


def restore(token) -> None:
    _OPTS.reset(token)

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
    """'Live · 10:01 London (05:01 NY)', 'Close Mon 2 Nov', 'End of day Mon 2 Nov'."""
    if p is None:
        return ""
    label = SESSION_TEXT.get(p.session, p.session)
    if p.session in ("regular_close", "end_of_day"):
        tz = ZoneInfo(tz_hint) if tz_hint else NY
        return f"{label} {p.as_of.astimezone(tz):%a %-d %b}"
    o = options()
    t_ny = p.as_of.astimezone(NY)
    if str(o.tz) == "America/New_York":
        return f"{label} · {t_ny:%H:%M} New York"
    return f"{label} · {p.as_of.astimezone(o.tz):%H:%M} {o.city} ({t_ny:%H:%M} NY)"


def local(ts: Optional[datetime], fmt: str = "%a %-d %b %Y, %H:%M") -> str:
    """A timestamp in the reader's timezone, named."""
    if ts is None:
        return "—"
    o = options()
    return ts.astimezone(o.tz).strftime(fmt) + " " + o.city


# ---------------------------------------------------------------------------
# Prices, with an optional annotation in a second currency
# ---------------------------------------------------------------------------

SUFFIX = {"k": 1e3, "m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9, "tn": 1e12, "trillion": 1e12}
_PROSE_USD = re.compile(
    r"(?<![\w$])(?:US)?\$(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s?(k|m|million|bn|billion|tn|trillion)\b)?")


def converted(value: float, ccy: str, target: str, per_usd: dict[str, float], suffix: str = "") -> Optional[str]:
    """'≈ £112.30' (or None when no conversion applies)."""
    ccy, target = (ccy or "").upper(), (target or "").upper()
    if not target or target == ccy or ccy not in per_usd or target not in per_usd:
        return None
    v = value / per_usd[ccy] * per_usd[target]
    sym = CURRENCY_SYMBOL.get(target, target + " ")
    if suffix:
        return f"≈{sym}{v / SUFFIX[suffix]:,.1f}{suffix}"
    dp = 0 if target in ZERO_DECIMAL or abs(v) >= 10000 else 2
    return f"≈{sym}{v:,.{dp}f}"


def _price_markup(text: Markup, value: float, ccy: str, suffix: str = "") -> Markup:
    o = options()
    attrs = f'class="m" data-v="{value:.10g}" data-c="{escape(ccy)}"' + (f' data-s="{suffix}"' if suffix else "")
    alt = converted(value, ccy, o.convert_to, o.per_usd, suffix)
    if o.fx_mode == "inline":  # email: no ruby, which mail clients render unevenly
        return text + Markup(f' <span style="color:#92400e;font-size:0.85em">({escape(alt)})</span>') if alt else text
    rt = Markup(f"<rp>(</rp><rt>{escape(alt)}</rt><rp>)</rp>") if alt and o.fx_mode == "ruby" else ""
    return Markup(f"<ruby {attrs}>") + text + rt + Markup("</ruby>")


def px(v: Optional[float], ccy: Optional[str] = "USD", dp: Optional[int] = 2) -> Markup:
    """A price that the reader can see converted (ruby annotation)."""
    if v is None:
        return Markup("—")
    return _price_markup(escape(num(v, dp)), v, ccy or "USD")


def money_px(v: Optional[float], ccy: Optional[str] = None, dp: int = 0) -> Markup:
    if v is None:
        return Markup("—")
    return _price_markup(escape(money(v, ccy, dp)), v, ccy or "USD")


def wrap_prices(escaped: str) -> str:
    """Mark up dollar amounts in already-escaped prose so they can be converted."""

    def rep(m: re.Match) -> str:
        val = float(m.group(1).replace(",", ""))
        suf = (m.group(2) or "").lower()
        if suf:
            suf = {"million": "m", "billion": "bn", "trillion": "tn"}.get(suf, suf)
            val *= SUFFIX[suf]
        return str(_price_markup(Markup(m.group(0)), val, "USD", suf))

    return _PROSE_USD.sub(rep, escaped)


def tx(text: Optional[str]) -> Markup:
    """Editorial prose: shown in the edition language, carrying the other
    translations for the on-page switch, with dollar amounts convertible."""
    if text is None:
        return Markup("")
    from .. import i18n

    o = options()
    versions = {"en": wrap_prices(str(escape(text)))}
    for lang in o.langs:
        t = o.translations.get(lang, {}).get(text)
        if t:
            versions[lang] = wrap_prices(str(escape(t)))
    return i18n.span(versions, o.lang, html=True, langs=o.langs)


def ui(text: str) -> Markup:
    from .. import i18n

    o = options()
    return i18n.ui(text, o.lang, o.langs)


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
    "local": local,
    "px": px,
    "money_px": money_px,
    "tx": tx,
    "ui": ui,
    "newyork": newyork,
    "day": day,
    "pct": pct,
    "big_money": big_money,
    "kind_text": lambda k: KIND_TEXT.get(k, k),
    "action_text": lambda a: ui(ACTION_TEXT.get(a, a)),
    "direction": direction,
}
