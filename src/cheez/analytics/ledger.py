"""The ideas ledger: a dated, append-only record of published ideas.

What it records, and what it deliberately does not claim:

* A "zone touch" means a later daily high/low range overlapped the published
  entry zone. It is not an executable fill: spreads, gaps and queue position
  are unknown, and nobody is assumed to have traded.
* Hypothetical returns are measured from the zone midpoint, only after a zone
  touch, using daily closes. They are observations, not evidence of skill; the
  sample is small and selection effects are large.
* Account trades come from the broker's execution history and are never mixed
  into the ledger.
* Original entries are never edited. A changed view appears as a revision with
  its own date.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from ..models import Bar, Editorial, Ledger, LedgerEntry, LedgerOutcome, LedgerRevision, StockFacts


def record_edition(ledger: Ledger, ed: Editorial, on: date, stocks: dict[str, StockFacts], revision: int = 1) -> Ledger:
    by_id = {e.idea_id: e for e in ledger.entries}
    rev_tag = ed.edition_id if revision <= 1 else f"{ed.edition_id}#r{revision}"
    for idea in ed.ideas:
        target_id = idea.revision_of or idea.idea_id
        facts = stocks.get(idea.symbol.upper())
        px = None
        if facts:
            px = (facts.last or facts.regular_close).value if (facts.last or facts.regular_close) else None
        if target_id in by_id:
            entry = by_id[target_id]
            if any(r.edition_id == rev_tag for r in entry.revisions) or entry.edition_id == rev_tag:
                continue  # idempotent: re-rendering the same revision never duplicates anything
            if entry.edition_id == ed.edition_id and revision > 1 and _same_levels(entry, idea):
                continue  # a later revision that leaves this idea unchanged adds nothing
            entry.revisions.append(
                LedgerRevision(
                    edition_id=rev_tag,
                    on=on,
                    action=idea.action,
                    entry_low=idea.entry.low if idea.entry else None,
                    entry_high=idea.entry.high if idea.entry else None,
                    invalidation=idea.invalidation.level if idea.invalidation else None,
                    note=idea.revision_note,
                )
            )
            if idea.action in ("wait", "watch") and entry.action in ("consider_buying", "consider_adding"):
                entry.status = "closed_by_revision"
            continue
        entry = LedgerEntry(
            idea_id=idea.idea_id,
            symbol=idea.symbol.upper(),
            first_published=on,
            edition_id=ed.edition_id,
            action=idea.action,
            horizon_label=idea.horizon.label,
            horizon_max_days=idea.horizon.max_days,
            thesis=idea.thesis,
            entry_low=idea.entry.low if idea.entry else None,
            entry_high=idea.entry.high if idea.entry else None,
            invalidation=idea.invalidation.level if idea.invalidation else None,
            invalidation_meaning=idea.invalidation.meaning if idea.invalidation else None,
            price_at_publication=px,
        )
        ledger.entries.append(entry)
        by_id[entry.idea_id] = entry
    return ledger


def _same_levels(entry: LedgerEntry, idea) -> bool:
    lo, hi, inv = _current_levels(entry)
    return (idea.entry.low if idea.entry else None, idea.entry.high if idea.entry else None,
            idea.invalidation.level if idea.invalidation else None) == (lo, hi, inv) and idea.action == entry.action


def _current_levels(e: LedgerEntry) -> tuple[Optional[float], Optional[float], Optional[float]]:
    lo, hi, inv = e.entry_low, e.entry_high, e.invalidation
    for r in e.revisions:
        if r.entry_low is not None:
            lo, hi = r.entry_low, r.entry_high
        if r.invalidation is not None:
            inv = r.invalidation
    return lo, hi, inv


def evaluate(ledger: Ledger, histories: dict[str, list[Bar]], today: date) -> Ledger:
    """Recompute observed outcomes from daily bars after each idea's publication."""
    for e in ledger.entries:
        bars = [b for b in histories.get(e.symbol, []) if b.d > e.first_published]
        lo, hi, inv = _current_levels(e)
        out = LedgerOutcome(evaluated_on=today, days_open=(today - e.first_published).days)
        if bars:
            out.last_close = bars[-1].c
        if lo is not None and hi is not None:
            for b in bars:
                bl = b.l if b.l is not None else b.c
                bh = b.h if b.h is not None else b.c
                if out.zone_touched_on is None and bl <= hi and bh >= lo:
                    out.zone_touched_on = b.d
                if inv is not None and out.invalidation_touched_on is None and bl <= inv:
                    out.invalidation_touched_on = b.d
            if out.zone_touched_on and out.last_close is not None:
                mid = (lo + hi) / 2
                out.hypothetical_return_from_zone_mid_pct = (out.last_close / mid - 1) * 100
        if not bars:
            out.note = "No trading data since publication yet."
        e.outcome = out
        if e.status == "open":
            if out.invalidation_touched_on:
                e.status = "invalidated"
            elif out.days_open > e.horizon_max_days * 7 / 5 + 2:
                e.status = "expired"
    return ledger


def summary(ledger: Ledger) -> dict:
    n = len(ledger.entries)
    touched = [e for e in ledger.entries if e.outcome and e.outcome.zone_touched_on]
    return {
        "ideas": n,
        "open": sum(1 for e in ledger.entries if e.status == "open"),
        "zone_touched": len(touched),
        "invalidated": sum(1 for e in ledger.entries if e.status == "invalidated"),
        "caveat": (
            "Observed outcomes of published ideas are not evidence of skill: the sample is small, "
            "zone touches are not fills, and results ignore costs, gaps and taxes."
        ),
    }
