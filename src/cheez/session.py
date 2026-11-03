"""Trading-calendar and session logic.

Everything here is deterministic and keyed to exchange-local time, so US/UK
daylight-saving mismatches, holidays and early closes are handled by the
calendar data rather than by hard-coded UTC offsets.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xc
import pandas as pd

from .models import SessionContext, SessionLabel

NY = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")
UTC = timezone.utc

# US equity extended-hours windows (exchange local time).
PRE_MARKET_START = time(4, 0)
POST_MARKET_END = time(20, 0)


@lru_cache(maxsize=16)
def calendar(code: str = "XNYS"):
    # Extend the default horizon so the scheduler never runs off the end of the data.
    today = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
    start = (today - pd.Timedelta(days=800)).strftime("%Y-%m-%d")
    for ahead in (500, 300, 120, 30):
        try:
            return xc.get_calendar(code, start=start, end=(today + pd.Timedelta(days=ahead)).strftime("%Y-%m-%d"))
        except Exception:
            continue  # some exchanges (e.g. Shanghai) publish next year's holidays late
    return xc.get_calendar(code)


def _ts(d: date) -> pd.Timestamp:
    return pd.Timestamp(d.isoformat())


def is_session(d: date, code: str = "XNYS") -> bool:
    return bool(calendar(code).is_session(_ts(d)))


def session_bounds(d: date, code: str = "XNYS") -> tuple[datetime, datetime]:
    cal = calendar(code)
    o = cal.session_open(_ts(d)).to_pydatetime()
    c = cal.session_close(_ts(d)).to_pydatetime()
    return o.astimezone(UTC), c.astimezone(UTC)


def is_early_close(d: date, code: str = "XNYS") -> bool:
    cal = calendar(code)
    try:
        return _ts(d) in cal.early_closes
    except Exception:  # pragma: no cover - defensive against library changes
        return False


def previous_session(d: date, code: str = "XNYS") -> date:
    cal = calendar(code)
    return cal.date_to_session(_ts(d - timedelta(days=1)), direction="previous").date()


def next_session(d: date, code: str = "XNYS") -> date:
    cal = calendar(code)
    return cal.date_to_session(_ts(d + timedelta(days=1)), direction="next").date()


def latest_completed_session(now_utc: datetime, code: str = "XNYS") -> date:
    """The most recent session whose regular close is at or before ``now_utc``."""
    cal = calendar(code)
    local = now_utc.astimezone(ZoneInfo(str(cal.tz)))
    d = local.date()
    if is_session(d, code):
        _, close = session_bounds(d, code)
        if now_utc >= close:
            return d
    return previous_session(d, code)


def holiday_name(d: date, code: str = "XNYS") -> str | None:
    """Best-effort holiday name for a non-session weekday."""
    if d.weekday() >= 5:
        return None
    cal = calendar(code)
    try:
        hols = cal.regular_holidays.holidays(_ts(d), _ts(d), return_name=True)
        if len(hols):
            return str(hols.iloc[0])
    except Exception:
        pass
    try:
        for adhoc in cal.adhoc_holidays:
            if pd.Timestamp(adhoc).date() == d:
                return "Market closure"
    except Exception:
        pass
    return "Market holiday"


def us_session_context(now_utc: datetime) -> SessionContext:
    """Describe where NYSE is in its day, from the point of view of ``now_utc``."""
    local = now_utc.astimezone(NY)
    d = local.date()
    notes: list[str] = []
    if not is_session(d):
        name = holiday_name(d)
        if name:
            notes.append(f"US markets are closed today ({name}).")
        else:
            notes.append("US markets are closed today (weekend).")
        return SessionContext(
            edition_date=d,
            is_trading_day=False,
            phase="closed_day",
            previous_session=previous_session(d),
            next_session=next_session(d),
            holiday_name=name,
            notes=notes,
        )
    o, c = session_bounds(d)
    early = is_early_close(d)
    if early:
        notes.append(f"Early close today at {c.astimezone(NY):%H:%M} New York time "
                     f"({c.astimezone(LONDON):%H:%M} London).")
    if o.astimezone(LONDON).strftime("%H:%M") != "14:30":
        notes.append(f"US and UK clocks are out of step this week: the US opens at "
                     f"{o.astimezone(LONDON):%H:%M} London time.")
    if now_utc < o:
        phase = "pre_open"
    elif now_utc < c:
        phase = "regular"
    elif local.time() < POST_MARKET_END:
        phase = "post_close"
    else:
        phase = "overnight"
    return SessionContext(
        edition_date=d,
        is_trading_day=True,
        phase=phase,
        open_utc=o,
        close_utc=c,
        early_close=early,
        previous_session=previous_session(d),
        next_session=next_session(d),
        notes=notes,
    )


def us_equity_session_label(ts_utc: datetime) -> SessionLabel:
    """Label a US stock/ETF print by the session it occurred in."""
    local = ts_utc.astimezone(NY)
    d = local.date()
    if not is_session(d):
        # Weekend/holiday prints are overnight-venue or stale prints.
        return "overnight"
    o, c = session_bounds(d)
    if o <= ts_utc < c:
        return "regular_live"
    if local.time() >= PRE_MARKET_START and ts_utc < o:
        return "pre_market"
    if ts_utc >= c and local.time() < POST_MARKET_END:
        return "post_market"
    return "overnight"


def exchange_session_label(ts_utc: datetime, code: str, now_utc: datetime) -> SessionLabel:
    """Label an index print: live if its exchange is in session at ``now_utc`` and the
    print is from today's session; otherwise it is that session's close."""
    try:
        return _exchange_session_label(ts_utc, code, now_utc)
    except Exception:
        # Calendar data can lag (e.g. China's holidays are published late each year).
        return "unknown"


def _exchange_session_label(ts_utc: datetime, code: str, now_utc: datetime) -> SessionLabel:
    cal = calendar(code)
    tz = ZoneInfo(str(cal.tz))
    d = ts_utc.astimezone(tz).date()
    if is_session(d, code):
        o, c = session_bounds(d, code)
        if o <= now_utc < c and o <= ts_utc <= c:
            return "regular_live"
    return "regular_close"


def fmt_london(ts: datetime) -> str:
    return ts.astimezone(LONDON).strftime("%H:%M %Z")


def fmt_ny(ts: datetime) -> str:
    return ts.astimezone(NY).strftime("%H:%M %Z")


def edition_id(edition_date: date, kind: str = "us-pre") -> str:
    return f"{edition_date.isoformat()}-{kind}"
