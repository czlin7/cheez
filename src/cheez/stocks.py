"""Per-stock facts: verified identity, labelled prices, technical reference levels,
liquidity and the next earnings date."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from . import session as sess
from .analytics.technicals import compute
from .models import Price, StockFacts
from .net import Fetcher
from .sources import nasdaq, yahoo
from .sources.symbols import SymbolDirectory


def stock_facts(f: Fetcher, ticker: str, now: datetime, directory: Optional[SymbolDirectory]) -> StockFacts:
    t = ticker.upper().strip()
    ident = directory.identify(t) if directory else None
    q = yahoo.live_quote(f, t, prepost=True)
    if ident is None:
        from .models import Identity

        ident = Identity(symbol=t, name=q.name, exchange=q.exchange, verified_by="provider_name_only",
                         note="Symbol directory unavailable; identity from price provider only.")
    elif ident.ambiguous and q.name:
        ident.note = (ident.note or "") + f" Price provider name: {q.name} ({q.exchange})."
    facts = StockFacts(identity=ident, currency=q.currency or "USD", source="yahoo",
                       delay_note="Yahoo Finance public data; US stock prices are typically real-time or near real-time "
                                  "for the regular session, extended-hours prints may be thin.")
    if q.regular_price is not None and q.regular_time is not None:
        label = sess.us_equity_session_label(q.regular_time)
        # Outside the regular session the 'regular' price is the last close.
        if label != "regular_live":
            label = "regular_close"
        facts.regular_close = Price(value=float(q.regular_price), as_of=q.regular_time, session=label)  # type: ignore[arg-type]
        facts.last = facts.regular_close
    if q.ext_price is not None and q.ext_time is not None and q.ext_kind:
        facts.last = Price(value=float(q.ext_price), as_of=q.ext_time, session=q.ext_kind)  # type: ignore[arg-type]
    if facts.last and q.previous_close:
        ref = q.previous_close if facts.last.session in ("regular_live", "pre_market") else q.regular_price
        if facts.last.session == "regular_close":
            ref = q.previous_close
        if ref:
            facts.change_pct_vs_close = (facts.last.value / ref - 1) * 100
    try:
        bars = yahoo.daily_bars(f, t, "1y")
        facts.history = bars
        facts.technicals = compute(bars)
    except Exception as e:
        facts.notes.append(f"Price history unavailable: {type(e).__name__}")
    ed, text = nasdaq.earnings_date(f, t)
    if ed:
        facts.next_earnings = ed
        facts.next_earnings_source = "Nasdaq.com (" + ("estimated" if text and "expected" in text.lower() else "reported") + ")"
    if facts.last and (now - facts.last.as_of).total_seconds() > 4 * 86400:
        facts.stale = True
        facts.notes.append("Latest price is more than four days old.")
    return facts
