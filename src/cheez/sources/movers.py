"""Candidate discovery: large movers and today's notable earnings reporters.

These lists only nominate names for the research step to look at. A mover is
not an idea; most movers are skipped. Filters keep out illiquid and tiny
companies: market value of at least $2bn and price of at least $5.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from ..net import Fetcher
from . import nasdaq

SCREENER = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
MIN_CAP = 2e9
MIN_PRICE = 5.0


def yahoo_movers(f: Fetcher, scr: str, count: int = 25) -> list[dict]:
    data = f.get_json(SCREENER, params={"scrIds": scr, "count": count}, max_age=300)
    res = ((data or {}).get("finance") or {}).get("result") or []
    quotes = res[0].get("quotes", []) if res else []
    out = []
    for q in quotes:
        cap = q.get("marketCap") or 0
        px = q.get("regularMarketPrice") or 0
        if q.get("quoteType") != "EQUITY" or cap < MIN_CAP or px < MIN_PRICE:
            continue
        t = q.get("regularMarketTime")
        out.append({
            "symbol": q.get("symbol"),
            "name": q.get("longName") or q.get("shortName"),
            "change_pct": q.get("regularMarketChangePercent"),
            "price": px,
            "market_cap": cap,
            "as_of": datetime.fromtimestamp(t, tz=timezone.utc).isoformat() if t else None,
            "market_state": q.get("marketState"),
            "list": scr,
        })
    return out


def candidates(f: Fetcher, today: date, errors: Optional[list[str]] = None) -> dict:
    errors = errors if errors is not None else []
    out: dict = {"movers": [], "earnings_today": []}
    for scr in ("day_gainers", "day_losers", "most_actives"):
        try:
            out["movers"].extend(yahoo_movers(f, scr))
        except Exception as e:
            errors.append(f"Yahoo {scr}: {type(e).__name__}")
    rows = nasdaq.earnings_on(f, today)
    big = [r for r in rows if nasdaq.parse_market_cap(r.get("market_cap")) >= 10e9]
    big.sort(key=lambda r: -nasdaq.parse_market_cap(r.get("market_cap")))
    out["earnings_today"] = big[:25]
    if not rows:
        errors.append("Nasdaq earnings calendar returned no rows.")
    return out
