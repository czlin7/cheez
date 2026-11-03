"""Portfolio arithmetic with explicit currency handling.

Rules enforced here (each has a test):

* Amounts in different currencies are never added together. Consolidation
  happens only through an explicit, timestamped FX rate, and the rate is shown.
* Broker "buying power" includes financing and is never treated as spendable cash.
* Unrealised gain/loss is shown only against a broker-reported cost price and is
  labelled as such; realised P&L and performance are withheld unless the trade
  and cash-flow history is complete for the period, which a partial API history
  cannot prove.
* Deposits, withdrawals and FX conversions are flows, not investment returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..models import Account, FxRate, PortfolioSnapshot, Position


@dataclass
class FxBook:
    rates: dict[tuple[str, str], FxRate] = field(default_factory=dict)

    @classmethod
    def from_rates(cls, rates: list[FxRate]) -> "FxBook":
        book = cls()
        for r in rates:
            a, b = r.pair[:3].upper(), r.pair[3:].upper()
            book.rates[(a, b)] = r
        return book

    def convert(self, amount: float, src: str, dst: str) -> Optional[tuple[float, Optional[FxRate]]]:
        src, dst = src.upper(), dst.upper()
        if src == dst:
            return amount, None
        if (src, dst) in self.rates:
            r = self.rates[(src, dst)]
            return amount * r.rate, r
        if (dst, src) in self.rates:
            r = self.rates[(dst, src)]
            return amount / r.rate, r
        return None  # unknown: refuse rather than guess


@dataclass
class PositionView:
    position: Position
    value_ccy: Optional[float]  # market value in the position's own currency
    value_base: Optional[float]  # converted to the account base currency, if possible
    weight_pct: Optional[float]  # of the account's convertible total
    unrealised_pct: Optional[float]  # vs broker cost price, price-only, position currency
    unrealised_ccy: Optional[float]
    fx_used: Optional[FxRate]
    issues: list[str] = field(default_factory=list)


@dataclass
class AccountView:
    account: Account
    base: Optional[str]
    positions: list[PositionView]
    invested_base: Optional[float]
    cash_base: Optional[float]
    total_base: Optional[float]  # positions + cash converted; None if any piece unconvertible
    broker_net_assets: Optional[float]
    reconciliation_gap_pct: Optional[float]
    top_weight_pct: Optional[float]
    top3_weight_pct: Optional[float]
    effective_positions: Optional[float]  # 1 / sum(w^2)
    cash_by_currency: list[tuple[str, Optional[float], Optional[float]]]  # (ccy, balance, available)
    performance_note: str
    issues: list[str] = field(default_factory=list)


def _position_value(p: Position) -> Optional[float]:
    if p.market_value is not None:
        return p.market_value
    if p.last_price is not None:
        return p.last_price * p.quantity
    return None


def account_view(acct: Account, fx: FxBook) -> AccountView:
    base = acct.base_currency
    issues: list[str] = []
    pviews: list[PositionView] = []
    invested = 0.0
    convertible = base is not None
    for p in acct.positions:
        pis: list[str] = []
        v = _position_value(p)
        vb: Optional[float] = None
        used: Optional[FxRate] = None
        if v is None:
            pis.append("No current price; value not computed.")
            convertible = False
        elif base:
            conv = fx.convert(v, p.currency, base)
            if conv is None:
                pis.append(f"No {p.currency}/{base} rate; not included in totals.")
                convertible = False
            else:
                vb, used = conv
                invested += vb
        ur_pct = ur_ccy = None
        if p.cost_price and p.last_price and p.cost_price > 0 and p.quantity > 0:
            ur_pct = (p.last_price / p.cost_price - 1) * 100
            ur_ccy = (p.last_price - p.cost_price) * p.quantity
        pviews.append(PositionView(p, v, vb, None, ur_pct, ur_ccy, used, pis))

    cash_total = 0.0
    cash_lines = []
    for c in acct.cash:
        cash_lines.append((c.currency, c.cash_balance, c.available))
        if c.cash_balance is None:
            continue
        if base:
            conv = fx.convert(c.cash_balance, c.currency, base)
            if conv is None:
                issues.append(f"Cash in {c.currency} could not be converted to {base}; totals withheld.")
                convertible = False
            else:
                cash_total += conv[0]

    total = (invested + cash_total) if convertible else None
    if total and invested > 0:
        for pv in pviews:
            if pv.value_base is not None:
                pv.weight_pct = pv.value_base / total * 100
    weights = sorted([pv.weight_pct for pv in pviews if pv.weight_pct is not None], reverse=True)
    eff = None
    if weights:
        s = sum((w / 100) ** 2 for w in weights)
        eff = 1 / s if s > 0 else None

    gap = None
    if total is not None and acct.net_assets:
        gap = (total / acct.net_assets - 1) * 100
        if abs(gap) > 2.0:
            issues.append(
                f"Cheez's valuation differs from the broker's net assets by {gap:+.1f}%; "
                "prices, FX or financing may differ. Broker figure shown as reported."
            )

    exec_cov = acct.executions_coverage
    perf = (
        "Performance and realised P&L are not calculated: the broker API history retrieved "
        f"covers {exec_cov.retrieved_from or 'unknown'} to {exec_cov.retrieved_to or 'unknown'} "
        "and cannot prove the full trade and deposit record. Unrealised figures compare the latest "
        "price with the broker's reported average cost in the position's own currency."
    )
    return AccountView(
        account=acct,
        base=base,
        positions=sorted(pviews, key=lambda x: -(x.value_base or 0)),
        invested_base=invested if convertible else None,
        cash_base=cash_total if convertible else None,
        total_base=total,
        broker_net_assets=acct.net_assets,
        reconciliation_gap_pct=gap,
        top_weight_pct=weights[0] if weights else None,
        top3_weight_pct=sum(weights[:3]) if weights else None,
        effective_positions=eff,
        cash_by_currency=cash_lines,
        performance_note=perf,
        issues=issues,
    )


def holdings_index(snap: Optional[PortfolioSnapshot]) -> dict[str, dict]:
    """Ticker -> combined quantity facts across accounts (for sell-side validation)."""
    out: dict[str, dict] = {}
    if not snap or snap.status not in ("ok", "partial"):
        return out
    for a in snap.accounts:
        for p in a.positions:
            rec = out.setdefault(p.ticker.upper(), {"quantity": 0.0, "available": 0.0, "accounts": []})
            rec["quantity"] += p.quantity
            rec["available"] += p.available_quantity if p.available_quantity is not None else 0.0
            rec["accounts"].append(a.label)
    return out


def cash_available(snap: Optional[PortfolioSnapshot], currency: str) -> Optional[float]:
    """Cash (not buying power) available in ``currency`` across accounts."""
    if not snap or snap.status not in ("ok", "partial"):
        return None
    tot = 0.0
    seen = False
    for a in snap.accounts:
        for c in a.cash:
            if c.currency.upper() == currency.upper() and c.available is not None:
                tot += c.available
                seen = True
    return tot if seen else 0.0
