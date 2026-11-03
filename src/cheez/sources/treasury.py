"""US Treasury daily par yield curve (official, end of day).

Source: U.S. Department of the Treasury, "Daily Treasury Par Yield Curve Rates".
Rates are published each business day in the late afternoon New York time and
describe that day's close; they are not intraday prices.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from ..net import Fetcher

URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv"
)
PAGE = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve"
NY = ZoneInfo("America/New_York")


def curve(f: Fetcher, year: int) -> list[tuple[date, dict[str, float]]]:
    raw = f.get(URL.format(year=year), max_age=3600).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(raw)))
    out: list[tuple[date, dict[str, float]]] = []
    for r in rows:
        try:
            d = datetime.strptime(r["Date"], "%m/%d/%Y").date()
        except (KeyError, ValueError):
            continue
        vals: dict[str, float] = {}
        for k, v in r.items():
            if k == "Date" or not v:
                continue
            try:
                vals[k.strip()] = float(v)
            except ValueError:
                pass
        out.append((d, vals))
    out.sort(key=lambda x: x[0])
    return out


def recent_curve(f: Fetcher, today: date) -> list[tuple[date, dict[str, float]]]:
    rows = curve(f, today.year)
    if len(rows) < 70 and today.month <= 4:
        try:
            rows = curve(f, today.year - 1) + rows
        except Exception:
            pass
    return rows


def close_time(d: date) -> datetime:
    """Treasury's curve reflects indicative bid-side quotes near 15:30 New York time."""
    return datetime.combine(d, time(15, 30), tzinfo=NY).astimezone(timezone.utc)
