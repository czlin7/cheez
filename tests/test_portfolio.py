"""Currency handling, cash vs buying power, and misleading-return safeguards."""

from datetime import datetime, timezone
from types import SimpleNamespace as NS

from cheez.analytics.portfolio import FxBook, account_view, cash_available, holdings_index
from cheez.brokerage.longbridge import classify_flow, normalise_ap
from cheez.models import Account, CashLine, Coverage, FxRate, PortfolioSnapshot, Position

UTC = timezone.utc
NOW = datetime(2026, 11, 3, 12, 41, tzinfo=UTC)


def _acct(**kw):
    base = dict(label="A", base_currency="USD",
                cash=[CashLine(currency="USD", cash_balance=1000, available=1000),
                      CashLine(currency="HKD", cash_balance=7800, available=7800)],
                positions=[Position(symbol="AAPL.US", ticker="AAPL", currency="USD", quantity=10, last_price=200,
                                    market_value=2000, cost_price=150),
                           Position(symbol="700.HK", ticker="700.HK", currency="HKD", quantity=100, last_price=500,
                                    market_value=50000, cost_price=None)])
    base.update(kw)
    return Account(**base)


def test_never_sums_currencies_without_a_rate():
    av = account_view(_acct(), FxBook())  # no FX rates at all
    assert av.total_base is None and av.invested_base is None and av.cash_base is None
    assert any("HKD" in i for i in av.issues)
    # The HKD position's own-currency value is still shown, untouched.
    hk = next(p for p in av.positions if p.position.ticker == "700.HK")
    assert hk.value_ccy == 50000 and hk.value_base is None and hk.weight_pct is None


def test_explicit_rate_converts_and_is_recorded():
    fx = FxBook.from_rates([FxRate(pair="HKDUSD", rate=0.128, as_of=NOW, source="test")])
    av = account_view(_acct(), fx)
    assert round(av.invested_base, 2) == 2000 + 50000 * 0.128
    assert round(av.cash_base, 2) == round(1000 + 7800 * 0.128, 2)
    assert abs(sum(p.weight_pct for p in av.positions) - av.invested_base / av.total_base * 100) < 1e-6
    hk = next(p for p in av.positions if p.position.ticker == "700.HK")
    assert hk.fx_used is not None and hk.fx_used.pair == "HKDUSD"


def test_inverse_rate_is_used_correctly():
    fx = FxBook.from_rates([FxRate(pair="USDHKD", rate=7.8, as_of=NOW, source="test")])
    v, _ = fx.convert(7800, "HKD", "USD")
    assert abs(v - 1000) < 1e-9


def test_missing_cost_price_means_no_gain_or_loss():
    av = account_view(_acct(), FxBook.from_rates([FxRate(pair="HKDUSD", rate=0.128, as_of=NOW, source="t")]))
    hk = next(p for p in av.positions if p.position.ticker == "700.HK")
    assert hk.unrealised_pct is None and hk.unrealised_ccy is None
    us = next(p for p in av.positions if p.position.ticker == "AAPL")
    assert round(us.unrealised_pct, 4) == round((200 / 150 - 1) * 100, 4)


def test_performance_is_never_claimed_from_partial_history():
    a = _acct(executions_coverage=Coverage(retrieved_from=None, retrieved_to=None, complete=False))
    av = account_view(a, FxBook())
    assert "not calculated" in av.performance_note


def test_reconciliation_gap_is_flagged():
    fx = FxBook.from_rates([FxRate(pair="HKDUSD", rate=0.128, as_of=NOW, source="t")])
    av = account_view(_acct(net_assets=20000.0), fx)
    assert av.reconciliation_gap_pct is not None and abs(av.reconciliation_gap_pct) > 2
    assert any("differs from the broker" in i for i in av.issues)


def test_buying_power_and_borrowed_cash_are_not_spendable():
    bal = NS(currency="HKD", net_assets="24145.90", total_cash="-1000", max_finance_amount="5000",
             remaining_finance_amount="1000", risk_level=2, margin_call="0", buy_power="999999",
             cash_infos=[NS(currency="USD", available_cash="-38665.68", withdraw_cash="-38665.68", frozen_cash="0",
                            settling_cash="0"),
                         NS(currency="HKD", available_cash="500", withdraw_cash="400", frozen_cash="100",
                            settling_cash="0")])
    pos = NS(channels=[NS(account_channel="lb", positions=[])])
    [acct] = normalise_ap([bal], pos, [], [], [], {}, NOW, NOW, trade_read=True)
    usd = next(c for c in acct.cash if c.currency == "USD")
    hkd = next(c for c in acct.cash if c.currency == "HKD")
    assert usd.available == 0.0  # borrowed money is not available cash
    assert hkd.available == 400.0  # withdrawable, not "available" including unsettled/frozen
    assert "includes margin" in acct.margin_or_financing_note
    assert "Financing in use" in acct.margin_or_financing_note
    assert "risk level 2" in acct.margin_or_financing_note
    snap = PortfolioSnapshot(status="ok", accounts=[acct])
    assert cash_available(snap, "USD") == 0.0


def test_short_or_zero_lines_are_not_holdings_and_cost_zero_is_unknown():
    pos = NS(channels=[NS(account_channel="lb", positions=[
        NS(symbol="700.HK", symbol_name="T", quantity="650", available_quantity="-450", currency="HKD",
           cost_price="0", market="HK"),
        NS(symbol="XYZ.US", symbol_name="X", quantity="-10", available_quantity="-10", currency="USD",
           cost_price="5", market="US"),
    ])])
    [acct] = normalise_ap([], pos, [], [], [], {}, NOW, NOW, trade_read=False)
    assert [p.ticker for p in acct.positions] == ["700.HK"]
    p = acct.positions[0]
    assert p.cost_price is None  # an empty/zero cost from the SDK means unknown, never 0
    assert p.available_quantity == 0.0  # negative sellable quantity is clamped, never sold short


def test_duplicate_executions_and_flows_are_removed():
    ex = [NS(trade_id="T1", symbol="AAPL.US", side="OrderSide.Buy", quantity="1", price="100", trade_done_at=NOW)] * 3
    flows = [NS(transaction_flow_name="Dividend", balance="12", currency="USD", business_time=NOW, symbol="")] * 2
    pos = NS(channels=[NS(account_channel="lb", positions=[])])
    [acct] = normalise_ap([], pos, [], ex, flows, {}, NOW, NOW, trade_read=True)
    assert len(acct.executions) == 1 and len(acct.cash_flows) == 1
    assert acct.executions[0].trade_id != "T1"  # broker ids are hashed, not republished
    assert acct.executions_coverage.complete is False


def test_flows_are_classified_and_deposits_are_not_returns():
    assert classify_flow("Deposit-Cash") == "deposit"
    assert classify_flow("Withdrawal") == "withdrawal"
    assert classify_flow("Cash Dividend") == "dividend"
    assert classify_flow("BuyContract-Stocks") == "trade"
    assert classify_flow("Something odd") == "other"


def test_holdings_index_counts_sellable_quantity():
    snap = PortfolioSnapshot(status="ok", accounts=[_acct()])
    h = holdings_index(snap)
    assert h["AAPL"]["quantity"] == 10
    assert holdings_index(PortfolioSnapshot(status="error")) == {}
