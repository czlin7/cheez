"""Yahoo Finance chart endpoint (unofficial, public, no key).

Used for index levels, futures, FX, commodities and US stock prices including
extended hours. It is not a licensed real-time feed: exchange delays vary
(commonly up to 15-20 minutes for non-US indices and CME futures), and the
endpoint can change without notice. The report shows the provider and the
timestamp of every value, and Longbridge quotes replace Yahoo for single stocks
when a Longbridge connection is configured.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from ..models import Bar
from ..net import Fetcher

BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
UTC = timezone.utc


@dataclass
class ChartQuote:
    symbol: str
    name: Optional[str]
    currency: Optional[str]
    exchange: Optional[str]
    instrument_type: Optional[str]
    tz: str
    regular_price: Optional[float]
    regular_time: Optional[datetime]
    previous_close: Optional[float]
    # Extended-hours print (US stocks/ETFs only); None when not available.
    ext_price: Optional[float] = None
    ext_time: Optional[datetime] = None
    ext_kind: Optional[str] = None  # "pre_market" | "post_market"
    regular_start: Optional[datetime] = None
    regular_end: Optional[datetime] = None


def _ts(x: Optional[int]) -> Optional[datetime]:
    return datetime.fromtimestamp(x, tz=UTC) if x else None


def chart(f: Fetcher, symbol: str, range_: str, interval: str, prepost: bool = False, max_age: float = 300) -> dict:
    params = {"range": range_, "interval": interval}
    if prepost:
        params["includePrePost"] = "true"
    data = f.get_json(BASE + symbol, params=params, max_age=max_age)
    res = (data.get("chart") or {}).get("result")
    if not res:
        err = (data.get("chart") or {}).get("error")
        raise ValueError(f"no chart data for {symbol}: {err}")
    return res[0]


def live_quote(f: Fetcher, symbol: str, prepost: bool = False) -> ChartQuote:
    r = chart(f, symbol, "1d", "1m" if prepost else "5m", prepost=prepost, max_age=120)
    m = r.get("meta", {})
    tz = m.get("exchangeTimezoneName") or "America/New_York"
    period = (m.get("currentTradingPeriod") or {}).get("regular") or {}
    q = ChartQuote(
        symbol=symbol,
        name=m.get("longName") or m.get("shortName"),
        currency=m.get("currency"),
        exchange=m.get("fullExchangeName") or m.get("exchangeName"),
        instrument_type=m.get("instrumentType"),
        tz=tz,
        regular_price=m.get("regularMarketPrice"),
        regular_time=_ts(m.get("regularMarketTime")),
        previous_close=m.get("previousClose") or m.get("chartPreviousClose"),
        regular_start=_ts(period.get("start")),
        regular_end=_ts(period.get("end")),
    )
    if prepost:
        ts = r.get("timestamp") or []
        closes = ((r.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        pts = [(t, c) for t, c in zip(ts, closes) if c is not None]
        if pts and q.regular_start and q.regular_end:
            t, c = pts[-1]
            when = _ts(t)
            if when < q.regular_start:
                q.ext_price, q.ext_time, q.ext_kind = c, when, "pre_market"
            elif when >= q.regular_end:
                q.ext_price, q.ext_time, q.ext_kind = c, when, "post_market"
    return q


def daily_bars(f: Fetcher, symbol: str, range_: str = "1y") -> list[Bar]:
    r = chart(f, symbol, range_, "1d", max_age=3600)
    m = r.get("meta", {})
    tz = ZoneInfo(m.get("exchangeTimezoneName") or "America/New_York")
    ts = r.get("timestamp") or []
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    adj = ((r.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
    out: list[Bar] = []
    seen: set[date] = set()
    for i, t in enumerate(ts):
        c = (q.get("close") or [None])[i]
        if c is None:
            continue
        d = datetime.fromtimestamp(t, tz=UTC).astimezone(tz).date()
        if d in seen:
            continue
        seen.add(d)
        out.append(
            Bar(
                d=d,
                o=(q.get("open") or [None])[i],
                h=(q.get("high") or [None])[i],
                l=(q.get("low") or [None])[i],
                c=float(c),
                v=(q.get("volume") or [None])[i],
            )
        )
    _ = adj  # split-adjusted closes are already applied by the endpoint for OHLC
    return out
