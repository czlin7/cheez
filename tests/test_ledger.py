"""Idea ledger: zone touches are not fills, revisions append, nothing is rewritten."""

import json
from datetime import date, timedelta
from pathlib import Path

from cheez.analytics import ledger as L
from cheez.models import Bar, Editorial, Ledger

ROOT = Path(__file__).resolve().parents[1]


def _ed(eid="2026-11-03-us"):
    d = json.loads((ROOT / "fixtures/demo/editorial.json").read_text())
    d["edition_id"] = eid
    return Editorial.model_validate(d)


def test_record_is_idempotent(demo_world):
    _, stocks, _ = demo_world
    led = Ledger()
    L.record_edition(led, _ed(), date(2026, 11, 3), stocks)
    L.record_edition(led, _ed(), date(2026, 11, 3), stocks)
    assert len(led.entries) == 3
    e = next(x for x in led.entries if x.symbol == "NWSC")
    assert e.entry_low == 158.0 and e.invalidation == 149.5 and e.price_at_publication is not None


def test_revision_appends_and_keeps_original(demo_world):
    _, stocks, _ = demo_world
    led = Ledger()
    L.record_edition(led, _ed(), date(2026, 11, 3), stocks)
    ed2 = _ed("2026-11-04-us")
    nw = next(i for i in ed2.ideas if i.symbol == "NWSC")
    nw.revision_of = nw.idea_id
    nw.idea_id = "2026-11-04-NWSC"
    nw.entry.low, nw.entry.high = 155.0, 162.0
    nw.revision_note = "Lowered after results were delayed."
    L.record_edition(led, ed2, date(2026, 11, 4), stocks)
    e = next(x for x in led.entries if x.symbol == "NWSC")
    assert e.entry_low == 158.0  # original untouched
    assert e.revisions[-1].entry_low == 155.0 and e.revisions[-1].on == date(2026, 11, 4)
    assert len([x for x in led.entries if x.symbol == "NWSC"]) == 1


def test_zone_touch_is_not_a_fill_and_invalidation_is_tracked(demo_world):
    _, stocks, _ = demo_world
    led = Ledger()
    L.record_edition(led, _ed(), date(2026, 11, 3), stocks)
    bars = [
        Bar(d=date(2026, 11, 4), h=172.0, l=167.0, c=169.0),  # above the zone
        Bar(d=date(2026, 11, 5), h=168.0, l=165.5, c=166.5),  # range overlaps zone top (166)
        Bar(d=date(2026, 11, 6), h=160.0, l=148.0, c=150.0),  # pierces invalidation 149.5
    ]
    L.evaluate(led, {"NWSC": bars}, date(2026, 11, 6))
    e = next(x for x in led.entries if x.symbol == "NWSC")
    assert e.outcome.zone_touched_on == date(2026, 11, 5)
    assert e.outcome.invalidation_touched_on == date(2026, 11, 6)
    assert e.status == "invalidated"
    assert round(e.outcome.hypothetical_return_from_zone_mid_pct, 4) == round((150 / 162 - 1) * 100, 4)
    s = L.summary(led)
    assert "not evidence of skill" in s["caveat"]


def test_no_return_without_zone_touch(demo_world):
    _, stocks, _ = demo_world
    led = Ledger()
    L.record_edition(led, _ed(), date(2026, 11, 3), stocks)
    L.evaluate(led, {"NWSC": [Bar(d=date(2026, 11, 4), h=180, l=170, c=175)]}, date(2026, 11, 4))
    e = next(x for x in led.entries if x.symbol == "NWSC")
    assert e.outcome.zone_touched_on is None and e.outcome.hypothetical_return_from_zone_mid_pct is None


def test_ideas_expire_after_horizon(demo_world):
    _, stocks, _ = demo_world
    led = Ledger()
    L.record_edition(led, _ed(), date(2026, 11, 3), stocks)
    later = date(2026, 11, 3) + timedelta(days=400)
    L.evaluate(led, {}, later)
    assert all(e.status == "expired" for e in led.entries)
