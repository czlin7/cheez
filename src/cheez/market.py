"""Build the deterministic cross-asset snapshot for an edition."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import session as sess
from .config import INSTRUMENTS, STALE_INSTRUMENT_HOURS, InstrumentDef
from .models import Bar, DisplayFx, Instrument, MarketSnapshot, Price, SourceStatus
from .net import Fetcher, FetchError
from .sources import treasury, yahoo

UTC = timezone.utc
YAHOO_NOTE = (
    "Yahoo Finance public chart data; not an exchange-licensed feed. Exchange delays vary "
    "(often up to 15–20 minutes for non-US indices and CME futures)."
)


def _fmt_day(d) -> str:
    return d.strftime("%a %-d %b")


def _calendar_ok(code: str, now: datetime) -> bool:
    try:
        sess.latest_completed_session(now, code)
        return True
    except Exception:
        return False


def _yahoo_instrument(f: Fetcher, spec: InstrumentDef, now: datetime) -> Instrument:
    inst = Instrument(
        key=spec.key,
        label=spec.label,
        group=spec.group,
        kind=spec.kind,  # type: ignore[arg-type]
        symbol=spec.symbol,
        source="yahoo",
        source_url=f"https://finance.yahoo.com/quote/{spec.symbol}",
        unit=spec.unit,
        delay_note=YAHOO_NOTE,
        notes=[spec.note] if spec.note else [],
    )
    q = yahoo.live_quote(f, spec.symbol)
    inst.currency = q.currency
    inst.exchange_tz = q.tz
    try:
        bars = yahoo.daily_bars(f, spec.symbol, "6mo")
        inst.history = [Bar(d=b.d, c=b.c) for b in bars[-66:]]
    except (FetchError, ValueError) as e:
        inst.notes.append(f"History unavailable: {e}")
    if q.regular_price is None or q.regular_time is None:
        inst.stale = True
        inst.stale_reason = "No price returned by the provider."
        return inst

    as_of = q.regular_time
    age_h = (now - as_of).total_seconds() / 3600
    if spec.kind in ("index", "volatility_index", "yield") and spec.calendar and _calendar_ok(spec.calendar, now):
        label = sess.exchange_session_label(as_of, spec.calendar, now)
        local_day = as_of.astimezone(sess.calendar(spec.calendar).tz).date()
        expected = sess.latest_completed_session(now, spec.calendar)
        if label == "regular_close" and local_day < expected:
            inst.stale = True
            inst.stale_reason = f"Latest value is from {_fmt_day(local_day)}; expected the {_fmt_day(expected)} close."
        prev_day = sess.previous_session(local_day, spec.calendar) if sess.is_session(local_day, spec.calendar) else None
        basis = f"vs {_fmt_day(prev_day)} close" if prev_day else "vs previous close"
        if label == "regular_close" and local_day < now.astimezone(sess.calendar(spec.calendar).tz).date():
            inst.notes.append(f"Market not open yet or closed today; showing the {_fmt_day(local_day)} close.")
    elif spec.kind in ("index_future", "commodity_future"):
        label = "futures_live" if age_h < 2 else "end_of_day"
        basis = "vs prior settlement"
        if now.weekday() < 5 and age_h > STALE_INSTRUMENT_HOURS:
            inst.stale, inst.stale_reason = True, f"Last trade {age_h:.0f} hours ago."
    elif spec.kind in ("index", "volatility_index", "yield"):
        label = "unknown"  # exchange calendar unavailable: show the timestamp, claim nothing
        basis = "vs previous close (provider)"
        inst.notes.append("Exchange calendar data unavailable; session not labelled.")
    else:  # fx, dollar index
        label = "fx_live" if age_h < 2 else "end_of_day"
        basis = "vs previous close (provider)"
        if now.weekday() < 5 and age_h > STALE_INSTRUMENT_HOURS:
            inst.stale, inst.stale_reason = True, f"Last quote {age_h:.0f} hours ago."

    inst.last = Price(value=float(q.regular_price), as_of=as_of, session=label)  # type: ignore[arg-type]
    if q.previous_close:
        inst.reference = Price(value=float(q.previous_close), as_of=as_of, session="regular_close")
        inst.change_abs = q.regular_price - q.previous_close
        inst.change_pct = (q.regular_price / q.previous_close - 1) * 100
        if spec.kind == "yield":
            inst.change_bp = inst.change_abs * 100
        inst.change_basis = basis
    return inst


def _treasury_instruments(f: Fetcher, now: datetime) -> list[Instrument]:
    rows = treasury.recent_curve(f, now.date())
    if len(rows) < 2:
        raise FetchError("Treasury curve returned fewer than two rows")
    out: list[Instrument] = []
    for tenor, key, label in (("2 Yr", "ust2y", "US 2-year Treasury yield"), ("10 Yr", "ust10y", "US 10-year Treasury yield")):
        series = [(d, v[tenor]) for d, v in rows if tenor in v]
        (d1, v1), (d0, v0) = series[-1], series[-2]
        inst = Instrument(
            key=key,
            label=label,
            group="Rates",
            kind="yield",
            symbol=f"Treasury par curve {tenor}",
            source="treasury",
            source_url=treasury.PAGE,
            currency="USD",
            unit="%",
            exchange_tz="America/New_York",
            last=Price(value=v1, as_of=treasury.close_time(d1), session="end_of_day"),
            reference=Price(value=v0, as_of=treasury.close_time(d0), session="end_of_day"),
            change_abs=v1 - v0,
            change_bp=(v1 - v0) * 100,
            change_basis=f"vs {_fmt_day(d0)} (official daily close)",
            history=[Bar(d=d, c=v) for d, v in series[-66:]],
            delay_note="Official end-of-day par yield, published by the US Treasury each business day.",
        )
        expected = sess.latest_completed_session(now)
        if d1 < sess.previous_session(expected) :
            inst.stale = True
            inst.stale_reason = f"Latest official curve is {_fmt_day(d1)}."
        out.append(inst)
    # Curve slope as a derived row-note, computed deterministically.
    two = out[0].last.value if out[0].last else None
    ten = out[1].last.value if out[1].last else None
    if two is not None and ten is not None:
        out[1].notes.append(f"10-year minus 2-year spread: {(ten - two) * 100:+.0f} bp.")
    return out


def build_snapshot(f: Fetcher, now: datetime, specs: Optional[list[InstrumentDef]] = None) -> MarketSnapshot:
    ctx = sess.us_session_context(now)
    instruments: list[Instrument] = []
    sources: list[SourceStatus] = []
    ok = 0
    failures: list[str] = []
    for spec in specs or INSTRUMENTS:
        try:
            try:
                instruments.append(_yahoo_instrument(f, spec, now))
            except ValueError:  # provider occasionally returns an empty result; retry once
                time.sleep(1.0)
                instruments.append(_yahoo_instrument(f, spec, now))
            ok += 1
        except Exception as e:  # one bad symbol never sinks the edition
            failures.append(f"{spec.label}: {type(e).__name__}")
            instruments.append(
                Instrument(
                    key=spec.key, label=spec.label, group=spec.group, kind=spec.kind,  # type: ignore[arg-type]
                    symbol=spec.symbol, source="yahoo", unit=spec.unit, stale=True,
                    stale_reason="Provider did not return data this run.",
                )
            )
    sources.append(
        SourceStatus(source="Yahoo Finance chart API", ok=ok > 0, fetched_at=now, items=ok,
                     detail=("Failed: " + "; ".join(failures)) if failures else None)
    )
    try:
        tre = _treasury_instruments(f, now)
        # Put official yields ahead of the live proxy in the Rates group.
        idx = next((i for i, x in enumerate(instruments) if x.group == "Rates"), len(instruments))
        instruments[idx:idx] = tre
        sources.append(SourceStatus(source="US Treasury par yield curve", ok=True, fetched_at=now, items=len(tre)))
    except Exception as e:
        sources.append(SourceStatus(source="US Treasury par yield curve", ok=False, fetched_at=now, detail=str(e)[:200]))
    cutoff = max((i.last.as_of for i in instruments if i.last), default=now)
    return MarketSnapshot(generated_at=now, data_cutoff=min(cutoff, now), session=ctx,
                          instruments=instruments, sources=sources, display_fx=display_fx(f, now))


def display_fx(f: Fetcher, now: datetime) -> DisplayFx:
    """USD rates for the optional "also show prices in" annotation. Best effort:
    a currency that fails is simply not offered."""
    from .settings import DISPLAY_CURRENCIES

    out = DisplayFx(per_usd={"USD": 1.0}, as_of=now)
    for c in DISPLAY_CURRENCIES:
        if c == "USD":
            continue
        try:
            q = yahoo.live_quote(f, f"{c}=X")
            if q.regular_price:
                out.per_usd[c] = float(q.regular_price)
                out.as_of = min(out.as_of or now, q.regular_time or now)
        except Exception:
            continue
    return out


def snapshot_problems(snap: MarketSnapshot) -> list[str]:
    probs = []
    missing = [i.label for i in snap.instruments if i.last is None]
    stale = [i.label for i in snap.instruments if i.stale and i.last is not None]
    if missing:
        probs.append("Missing: " + ", ".join(missing))
    if stale:
        probs.append("Stale: " + ", ".join(stale))
    return probs


def now_utc() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)


_ = timedelta
