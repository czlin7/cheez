"""Nasdaq.com public calendar endpoints (earnings dates and the day's earnings list).

These are public website endpoints, not a licensed API; dates marked
"expected" are estimates until the company confirms them.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from ..net import Fetcher

HEADERS = {"Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com",
           "Referer": "https://www.nasdaq.com/"}


def earnings_date(f: Fetcher, ticker: str) -> tuple[Optional[date], Optional[str]]:
    """Next earnings date for a US ticker and the provider's own wording."""
    url = f"https://api.nasdaq.com/api/analyst/{ticker.upper()}/earnings-date"
    try:
        data = f.get_json(url, headers=HEADERS, max_age=6 * 3600)
    except Exception:
        return None, None
    text = ((data or {}).get("data") or {}).get("reportText") or ""
    m = re.search(r"(\d{2}/\d{2}/\d{4})", text)
    if not m:
        return None, text or None
    try:
        d = datetime.strptime(m.group(1), "%m/%d/%Y").date()
    except ValueError:
        return None, text
    return d, re.sub(r"\s+", " ", text).strip()


def earnings_on(f: Fetcher, d: date) -> list[dict]:
    url = f"https://api.nasdaq.com/api/calendar/earnings?date={d.isoformat()}"
    try:
        data = f.get_json(url, headers=HEADERS, max_age=3 * 3600)
    except Exception:
        return []
    rows = (((data or {}).get("data") or {}).get("rows")) or []
    out = []
    for r in rows:
        out.append({
            "symbol": r.get("symbol"),
            "name": r.get("name"),
            "time": {"time-pre-market": "before open", "time-after-hours": "after close"}.get(r.get("time"), "time not supplied"),
            "market_cap": r.get("marketCap"),
            "eps_forecast": r.get("epsForecast"),
        })
    return out


def parse_market_cap(s: Optional[str]) -> float:
    if not s:
        return 0.0
    try:
        return float(s.replace("$", "").replace(",", ""))
    except ValueError:
        return 0.0
