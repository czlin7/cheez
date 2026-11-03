"""The editorial validator: unsupported levels, long-only/cash-only rules,
certainty language and personalisation without data."""

import json
from pathlib import Path

import pytest

from cheez import session as sess
from cheez.demo import DEMO_NOW
from cheez.editorial.validate import validate
from cheez.models import Editorial, PortfolioSnapshot

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def fresh(demo_world):
    """Return a factory of independent copies so each scenario starts clean."""
    import copy

    market, stocks, portfolio = demo_world
    ed = json.loads((ROOT / "fixtures/demo/editorial.json").read_text())
    ed["edition_id"] = "2026-11-03-us"

    def make():
        return copy.deepcopy((ed, market, stocks, portfolio))

    return make


@pytest.fixture()
def base(fresh):
    return fresh()


def run(ed, market, stocks, portfolio):
    return validate(Editorial.model_validate(ed), edition_id="2026-11-03-us", session=market.session, stocks=stocks,
                    portfolio=portfolio, instrument_keys={i.key for i in market.instruments})


def test_demo_editorial_is_valid(base):
    rep = run(*base)
    assert rep.ok, rep.errors
    d = rep.derived["2026-11-03-NWSC"]
    assert d.reward_risk is not None and d.reward_risk_basis  # computed only because all inputs exist


def test_unknown_basis_and_remote_levels_are_rejected(fresh):
    ed, m, s, p = fresh()
    ed["ideas"][0]["entry"]["basis"] = ["sma999"]
    rep = run(ed, m, s, p)
    assert any("unknown facts" in e for e in rep.errors)
    ed["ideas"][0]["entry"]["basis"] = ["high_52w"]  # 210.76: nowhere near a 158-166 zone
    rep = run(ed, m, s, p)
    assert any("lie near the zone" in e for e in rep.errors)


def test_entry_above_price_and_inverted_invalidation_rejected(fresh):
    ed, m, s, p = fresh()
    ed["ideas"][0]["entry"].update({"low": 190.0, "high": 200.0})
    rep = run(ed, m, s, p)
    assert any("above the last price" in e for e in rep.errors)
    ed, m, s, p = fresh()
    ed["ideas"][0]["invalidation"]["level"] = 170.0
    rep = run(ed, m, s, p)
    assert any("must sit below the entry zone" in e for e in rep.errors)


def test_buy_idea_requires_levels_and_conditions(base):
    ed, m, s, p = base
    ed["ideas"][0]["entry"] = None
    rep = run(ed, m, s, p)
    assert any("needs an entry zone" in e for e in rep.errors)


def test_no_reward_risk_without_targets(base):
    ed, m, s, p = base
    for sc in ed["ideas"][0]["scenarios"]:
        sc["target"] = None
    rep = run(ed, m, s, p)
    assert rep.ok, rep.errors
    assert rep.derived["2026-11-03-NWSC"].reward_risk is None


@pytest.mark.parametrize("text", [
    "Consider selling short if it breaks down.",
    "Buy call options ahead of results.",
    "You could buy on margin to increase exposure.",
    "Consider using futures contracts instead.",
])
def test_long_only_cash_only(base, text):
    ed, m, s, p = base
    ed["ideas"][0]["why_now"] = text
    rep = run(ed, m, s, p)
    assert any("long-only cash equity" in e for e in rep.errors), rep.errors


def test_derivatives_as_market_context_are_allowed(base):
    ed, m, s, p = base
    ed["market_read"]["summary"] = "Options traders are paying up for downside protection and futures point lower."
    assert run(ed, m, s, p).ok


@pytest.mark.parametrize("text, kind", [
    ("This entry is guaranteed to work.", "certainty"),
    ("A safe entry for patient holders.", "certainty"),
    ("The stock will recover by spring.", "certainty"),
    ("We see a 70% chance of a rebound.", "probabilities"),
    ("Confidence 8/10.", "probabilities"),
    ("Fair value is $212.40 on our model.", "fair values"),
])
def test_certainty_probability_and_precision_language(base, text, kind):
    ed, m, s, p = base
    ed["ideas"][0]["thesis"] = text
    rep = run(ed, m, s, p)
    assert any(kind in e for e in rep.errors), rep.errors


