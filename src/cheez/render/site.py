"""Assemble the view model and render the edition and the publishable page."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from .. import session as sess
from ..analytics import ledger as ledger_mod
from ..analytics.portfolio import FxBook, account_view, holdings_index
from ..config import GROUP_ORDER, INSTRUMENTS
from ..editorial.validate import IdeaDerived, ValidationReport
from ..models import Editorial, MarketSnapshot, PortfolioSnapshot, RunRecord, StockFacts
from ..state import State, archive_templates, state_script
from . import charts
from .format import FILTERS, LONDON, NY

HERE = Path(__file__).parent
UTC = timezone.utc


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(HERE / "templates")),
        autoescape=select_autoescape(["html", "j2"]),
        undefined=StrictUndefined,
        trim_blocks=False,
        lstrip_blocks=False,
    )
    env.filters.update(FILTERS)
    env.filters["abs"] = abs
    return env


@dataclass
class EditionMeta:
    id: str
    date: Any
    kind_label: str
    published_at: datetime
    data_cutoff: datetime
    status: str  # complete | partial | closed | failed | demo
    problems: list[str] = field(default_factory=list)
    demo: bool = False
    revision: int = 1
    read_minutes: Optional[int] = None
    closed_headline: str = ""
    next_expected: Optional[datetime] = None


def session_text(ctx) -> str:
    if not ctx.is_trading_day:
        nxt = ctx.next_session
        return f"US markets closed today · next session {nxt:%a %-d %b}" if nxt else "US markets closed today"
    o = ctx.open_utc
    if ctx.phase == "pre_open":
        return f"US pre-market · opens {o.astimezone(LONDON):%H:%M} London ({o.astimezone(NY):%H:%M} New York)"
    if ctx.phase == "regular":
        return f"US regular session in progress (opened {o.astimezone(LONDON):%H:%M} London)"
    if ctx.phase == "post_close":
        return "US regular session closed · after-hours trading"
    return "US overnight session"


def next_expected_edition(edition_date, scheduled_ny_time: tuple[int, int] = (8, 30)) -> datetime:
    """When the edition after this one should exist: the next NYSE session after
    ``edition_date`` at the scheduled publication time (New York)."""
    d = sess.next_session(edition_date)
    return datetime(d.year, d.month, d.day, scheduled_ny_time[0], scheduled_ny_time[1], tzinfo=NY).astimezone(UTC)


def _read_minutes(ed: Optional[Editorial]) -> Optional[int]:
    if not ed:
        return None
    text = " ".join(
        [ed.headline, ed.dek, ed.market_read.summary]
        + [d.summary + " " + d.why_it_matters for d in ed.developments]
        + [f.catalyst + " " + f.why_attention + " " + f.interpretation for f in ed.featured]
        + [i.thesis + " " + i.why_now + " " + i.counter_argument for i in ed.ideas]
        + ([ed.portfolio.summary] if ed.portfolio else [])
    )
    words = len(re.findall(r"\w+", text))
    return max(2, round(words / 230) + 2)  # +2 for tables and charts


def _market_charts(m: MarketSnapshot) -> dict:
    by_key = {i.key: i for i in m.instruments}
    out: dict[str, Any] = {"hero": None, "small": []}
    spx = by_key.get("spx")
    if spx and len(spx.history) > 5:
        pts = [(b.d, b.c) for b in spx.history]
        out["hero"] = {
            "title": "S&P 500, daily close",
            "sub": f"{pts[0][0]:%-d %b} – {pts[-1][0]:%-d %b %Y} · index points",
            "svg": charts.line_chart(pts, width=760, height=230, label="S&P 500 daily close"),
        }
    for key, title, unit in (("ust10y", "US 10-year Treasury yield", "%, official daily close"),
                             ("dxy", "US Dollar Index", "index points"),
                             ("wti", "WTI crude oil, front month", "USD per barrel"),
                             ("gold", "Gold, front-month future", "USD per troy ounce")):
        i = by_key.get(key)
        if i and len(i.history) > 5:
            pts = [(b.d, b.c) for b in i.history]
            fmt = (lambda v: f"{v:.2f}%") if unit.startswith("%") else charts.default_fmt
            out["small"].append({
                "title": title,
                "sub": f"{pts[0][0]:%-d %b} – {pts[-1][0]:%-d %b} · {unit}",
                "svg": charts.line_chart(pts, width=360, height=170, fmt=fmt, label=title, compact=True),
            })
    return out


def _portfolio_view(p: Optional[PortfolioSnapshot]) -> dict:
    if p is None or p.status == "unconfigured":
        return {"available": False, "title": "Portfolio connection not set up",
                "message": (p.messages[0] if p and p.messages else "No Longbridge connection is configured.")
                + " See docs/SETUP.md for the one-time read-only authorisation.",
                "aside": "Awaiting setup", "accounts": [], "messages": []}
    if p.status in ("error", "stale") or not p.accounts:
        return {"available": False, "title": "Portfolio data unavailable today",
                "message": " ".join(p.messages) or "The brokerage snapshot failed.",
                "aside": "Not available", "accounts": [], "messages": []}
    fx = FxBook.from_rates(p.fx)
    views = [account_view(a, fx) for a in p.accounts]
    aside = ("Demonstration data" if p.demo else f"Longbridge, read-only · as of {p.as_of.astimezone(LONDON):%H:%M} London"
             if p.as_of else "Longbridge, read-only")
    msgs = list(p.messages)
    for r in p.fx:
        msgs.append(f"FX used: 1 {r.pair[:3]} = {r.rate:.4f} {r.pair[3:]} ({r.source}, {r.as_of.astimezone(LONDON):%H:%M} London).")
    for a in p.accounts:
        if a.margin_or_financing_note:
            msgs.append(a.margin_or_financing_note)
    return {"available": True, "title": "", "message": "", "aside": aside, "accounts": views, "messages": msgs}


def _feasibility(idea, facts: Optional[StockFacts], p: Optional[PortfolioSnapshot]) -> Optional[str]:
    if p is None or p.status not in ("ok", "partial") or not p.accounts:
        return None
    if idea.action not in ("consider_buying", "consider_adding") or idea.entry is None:
        return None
    ccy = facts.currency if facts else "USD"
    avail = 0.0
    seen = False
    for a in p.accounts:
        for c in a.cash:
            if c.currency == ccy and c.available is not None:
                avail += c.available
                seen = True
    mid = (idea.entry.low + idea.entry.high) / 2
    if not seen or avail <= 0:
        return (f"No free {ccy} cash is shown in the account; acting would first need a currency conversion or a deposit, "
                "with conversion costs. Margin buying power is not counted.")
    shares = int(avail // mid)
    return (f"Free {ccy} cash of about {avail:,.0f} would cover roughly {shares:,} shares at the zone midpoint before fees. "
            "This is an arithmetic ceiling, not a suggested size; sizing waits for configured risk preferences.")


def build_view(
    *,
    edition: EditionMeta,
    market: MarketSnapshot,
    stocks: dict[str, StockFacts],
    editorial: Optional[Editorial],
    report: Optional[ValidationReport],
    portfolio: Optional[PortfolioSnapshot],
    state: State,
    run: RunRecord,
    previous: Optional[dict] = None,
) -> dict:
    groups = []
    order = {g: i for i, g in enumerate(GROUP_ORDER)}
    by_group: dict[str, list] = {}
    for i in market.instruments:
        by_group.setdefault(i.group, []).append(i)
    for g in sorted(by_group, key=lambda x: order.get(x, 99)):
        groups.append((g, by_group[g]))
    inst_labels = {i.key: i.label for i in market.instruments}
    held = holdings_index(portfolio)
    ideas = []
    if editorial:
        for idea in editorial.ideas:
            f = stocks.get(idea.symbol.upper())
            der = (report.derived.get(idea.idea_id) if report else None) or IdeaDerived()
            chart = None
            rng = ""
            if f and len(f.history) > 20:
                hist = f.history[-126:]
                pts = [(b.d, b.c) for b in hist]
                chart = charts.line_chart(
                    pts, width=720, height=240,
                    zone=(idea.entry.low, idea.entry.high) if idea.entry else None,
                    inval=idea.invalidation.level if idea.invalidation else None,
                    label=f"{idea.symbol} daily close with entry zone and invalidation level",
                    fmt=lambda v: f"{v:,.2f}" if abs(v) < 1000 else f"{v:,.0f}",
                )
                rng = f"{pts[0][0]:%-d %b} – {pts[-1][0]:%-d %b %Y} · {f.currency}"
            ideas.append({"idea": idea, "derived": der, "facts": f, "chart": chart, "chart_range": rng,
                          "feasibility": _feasibility(idea, f, portfolio)})
    sources = list(market.sources)
    method_notes = [
        "Index levels are index values, not ETF prices; futures rows are futures contracts and trade almost around the clock, "
        "so they move before cash markets open. Each row states which session its price comes from and what its change is measured against.",
        "Yahoo Finance public chart data is not an exchange-licensed feed and may be delayed; the US Treasury curve is official end-of-day data; "
        "ticker identities are checked against Nasdaq Trader's listed-securities directory; earnings dates come from Nasdaq.com and may be estimates.",
        "Technical reference levels (moving averages, 20-day and 52-week ranges, swing highs and lows, average true range) describe past prices. "
        "They help locate an entry zone or an invalidation level; they do not predict anything.",
    ]
    if portfolio and portfolio.status in ("ok", "partial"):
        method_notes.append("Portfolio data is read through a read-only Longbridge connection (OAuth scopes account.read and trade.read only). "
                            "Cheez cannot place, change or cancel orders, move money or edit watchlists or alerts.")
    return {
        "edition": edition,
        "session": market.session,
        "session_text": session_text(market.session),
        "market": market,
        "groups": groups,
        "inst_labels": inst_labels,
        "charts": _market_charts(market),
        "editorial": editorial,
        "stocks": {k.upper(): v for k, v in stocks.items()},
        "held": held,
        "ideas": ideas,
        "portfolio": _portfolio_view(portfolio),
        "ledger": {"entries": sorted(state.ledger.entries, key=lambda e: e.first_published, reverse=True)[:40],
                   "summary": ledger_mod.summary(state.ledger)},
        "run": run,
        "sources": sources,
        "method_notes": method_notes,
        "warnings": (report.warnings if report else []),
        "previous": previous,
    }


def render_edition_body(view: dict) -> str:
    return _env().get_template("edition.html.j2").render(v=view)


def render_page(*, body: str, view: dict, document: bool, archive: Optional[list[dict]], extra_tail: str = "",
                home_href: str = "#latest") -> str:
    env = _env()
    css = (HERE / "static" / "cheez.css").read_text()
    js = (HERE / "static" / "cheez.js").read_text()
    ed: EditionMeta = view["edition"]
    nxt = ed.next_expected.isoformat() if ed.next_expected else ""
    title = "Cheez Daily" if archive is not None else f"Cheez Daily {ed.date:%-d %b %Y}"
    html = env.get_template("page.html.j2").render(
        title=title,
        document=document,
        css=css,
        js=js,
        body=body,
        edition_id=ed.id,
        next_expected=nxt,
        archive=archive,
        has_editorial=view["editorial"] is not None,
        has_featured=bool(view["editorial"] and view["editorial"].featured),
        generated=ed.published_at.astimezone(LONDON).strftime("%-d %b %Y %H:%M London"),
        home_href=home_href,
    )
    if extra_tail:
        marker = "<script>"
        idx = html.rfind(marker)
        html = html[:idx] + extra_tail + "\n" + html[idx:]
    return html


STATUS_LABEL = {"complete": "Complete", "partial": "Partial data", "closed": "Market closed", "failed": "Failed", "demo": "Demo"}


def assemble_index(*, body: str, view: dict, state: State, archive_items: list[tuple[str, str]], document: bool) -> str:
    ed: EditionMeta = view["edition"]
    archive = []
    for e in sorted(state.editions, key=lambda x: (x.date, x.published_at), reverse=True):
        if e.id == ed.id:
            continue
        archive.append({"id": e.id, "date_label": e.date.strftime("%a %-d %b %Y"), "headline": e.headline,
                        "status": e.status, "status_label": STATUS_LABEL.get(e.status, e.status)})
    tail = archive_templates(archive_items) + "\n" + state_script(state)
    return render_page(body=body, view=view, document=document, archive=archive, extra_tail=tail)