def test_negated_disclaimer_is_allowed(base):
    ed, m, s, p = base
    ed["ideas"][0]["invalidation"]["gap_risk"] = "Prices can gap; this is not a guaranteed exit price."
    assert run(ed, m, s, p).ok


def test_share_counts_are_not_published(base):
    ed, m, s, p = base
    ed["ideas"][1]["conditions"] = ["Sell 90 shares to halve the position."]
    rep = run(ed, m, s, p)
    assert any("position sizes" in e for e in rep.errors)


def test_trim_requires_a_holding_with_sellable_quantity(fresh):
    ed, m, s, p = fresh()
    ed["ideas"][1]["symbol"] = "QRTZ"  # not held
    rep = run(ed, m, s, p)
    assert any("requires a current holding" in e for e in rep.errors)
    ed, m, s, p = fresh()
    p.accounts[0].positions[0].available_quantity = 0  # HLDX locked (e.g. pending sell order)
    rep = run(ed, m, s, p)
    assert any("no sellable quantity" in e for e in rep.errors)


def test_personalised_ideas_withheld_without_portfolio(base):
    ed, m, s, _ = base
    rep = run(ed, m, s, PortfolioSnapshot(status="unconfigured"))
    assert any("portfolio data is unavailable" in e for e in rep.errors)
    assert any("no portfolio data is available" in e for e in rep.errors)  # holding notes in commentary


def test_illiquid_and_leveraged_are_rejected(fresh):
    ed, m, s, p = fresh()
    s["NWSC"].technicals.avg_dollar_volume_20d = 1_000_000
    rep = run(ed, m, s, p)
    assert any("too illiquid" in e for e in rep.errors)
    ed, m, s, p = fresh()
    s["NWSC"].identity.name = "Ultra 3x Semiconductor Bull ETF"
    rep = run(ed, m, s, p)
    assert any("leveraged" in e for e in rep.errors)


def test_unverified_or_ambiguous_ticker_rejected(fresh):
    ed, m, s, p = fresh()
    ed["featured"][0]["symbol"] = "NOPE"
    rep = run(ed, m, s, p)
    assert any("no verified market data" in e for e in rep.errors)
    ed, m, s, p = fresh()
    s["NWSC"].identity.ambiguous = True
    rep = run(ed, m, s, p)
    assert any("ambiguous" in e for e in rep.errors)


def test_earnings_inside_horizon_must_be_addressed(base):
    ed, m, s, p = base
    idea = ed["ideas"][0]
    idea["costs_and_risks"] = [x for x in idea["costs_and_risks"] if "arn" not in x]
    idea["catalyst"] = "A product update."
    idea["conditions"] = ["Price trades within 158–166 on a closing basis."]
    idea["why_now"] = "The shares have fallen."
    rep = run(ed, m, s, p)
    assert any("earnings" in e for e in rep.errors)


def test_no_quota_but_explicit_no_setup_statement(base):
    ed, m, s, p = base
    ed["ideas"] = []
    ed["no_setup_statement"] = None
    rep = run(ed, m, s, p)
    assert any("no compelling setup" in e for e in rep.errors)
    ed["no_setup_statement"] = "Nothing clears the bar today."
    assert run(ed, m, s, p).ok


def test_closed_day_cannot_carry_decisions_for_today(base):
    ed, m, s, p = base
    from datetime import datetime, timezone

    m.session = sess.us_session_context(datetime(2026, 11, 26, 12, 41, tzinfo=timezone.utc))
    rep = run(ed, m, s, p)
    assert any("closed today" in e for e in rep.errors)


def test_wrong_edition_id_rejected(base):
    ed, m, s, p = base
    ed["edition_id"] = "2026-11-02-us"
    assert any("edition_id" in e for e in run(ed, m, s, p).errors)
    _ = DEMO_NOW
